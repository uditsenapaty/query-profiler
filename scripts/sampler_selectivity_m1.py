# =========================================================
# sampler_selectivity_m1.py
#
# Method 1: percentile_cont — exact CDF inverse from data.
#
# For a target selectivity s in (0, 1) on a predicate
# `col <= v`, the value v that achieves exactly that
# selectivity is the s-th percentile of `col`. We ask
# PostgreSQL for those percentiles directly in a single
# pass:
#
#     SELECT percentile_cont(ARRAY[s1, s2, ...])
#            WITHIN GROUP (ORDER BY col)
#     FROM   tab;
#
# Selectivities are exact w.r.t. the actual data (not
# estimator stats). Single table scan per axis.
#
# Pros: exact, uniform-in-selectivity grid by construction.
# Cons: full scan per axis (cached afterwards); only valid
#       for "<= :p" style predicates.
# =========================================================

import numpy as np
import psycopg2.sql as sql


def _target_selectivities(resolution):
    """
    Cell-center selectivities in (0, 1):
       s_i = (i + 0.5) / N    for i = 0 .. N-1
    This matches Picasso's uniform-grid convention and
    avoids the degenerate endpoints 0 and 1.
    """
    return [(i + 0.5) / resolution for i in range(resolution)]


def sample(conn, table, column, resolution):
    """
    Return `resolution` values v_1 < v_2 < ... < v_N such
    that  P(col <= v_i)  ~=  (i + 0.5)/N  exactly
    (computed by percentile_cont on the live data).
    """
    sels = _target_selectivities(resolution)

    query = sql.SQL("""
        SELECT percentile_cont(%s::float8[])
               WITHIN GROUP (ORDER BY {col})
        FROM {tbl}
    """).format(
        col=sql.Identifier(column),
        tbl=sql.Identifier(table),
    )

    cur = conn.cursor()
    cur.execute(query, (sels,))
    values = cur.fetchone()[0]
    cur.close()

    # percentile_cont returns floats; keep the native column
    # type when it makes sense (ints / dates would otherwise
    # break the `:p` substitution downstream).
    return _coerce(values, conn, table, column)


def _coerce(values, conn, table, column):
    """Cast the float percentiles back to the column's type."""
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
        return [int(round(v)) for v in values]

    if dtype in ("date",):
        # values are floats representing ordinal-ish; round
        # and cast back via DB
        cur = conn.cursor()
        out = []
        for v in values:
            cur.execute("SELECT DATE 'epoch' + (%s)::int", (int(round(v)),))
            # Fallback: just return float; caller substitutes
            # with isoformat — better to use percentile result
            # as-is.
            out.append(v)
        cur.close()
        return out

    return [float(v) for v in values]


def selectivities(resolution):
    """Expose the target selectivities for logging/metadata."""
    return _target_selectivities(resolution)
