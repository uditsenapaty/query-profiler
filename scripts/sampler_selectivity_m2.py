# =========================================================
# sampler_selectivity_m2.py
#
# Method 2: Picasso-style histogram interpolation.
#
# Reads PostgreSQL's optimizer statistics (pg_stats) for
# the column — histogram_bounds, most_common_vals (MCVs),
# and most_common_freqs (MCFs) — builds an approximate CDF
# of the form
#
#     CDF(x) = sum(MCF_i where MCV_i <= x)
#            + (1 - sum(MCF)) * frac_of_histogram_bucket(x)
#
# and inverts it at the target selectivities to obtain
# parameter values. This mirrors what the Picasso 2.1
# `PostgresHistogram` class does
# (PicassoServer/.../db/postgres/PostgresHistogram.java).
#
# Pros: zero table scans (uses cached stats); same
#       selectivity-space view the optimizer itself sees.
# Cons: only as good as `default_statistics_target` /
#       ANALYZE freshness; selectivities are *estimated*,
#       not exact.
# =========================================================

import numpy as np


def _target_selectivities(resolution):
    return [(i + 0.5) / resolution for i in range(resolution)]


def _read_pg_stats(conn, table, column):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT histogram_bounds::text,
               most_common_vals::text,
               most_common_freqs
        FROM pg_stats
        WHERE tablename = %s AND attname = %s
        """,
        (table, column),
    )
    row = cur.fetchone()
    cur.close()

    if row is None:
        raise RuntimeError(
            f"No pg_stats row for {table}.{column} — run ANALYZE first."
        )

    return row  # (hist_str, mcv_str, freqs)


def _parse_array_text(s, caster):
    """Parse a Postgres array-text representation, e.g. '{1,2,3}'."""
    if s is None:
        return []
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    if not s:
        return []
    # naive split — pg_stats numeric/date columns don't quote
    return [caster(tok.strip().strip('"')) for tok in s.split(",")]


def _cast_for_column(conn, table, column):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    row = cur.fetchone()
    cur.close()
    dtype = row[0] if row else "double precision"

    if dtype in ("integer", "bigint", "smallint"):
        return int, dtype
    if dtype.startswith("numeric") or dtype in ("real", "double precision"):
        return float, dtype
    if dtype == "date":
        import datetime

        def to_date(s):
            return datetime.date.fromisoformat(s)

        return to_date, dtype
    return float, dtype


def _interp(lo, hi, frac):
    """Linear interpolation between two values of the same type."""
    if hasattr(lo, "toordinal"):
        a = lo.toordinal()
        b = hi.toordinal()
        return type(lo).fromordinal(int(round(a + frac * (b - a))))
    return lo + frac * (hi - lo)


def _build_cdf_table(hist_bounds, mcv_vals, mcv_freqs):
    """
    Merge histogram-bound buckets and MCV spikes into a
    sorted list of (value, cumulative_selectivity) pairs.

    Histogram buckets each carry weight (1 - sum(MCF)) / B
    where B = len(hist_bounds) - 1. MCV points add their
    individual frequency mass as a discrete jump at that
    value.
    """
    mcf_sum = sum(mcv_freqs) if mcv_freqs else 0.0
    B = max(len(hist_bounds) - 1, 1)
    bucket_mass = (1.0 - mcf_sum) / B if hist_bounds else 0.0

    # Discrete jumps from MCVs.
    mcv_lookup = dict(zip(mcv_vals, mcv_freqs))

    # Build a piecewise-linear CDF over the histogram, and
    # add MCV jumps where their value lies. We emit pairs
    # at each histogram bound and at each MCV value.
    pts = []  # list of (value, cdf)
    cdf = 0.0
    if not hist_bounds:
        # fall back to MCV-only
        for v in sorted(mcv_lookup.keys()):
            cdf += mcv_lookup[v]
            pts.append((v, cdf))
        return pts

    # First bound contributes 0 mass (left endpoint).
    pts.append((hist_bounds[0], 0.0))
    for i in range(1, len(hist_bounds)):
        # add MCV jumps strictly inside (prev, cur] before
        # the histogram bucket increment
        prev_v = hist_bounds[i - 1]
        cur_v = hist_bounds[i]
        spikes = sorted(
            v for v in mcv_lookup if (v > prev_v) and (v <= cur_v)
        )
        for v in spikes:
            cdf += mcv_lookup[v]
            pts.append((v, cdf))
        cdf += bucket_mass
        pts.append((cur_v, cdf))

    # MCVs outside the histogram range (rare).
    for v, f in mcv_lookup.items():
        if v < hist_bounds[0] or v > hist_bounds[-1]:
            cdf += f
            pts.append((v, cdf))

    pts.sort(key=lambda p: (p[1], 0 if hasattr(p[0], "toordinal") else p[0]))
    return pts


def _invert(cdf_pts, target_sel):
    """
    Given a sorted-by-cdf list of (value, cdf) points,
    return the value v such that cdf(v) == target_sel by
    linear interpolation.
    """
    if target_sel <= cdf_pts[0][1]:
        return cdf_pts[0][0]
    for i in range(1, len(cdf_pts)):
        v_lo, c_lo = cdf_pts[i - 1]
        v_hi, c_hi = cdf_pts[i]
        if c_lo <= target_sel <= c_hi:
            if c_hi == c_lo:
                return v_lo
            frac = (target_sel - c_lo) / (c_hi - c_lo)
            return _interp(v_lo, v_hi, frac)
    return cdf_pts[-1][0]


def sample(conn, table, column, resolution):
    """
    Return `resolution` parameter values such that, under
    the optimizer's pg_stats histogram, P(col <= v_i) ~=
    (i + 0.5) / resolution.
    """
    hist_str, mcv_str, mcv_freqs = _read_pg_stats(conn, table, column)
    cast, _dtype = _cast_for_column(conn, table, column)

    hist_bounds = _parse_array_text(hist_str, cast)
    mcv_vals = _parse_array_text(mcv_str, cast)
    mcv_freqs = list(mcv_freqs) if mcv_freqs else []

    cdf_pts = _build_cdf_table(hist_bounds, mcv_vals, mcv_freqs)

    sels = _target_selectivities(resolution)
    return [_invert(cdf_pts, s) for s in sels]


def selectivities(resolution):
    return _target_selectivities(resolution)
