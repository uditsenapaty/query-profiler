# =========================================================
# scripts/per_method_processors/qerr_desc.py
# =========================================================

from pathlib import Path
import sys
import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from tpch.utils.comparator import compare, _classify
except Exception:
    from comparator import compare, _classify


# =========================================================
# change-code mappings
# =========================================================

# Structural / guaranteed change codes:
# R = ROOT, J = JOIN, S = SCAN, A = AGG, X = AUX,
# P = PARALLEL, D = DML, T = STRUCTURE
STRUCTURAL_CATEGORY_ORDER = (
    "ROOT",
    "JOIN",
    "SCAN",
    "AGG",
    "AUX",
    "PARALLEL",
    "DML",
    "STRUCTURE",
)

STRUCTURAL_CODE_MAP = {
    "ROOT": "R",
    "JOIN": "J",
    "SCAN": "S",
    "AGG": "A",
    "AUX": "X",
    "PARALLEL": "P",
    "DML": "D",
    "STRUCTURE": "T",
}

# Column name for each structural category change detail
CATEGORY_CHANGE_COLS = tuple(
    f"{cat}_change"
    for cat in STRUCTURAL_CATEGORY_ORDER
)


# =========================================================
# helpers
# =========================================================

def _get_plan_path_from_row(row):
    """
    Try the common plan path column names.
    The path is assumed to be relative to RESULTS_DIR unless absolute.
    """
    for key in (
        "plan_json_path",
        "plan_path",
        "json_path",
    ):
        if key in row.index:
            val = row.get(key)
            if pd.notna(val) and str(val).strip():
                return str(val).strip()
    return None


def _load_plan_json(results_dir, row, cache):
    """
    Load plan JSON for a dataframe row.
    Cache key is the absolute path string.
    """
    if row is None:
        return None

    rel_path = _get_plan_path_from_row(row)
    if rel_path is None:
        return None

    path = Path(rel_path)
    if not path.is_absolute():
        path = Path(results_dir) / path

    cache_key = str(path)
    if cache_key in cache:
        return cache[cache_key]

    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    cache[cache_key] = plan
    return plan


def _parameter_change_from_cmp(cmp):
    """
    Kept only for internal compatibility.
    Not written to output anymore.
    """
    kinds = []

    if any(a.kind == "label" for a in cmp.attributions):
        kinds.append("label")

    if any(a.kind == "literal" for a in cmp.attributions):
        kinds.append("literal")

    return "none" if not kinds else "|".join(kinds)


def _structural_change_from_cmp(cmp):
    """
    Returns e.g.:
      0
      JAX12
      R3
      SP5
    """
    if cmp.verdict != "STRUCTURAL":
        return "0"

    code = "".join(
        STRUCTURAL_CODE_MAP.get(category, "")
        for category in STRUCTURAL_CATEGORY_ORDER
        if category in cmp.change_types
    )

    if not code:
        code = "T"

    #return f"{code}{cmp.distance}"
    return code


def _change_type_from_cmp(cmp):
    """
    Compact change type only.

    Returns:
      0
      Pc
      JAX12
    """
    if cmp.verdict == "IDENTICAL":
        return "0"

    if cmp.verdict == "PARAMETRIC":
        return "none"

    return _structural_change_from_cmp(cmp)


def _category_change_details(cmp):
    """
    Returns a dict mapping each structural category to a human-readable
    change string, e.g.:

      {
        "ROOT":      "same",
        "JOIN":      "Join Type: Hash Join -> Nested Loop",
        "SCAN":      "Index Name: orders_pkey -> none; Relation Name: orders -> lineitem",
        "AGG":       "same",
        "AUX":       "same",
        "PARALLEL":  "same",
        "DML":       "same",
        "STRUCTURE": "same",
      }

    When the verdict is not STRUCTURAL every category is "same".
    When plans were unavailable every category is NaN.
    """
    result = {cat: "same" for cat in STRUCTURAL_CATEGORY_ORDER}

    if cmp.verdict != "STRUCTURAL":
        return result

    # bucket witnesses by category
    category_witnesses = {cat: [] for cat in STRUCTURAL_CATEGORY_ORDER}

    for w in cmp.witnesses:
        for cat in _classify(w):
            if cat in category_witnesses:
                category_witnesses[cat].append(w)

    for cat in STRUCTURAL_CATEGORY_ORDER:
        wits = category_witnesses[cat]
        if not wits:
            continue
        parts = []
        for w in wits:
            a_str = str(w.a) if w.a is not None else "none"
            b_str = str(w.b) if w.b is not None else "none"
            parts.append(f"{w.key}: {a_str} -> {b_str}")
        result[cat] = "; ".join(parts)

    return result


# =========================================================
# main
# =========================================================

def run(results_dir):

    RESULTS_DIR = Path(results_dir)

    CSV_PATH = (
        RESULTS_DIR /
        "ground_truth.csv"
    )

    OUTPUT_DIR = (
        RESULTS_DIR /
        "qerr_sorted"
    )

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    print()
    print("=" * 48)
    print("MERGING ALL QERR INSTANCES")
    print("=" * 48)

    # =========================================================
    # LOAD
    # =========================================================

    df = pd.read_csv(
        CSV_PATH
    )

    # =========================================================
    # PARAMETER COLUMNS
    # =========================================================

    x_cols = sorted([
        c
        for c in df.columns
        if (
            c.startswith("x")
            and "_neighbor_" not in c
        )
    ])

    # =========================================================
    # FAST LOOKUP:
    # coordinate tuple → row
    # =========================================================

    lookup = {}

    for _, row in df.iterrows():
        key = tuple(
            row[c]
            for c in x_cols
        )
        lookup[key] = row

    # =========================================================
    # FIND AXES
    # =========================================================

    qcols = sorted([
        c for c in df.columns
        if c.startswith("adjacent_qerr_x")
    ])

    rows = []
    instance_id = 0
    plan_cache = {}

    # =========================================================
    # BUILD INSTANCES
    # =========================================================

    for qcol in qcols:

        axis = int(
            qcol.split("_x")[-1]
        )

        pcol = (
            f"plan_change_x{axis}"
        )

        if pcol not in df.columns:
            continue

        valid = df.loc[
            np.isfinite(
                df[qcol]
            )
        ]

        for _, row in valid.iterrows():

            instance = {}

            instance[
                "instance_id"
            ] = instance_id

            instance[
                "axis"
            ] = axis

            instance[
                "qerr"
            ] = row[qcol]

            instance[
                "plan_change"
            ] = row[pcol]

            # =====================================
            # current point coordinates
            # =====================================

            for c in x_cols:
                instance[c] = row[c]

            # =====================================
            # exact neighbor coordinates
            # =====================================

            neighbor_coords = []

            for c in x_cols:

                ncol = (
                    f"{c}_neighbor_axis{axis}"
                )

                val = row.get(
                    ncol,
                    np.nan
                )

                instance[
                    f"{c}_neighbor"
                ] = val

                neighbor_coords.append(val)

            # =====================================
            # lookup exact neighboring point
            # =====================================

            neighbor_key = tuple(
                neighbor_coords
            )

            neighbor_row = lookup.get(
                neighbor_key,
                None
            )

            # =====================================
            # Boundary flag
            # Yes if current OR neighbor point
            # touches min/max on ANY axis
            # =====================================

            boundary = False

            for c in x_cols:

                vals = np.sort(
                    df[c].unique()
                )

                minv = vals[0]
                maxv = vals[-1]

                current_val = row[c]

                neighbor_val = row.get(
                    f"{c}_neighbor_axis{axis}",
                    np.nan
                )

                current_boundary = (
                    current_val == minv
                    or current_val == maxv
                )

                neighbor_boundary = (
                    not pd.isna(
                        neighbor_val
                    )
                    and
                    (
                        neighbor_val == minv
                        or neighbor_val == maxv
                    )
                )

                if (
                    current_boundary
                    or
                    neighbor_boundary
                ):
                    boundary = True
                    break

            instance[
                "has_boundary_point"
            ] = (
                "Yes"
                if boundary
                else "No"
            )

            # =====================================
            # comparator-based classification
            # =====================================

            cur_plan = _load_plan_json(
                RESULTS_DIR,
                row,
                plan_cache
            )

            neighbor_plan = _load_plan_json(
                RESULTS_DIR,
                neighbor_row,
                plan_cache
            ) if neighbor_row is not None else None

            if (
                cur_plan is not None
                and neighbor_plan is not None
            ):
                cmp = compare(
                    cur_plan,
                    neighbor_plan
                )

                # ---- per-category detail columns ----
                cat_details = _category_change_details(cmp)
                for cat in STRUCTURAL_CATEGORY_ORDER:
                    instance[f"{cat}_change"] = cat_details[cat]

                instance["change_type"] = _change_type_from_cmp(cmp)

            else:
                # plans unavailable → NaN for all detail cols
                for cat in STRUCTURAL_CATEGORY_ORDER:
                    instance[f"{cat}_change"] = np.nan

                instance["change_type"] = np.nan

            # =====================================
            # neighbor selectivities / metrics
            # =====================================

            if neighbor_row is not None:

                ndim = len(x_cols)

                # Current independent selectivities
                for a in range(ndim):
                    instance[
                        f"selectivity_x{a+1}"
                    ] = row.get(
                        f"selectivity_x{a+1}",
                        np.nan
                    )

                # Neighbor selectivities for THIS q-error axis
                for a in range(ndim):

                    instance[
                        f"neighbor_selectivity_x{a+1}"
                    ] = row.get(
                        f"neighbor_selectivity_x{a+1}_axis{axis}",
                        np.nan
                    )

                    instance[
                        f"dS_x{a+1}"
                    ] = row.get(
                        f"dS_x{a+1}_axis{axis}",
                        np.nan
                    )

                # Actual observed joint selectivities
                instance[
                    "joint_sel"
                ] = row.get(
                    "joint_sel",
                    np.nan
                )

                instance[
                    "neighbor_joint_sel"
                ] = row.get(
                    f"neighbor_joint_sel_axis{axis}",
                    np.nan
                )

                instance[
                    "joint_dS"
                ] = row.get(
                    f"joint_dS_axis{axis}",
                    np.nan
                )

                # Neighbor metrics
                instance[
                    "neighbor_runtime"
                ] = neighbor_row.get(
                    "runtime_mean",
                    np.nan
                )

                instance[
                    "neighbor_count_rows"
                ] = neighbor_row.get(
                    "count_rows",
                    np.nan
                )

                instance[
                    "neighbor_plan_hash"
                ] = neighbor_row.get(
                    "plan_hash",
                    ""
                )

            else:

                ndim = len(x_cols)

                for a in range(ndim):
                    instance[
                        f"neighbor_selectivity_x{a+1}"
                    ] = np.nan

                    instance[
                        f"dS_x{a+1}"
                    ] = np.nan

                instance[
                    "neighbor_joint_sel"
                ] = np.nan

                instance[
                    "joint_dS"
                ] = np.nan

                instance["neighbor_runtime"] = np.nan
                instance["neighbor_count_rows"] = np.nan
                instance["neighbor_plan_hash"] = ""

            # =====================================
            # useful info
            # =====================================

            useful_cols = [

                "runtime_mean",
                "count_rows",
                "execution_time",
                "planning_time",
                "rows_ret",
                "plan_rows",
                "plan_hash",

                *[
                    f"selectivity_x{i+1}"
                    for i in range(ndim)
                ],

                *[
                    f"neighbor_selectivity_x{i+1}"
                    for i in range(ndim)
                ],

                *[
                    f"dS_x{i+1}"
                    for i in range(ndim)
                ],

                "joint_sel",
                "neighbor_joint_sel",
                "joint_dS"
            ]

            for c in useful_cols:
                if c in row:
                    instance[c] = row[c]

            rows.append(
                instance
            )

            instance_id += 1

    # =========================================================
    # FINAL TABLE
    # =========================================================

    merged = pd.DataFrame(
        rows
    )

    # =====================================
    # Sort by descending qerror FIRST
    # =====================================

    merged = merged.sort_values(
        "qerr",
        ascending=False
    )

    merged = merged.reset_index(
        drop=True
    )

    merged.insert(
        0,
        "rank",
        np.arange(
            1,
            len(merged) + 1
        )
    )

    # =====================================
    # Column groups
    # =====================================

    coord_cols = [
        "rank",
        "instance_id",
        "axis",

        *x_cols,

        *[
            f"{c}_neighbor"
            for c in x_cols
        ]
    ]

    boundary_cols = [
        "has_boundary_point"
    ]

    metric_cols = [
        "qerr",
        "plan_change",

        "runtime_mean",
        "neighbor_runtime",

        "count_rows",
        "neighbor_count_rows",

        "execution_time",
        "planning_time",

        "rows_ret",
        "plan_rows"
    ]

    selectivity_cols = []
    for i in range(len(x_cols)):
        selectivity_cols.extend([
            f"selectivity_x{i+1}",
            f"neighbor_selectivity_x{i+1}",
            f"dS_x{i+1}"
        ])

    joint_cols = [
        "joint_sel",
        "neighbor_joint_sel",
        "joint_dS"
    ]

    plan_cols = [
        "plan_hash",
        "neighbor_plan_hash"
    ]

    # Per-category detail cols come first, then the compact summary
    change_cols = [
        *[f"{cat}_change" for cat in STRUCTURAL_CATEGORY_ORDER],
        "change_type",
    ]

    ordered = (
        coord_cols
        + boundary_cols
        + metric_cols
        + selectivity_cols
        + joint_cols
        + plan_cols
        + change_cols
    )

    existing = [
        c
        for c in ordered
        if c in merged.columns
    ]

    remaining = [
        c
        for c in merged.columns
        if c not in existing
    ]

    merged = merged[
        existing
        +
        remaining
    ]

    # Make format compatible
    pd.options.display.float_format = (
        lambda x:
        f"{x:.16e}"
    )

    # =========================================================
    # SAVE
    # =========================================================

    out_csv = (OUTPUT_DIR / "qerr_desc.csv")

    merged.to_csv(
        out_csv,
        index=False
    )

    print()
    print(
        f"Instances : {len(merged)}"
    )

    print(
        f"Saved : {out_csv}"
    )

    print()
    print(
        merged.head(20)
    )

    print()
    print("DONE")

    # ==============================================================================================

    # ==========================================
    # Load file
    # ==========================================

    df = pd.read_csv(
        OUTPUT_DIR / "qerr_desc.csv"
    )

    # ==========================================
    # Clean values
    # ==========================================

    qerr = (
        df["qerr"]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )

    sel_diff = (
        df["joint_dS"]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )

    # ==========================================
    # Build empirical CDF
    # ==========================================

    def make_cdf(x):

        x = np.sort(x)

        y = np.arange(
            1,
            len(x) + 1
        ) / len(x)

        return x, y

    qx, qy = make_cdf(qerr)
    sx, sy = make_cdf(sel_diff)

    # ==========================================
    # Plot
    # ==========================================

    plt.figure(figsize=(10, 6))

    plt.plot(
        qx,
        qy,
        label="Q-error CDF"
    )

    plt.plot(
        sx,
        sy,
        label="Joint dS CDF"
    )

    plt.xlabel("Value")
    plt.ylabel("CDF")

    plt.title(
        "CDF: Q-error vs Selectivity Difference"
    )

    plt.grid(True)

    plt.legend()

    plt.tight_layout()

    out_path = (
        OUTPUT_DIR /
        "qerror_vs_planchange_cdf_GLOBAL.png"
    )

    plt.savefig(
        out_path,
        dpi=300
    )

    print(
        f"Saved global plot: {out_path}"
    )


if __name__ == "__main__":

    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "gt_results_sf1_10x10_s1q0/qt8/m0"
    run(path)