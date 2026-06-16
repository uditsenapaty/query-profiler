# =========================================================
# scripts/per_method_processors/summarise.py
# =========================================================

from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config_gt


# =========================================================
# helpers
# =========================================================

STRUCTURAL_CODE_ORDER = [
    ("R", "ROOT"),
    ("J", "JOIN"),
    ("S", "SCAN"),
    ("A", "AGG"),
    ("X", "AUX"),
    ("P", "PARALLEL"),
    ("D", "DML"),
    ("T", "STRUCTURE"),
]


def _safe_str(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def _normalize_verdict(v):
    """
    Supports both old boolean plan_change and new string verdicts.
    Always returns one of: STRUCTURAL | PARAMETRIC | IDENTICAL
    """
    s = _safe_str(v).upper()

    if s in {"STRUCTURAL", "PARAMETRIC", "IDENTICAL"}:
        return s

    if s in {"TRUE", "T", "1", "YES"}:
        return "STRUCTURAL"

    if s in {"FALSE", "F", "0", "NO"}:
        return "IDENTICAL"

    return "IDENTICAL"


def _is_structural(plan_change_value):
    """
    Return True if the (already-normalized) plan_change value
    represents a structural change.
    Handles both legacy boolean strings and current verdict strings.
    """
    s = str(plan_change_value).strip().upper()
    return s in {"STRUCTURAL", "TRUE", "T", "1", "YES"}


def _first_existing_value(row, candidates, default=np.nan):
    for c in candidates:
        if c in row.index:
            v = row.get(c, default)
            if pd.notna(v):
                return v
    return default


def _percent_str(count, total):
    if total <= 0:
        return "0 of 0 (0.00%)"
    return f"{count} of {total} ({100.0 * count / total:.2f}%)"


def _pick_qerr_axis(base_row, qcols):
    """
    Returns the axis (1-based), qerr value, verdict, change_type and parameter_change
    for the axis with the highest q-error.
    """
    best = None

    for qcol in qcols:
        axis = int(qcol.split("_x")[-1])

        q = base_row.get(qcol, np.nan)
        if not np.isfinite(q) or q <= 0:
            continue

        verdict = _normalize_verdict(
            _first_existing_value(
                base_row,
                [
                    f"plan_change_x{axis}",
                    f"verdict_x{axis}",
                    "plan_change",
                    "verdict",
                ],
                "IDENTICAL",
            )
        )

        change_type = _safe_str(
            _first_existing_value(
                base_row,
                [
                    f"change_type_x{axis}",
                    f"structural_change_x{axis}",
                    f"shape_change_type_x{axis}",
                    "change_type",
                    "structural_change",
                    "shape_change_type",
                ],
                "",
            )
        )

        parameter_change = _safe_str(
            _first_existing_value(
                base_row,
                [
                    f"parameter_change_x{axis}",
                    "parameter_change",
                ],
                "",
            )
        )

        if best is None or q > best["max_qerr"]:
            best = {
                "axis": axis,
                "max_qerr": float(q),
                "plan_change": verdict,
                "change_type": change_type,
                "parameter_change": parameter_change,
            }

    return best


def _parse_structural_codes(change_type):
    """
    Accepts strings like:
      JAX12
      R3
      JAX12|Pc
      0
      IDENTICAL
    Returns a list of single-letter structural codes found at the front.
    """
    s = _safe_str(change_type)
    if not s:
        return []

    s_up = s.upper()
    if s_up in {"0", "IDENTICAL"}:
        return []

    if "|PC" in s_up:
        s = s.split("|Pc", 1)[0]
        s_up = s.upper().split("|PC", 1)[0]

    if s_up.startswith("PC"):
        return []

    m = re.match(r"^([A-Z]+)", s_up)
    if not m:
        return []

    codes = list(m.group(1))
    valid = {c for c, _ in STRUCTURAL_CODE_ORDER}
    return [c for c in codes if c in valid]


def _parse_param_tokens(parameter_change, change_type=None):
    """
    Returns tokens like:
      literal
      label
      literal|label -> ["literal", "label"]

    If parameter_change is missing, tries to infer from change_type
    where possible, e.g. Pc(literal|label) or Pc(literal).
    """
    s = _safe_str(parameter_change)

    if not s and change_type is not None:
        ct = _safe_str(change_type)
        if "|Pc(" in ct or ct.startswith("Pc("):
            m = re.search(r"Pc\((.*?)\)", ct, flags=re.IGNORECASE)
            if m:
                s = m.group(1).strip()
        elif ct.upper().endswith("|PC"):
            return ["Pc"]

    if not s:
        return []

    s_up = s.upper()
    if s_up in {"NONE", "0", "IDENTICAL", "NAN"}:
        return []

    if s_up == "PC":
        return ["Pc"]

    if s_up.startswith("PC(") and s.endswith(")"):
        s = s[3:-1].strip()

    tokens = [
        t.strip()
        for t in s.split("|")
        if t.strip() and t.strip().lower() != "none"
    ]

    return tokens


def _format_transition_counts(sub, verdict_filter, kind_col, parser):
    """
    Counts component hits among rows matching verdict_filter.
    Returns dict(code -> 'count/total (pct%)')
    """
    if kind_col not in sub.columns:
        return {name: "0/0 (0.00%)" for _, name in STRUCTURAL_CODE_ORDER}

    filtered = sub[sub["plan_change"] == verdict_filter].copy()
    total = len(filtered)

    out = {}
    for code, name in STRUCTURAL_CODE_ORDER:
        if total == 0:
            out[name] = "0/0 (0.00%)"
            continue

        hits = filtered[kind_col].apply(
            lambda v: code in parser(v)
        ).sum()

        out[name] = _percent_str(int(hits), total)

    return out


def _format_param_tokens(sub):
    """
    Counts parameter tokens among rows that have any parametric change.
    """
    if "parameter_change" not in sub.columns and "change_type" not in sub.columns:
        return {}

    tokens_series = sub.apply(
        lambda r: _parse_param_tokens(
            r.get("parameter_change", ""),
            r.get("change_type", "")
        ),
        axis=1
    )

    has_param = tokens_series.apply(lambda xs: len(xs) > 0)
    filtered_tokens = tokens_series[has_param]

    total = len(filtered_tokens)
    if total == 0:
        return {}

    token_counts = {}
    all_tokens = []
    for xs in filtered_tokens:
        all_tokens.extend(xs)

    for tok in sorted(set(all_tokens)):
        hits = sum(tok in xs for xs in filtered_tokens)
        token_counts[tok] = _percent_str(int(hits), total)

    return token_counts


def _pick_top_subset(sub, frac):
    n = max(1, int(np.ceil(len(sub) * frac)))
    return sub.nlargest(n, "max_qerr").copy()


def _add_row(rows, section, metric, value):
    rows.append(
        {
            "Section": section,
            "Metric": metric,
            "Value": value,
        }
    )


# =========================================================
# Processor entry
# =========================================================

def run(results_dir):

    results_dir = Path(results_dir)

    edge_csv_path = (
        results_dir
        / "qerr_sorted"
        / "qerr_desc.csv"
    )

    point_csv_path = (
        results_dir
        / config_gt.RESULTS_FILENAME
    )

    if not edge_csv_path.exists():
        print(f"Missing:\n{edge_csv_path}")
        return

    if not point_csv_path.exists():
        print(f"Missing:\n{point_csv_path}")
        return

    # edge table
    df = pd.read_csv(edge_csv_path)

    # point table
    points_df = pd.read_csv(point_csv_path)

    print()
    print("=" * 60)
    print("QUERY GROUND TRUTH SUMMARY")
    print("=" * 60)

    query_name = config_gt.query_name_from_path(
        config_gt.QUERY_SQL_PATH
    ).upper()

    # =====================================================
    # Identify q-error columns
    # =====================================================

    qcols = sorted([
        c for c in df.columns
        if c.startswith("adjacent_qerr_x")
    ])

    # =====================================================
    # Merge / normalize source table
    # =====================================================
    # qerr_desc.csv already has one row per qerr instance
    # with a single "qerr" column and a single "plan_change"
    # column (already normalized by qerr_desc.py).
    # The qcols branch handles older ground_truth.csv-style
    # files where axes are stored as separate columns.
    # =====================================================

    if qcols:
        rows = []

        for _, base_row in df.iterrows():

            best = _pick_qerr_axis(base_row, qcols)
            if best is None:
                continue

            rows.append(
                {
                    "rank": int(base_row.get("rank", len(rows) + 1)),
                    "instance_id": base_row.get("instance_id", len(rows) + 1),
                    "x1": base_row.get("x1", np.nan),
                    "x2": base_row.get("x2", np.nan),
                    "max_axis": best["axis"],
                    "max_qerr": best["max_qerr"],
                    "plan_change": best["plan_change"],
                    "change_type": best["change_type"],
                    "parameter_change": best["parameter_change"],
                    "runtime_mean": base_row.get("runtime_mean", np.nan),
                    "plan_hash": base_row.get("plan_hash", np.nan),
                    "count_rows": base_row.get("count_rows", np.nan),
                }
            )

        merged = pd.DataFrame(rows)

    else:
        merged = df.copy()

        if "qerr" not in merged.columns:
            print("No qerr column found.")
            return

        merged["max_qerr"] = merged["qerr"]

        if "axis" in merged.columns and "max_axis" not in merged.columns:
            merged["max_axis"] = merged["axis"]

        # Normalize plan_change to verdict strings
        if "plan_change" in merged.columns:
            merged["plan_change"] = merged["plan_change"].apply(
                _normalize_verdict
            )

    if merged.empty:
        print("No valid rows.")
        return

    merged = merged[np.isfinite(merged["max_qerr"])]
    merged = merged[merged["max_qerr"] > 0].copy()

    if merged.empty:
        print("No positive q-error rows.")
        return

    # =====================================================
    # Basic stats
    # =====================================================

    runtime_col = (
        "runtime_mean"
        if "runtime_mean" in points_df.columns
        else None
    )

    max_rt = (
        points_df[runtime_col].max()
        if runtime_col else np.nan
    )

    mean_rt = (
        points_df[runtime_col].mean()
        if runtime_col else np.nan
    )

    min_rt = (
        points_df[runtime_col].min()
        if runtime_col else np.nan
    )

    total_rt = (
        points_df[runtime_col].sum()
        if runtime_col else np.nan
    )

    min_count_rows = (
        points_df["count_rows"].min()
        if "count_rows" in points_df.columns
        else np.nan
    )

    max_count_rows = (
        points_df["count_rows"].max()
        if "count_rows" in points_df.columns
        else np.nan
    )

    max_qerr  = merged["max_qerr"].max()
    mean_qerr = merged["max_qerr"].mean()
    min_qerr  = merged["max_qerr"].min()

    # =====================================================
    # FIX: plan_change is now always a normalized verdict
    # string ("STRUCTURAL" / "PARAMETRIC" / "IDENTICAL").
    # The old check for {"TRUE","T","1","YES"} always
    # returned 0 because _normalize_verdict had already
    # converted those to "STRUCTURAL".
    # Use _is_structural() which handles both forms.
    # =====================================================

    plan_changes = int(
        merged["plan_change"]
        .apply(_is_structural)
        .sum()
    )

    unique_hashes = int(
        points_df["plan_hash"].nunique(dropna=True)
    ) if "plan_hash" in points_df.columns else 0

    # =====================================================
    # Top 1% / Top 10%
    # =====================================================

    top1  = _pick_top_subset(merged, 0.01)
    top10 = _pick_top_subset(merged, 0.10)

    # Same fix applied to top-subset counts
    top1_plan_changes = int(
        top1["plan_change"]
        .apply(_is_structural)
        .sum()
    )

    top10_plan_changes = int(
        top10["plan_change"]
        .apply(_is_structural)
        .sum()
    )

    # =====================================================
    # Structural transition stats
    # =====================================================

    structural_all = _format_transition_counts(
        merged,
        "STRUCTURAL",
        "change_type",
        _parse_structural_codes
    )
    structural_top1 = _format_transition_counts(
        top1,
        "STRUCTURAL",
        "change_type",
        _parse_structural_codes
    )
    structural_top10 = _format_transition_counts(
        top10,
        "STRUCTURAL",
        "change_type",
        _parse_structural_codes
    )

    # =====================================================
    # Parametric changes
    # =====================================================

    def _has_any_param(r):
        return len(
            _parse_param_tokens(
                r.get("parameter_change", ""),
                r.get("change_type", "")
            )
        ) > 0

    any_param_all  = merged[merged.apply(_has_any_param, axis=1)].copy()
    any_param_top1 = top1[top1.apply(_has_any_param, axis=1)].copy()
    any_param_top10 = top10[top10.apply(_has_any_param, axis=1)].copy()

    param_tokens_all  = _format_param_tokens(any_param_all)
    param_tokens_top1 = _format_param_tokens(any_param_top1)
    param_tokens_top10 = _format_param_tokens(any_param_top10)

    # =====================================================
    # Build vertical summary
    # =====================================================

    out_rows = []

    _add_row(out_rows, "Basic stats", "Query", query_name)
    _add_row(out_rows, "Basic stats", "max_rt", max_rt)
    _add_row(out_rows, "Basic stats", "mean_rt", mean_rt)
    _add_row(out_rows, "Basic stats", "min_rt", min_rt)
    _add_row(out_rows, "Basic stats", "total_rt", total_rt)

    _add_row(out_rows, "Basic stats", "min_count_rows", min_count_rows)
    _add_row(out_rows, "Basic stats", "max_count_rows", max_count_rows)

    _add_row(out_rows, "Basic stats", "max_qerr", max_qerr)
    _add_row(out_rows, "Basic stats", "mean_qerr", mean_qerr)
    _add_row(out_rows, "Basic stats", "min_qerr", min_qerr)

    _add_row(out_rows, "Basic stats", "Total_Plan_changes", f"{plan_changes} of {len(merged)}")
    _add_row(out_rows, "Basic stats", "Unique_hashes", unique_hashes)
    _add_row(out_rows, "Basic stats", "top1%_plan_changes",  f"{top1_plan_changes} of {len(top1)}")
    _add_row(out_rows, "Basic stats", "top10%_plan_changes", f"{top10_plan_changes} of {len(top10)}")

    _add_row(out_rows, "Plan operator transition stats (all)", "JOIN_transitions",      structural_all["JOIN"])
    _add_row(out_rows, "Plan operator transition stats (all)", "SCAN_transitions",      structural_all["SCAN"])
    _add_row(out_rows, "Plan operator transition stats (all)", "AGG_transitions",       structural_all["AGG"])
    _add_row(out_rows, "Plan operator transition stats (all)", "AUX_transitions",       structural_all["AUX"])
    _add_row(out_rows, "Plan operator transition stats (all)", "PAR_transitions",       structural_all["PARALLEL"])
    _add_row(out_rows, "Plan operator transition stats (all)", "ROOT_transitions",      structural_all["ROOT"])
    _add_row(out_rows, "Plan operator transition stats (all)", "DML_transitions",       structural_all["DML"])
    _add_row(out_rows, "Plan operator transition stats (all)", "STRUCTURE_transitions", structural_all["STRUCTURE"])

    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "JOIN_transitions",      structural_top1["JOIN"])
    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "SCAN_transitions",      structural_top1["SCAN"])
    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "AGG_transitions",       structural_top1["AGG"])
    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "AUX_transitions",       structural_top1["AUX"])
    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "PAR_transitions",       structural_top1["PARALLEL"])
    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "ROOT_transitions",      structural_top1["ROOT"])
    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "DML_transitions",       structural_top1["DML"])
    _add_row(out_rows, "Plan operator transition stats (top 1% qerr)", "STRUCTURE_transitions", structural_top1["STRUCTURE"])

    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "JOIN_transitions",      structural_top10["JOIN"])
    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "SCAN_transitions",      structural_top10["SCAN"])
    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "AGG_transitions",       structural_top10["AGG"])
    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "AUX_transitions",       structural_top10["AUX"])
    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "PAR_transitions",       structural_top10["PARALLEL"])
    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "ROOT_transitions",      structural_top10["ROOT"])
    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "DML_transitions",       structural_top10["DML"])
    _add_row(out_rows, "Plan operator transition stats (top 10% qerr)", "STRUCTURE_transitions", structural_top10["STRUCTURE"])

    formatted_rows = []

    last_section = None

    for _, r in pd.DataFrame(out_rows).iterrows():

        if r["Section"] != last_section:

            formatted_rows.append(
                {
                    "Section": r["Section"],
                    "Metric": "",
                    "Value": ""
                }
            )

            last_section = r["Section"]

        formatted_rows.append(
            {
                "Section": "",
                "Metric": r["Metric"],
                "Value": r["Value"]
            }
        )

    summary_df = pd.DataFrame(formatted_rows)

    # =====================================================
    # Print
    # =====================================================

    print()
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(summary_df.to_string(index=False))

    # =====================================================
    # Save
    # =====================================================

    out_csv = results_dir / "summary.csv"
    summary_df.to_csv(out_csv, index=False)

    print()
    print(f"Saved:\n{out_csv}")
    print()
    print("DONE")


if __name__ == "__main__":

    run(
        "gt_results_sf10_qt8/100x100/m1"
    )