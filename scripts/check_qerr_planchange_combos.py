# =========================================================
# scripts/check_qerr_planchange_combos.py
# =========================================================

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from config_gt import RESULTS_DIR
from config_gt import RESULTS_FILENAME

CSV_PATH = Path(RESULTS_DIR) / RESULTS_FILENAME

OUTPUT_DIR = Path(
    "qerr_planchange_analysis"
)

OUTPUT_DIR.mkdir(exist_ok=True)

print()
print("================================================")
print("GLOBAL QERR / PLANCHANGE ANALYSIS")
print("================================================")

df = pd.read_csv(CSV_PATH)

# =========================================================
# MERGE ALL AXES
# =========================================================

rows = []

qcols = sorted([
    c for c in df.columns
    if c.startswith("adjacent_qerr_x")
])

for qcol in qcols:

    axis = int(
        qcol.split("_x")[-1]
    )

    pcol = f"plan_change_x{axis}"

    if pcol not in df.columns:
        continue

    sub = df.loc[
        np.isfinite(df[qcol])
    ].copy()

    for _, row in sub.iterrows():

        r = row.to_dict()

        r["axis"] = axis

        r["merged_qerr"] = row[qcol]

        r["merged_plan_change"] = row[pcol]

        rows.append(r)

merged = pd.DataFrame(rows)

# =========================================================
# SORT
# =========================================================

merged = merged.sort_values(
    "merged_qerr"
)

merged = merged.reset_index(
    drop=True
)

# =========================================================
# THRESHOLDS
# =========================================================

true_rows = merged[
    merged["merged_plan_change"] == True
]

false_rows = merged[
    merged["merged_plan_change"] == False
]

first_true = true_rows.iloc[0]

last_false = false_rows.iloc[-1]

ft_x = float(
    first_true["merged_qerr"]
)

lf_x = float(
    last_false["merged_qerr"]
)

# =========================================================
# HELPERS
# =========================================================

def safe_copy(src, dst):

    try:

        src = str(src)

        # -------------------------------------------------
        # absolute
        # -------------------------------------------------

        p = Path(src)

        # -------------------------------------------------
        # relative to RESULTS_DIR
        # -------------------------------------------------

        if not p.exists():

            p = RESULTS_DIR / src

        # -------------------------------------------------
        # still missing
        # -------------------------------------------------

        if not p.exists():

            print(
                f"[WARN] missing file: {src}"
            )

            return

        dst.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        shutil.copy(p, dst)

    except Exception as e:

        print(
            f"[WARN] copy failed: {src}"
        )

        print(e)


def export_everything(
    df_case,
    out_dir
):

    out_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    # -----------------------------------------------------
    # CSV
    # -----------------------------------------------------

    df_case.to_csv(
        out_dir / "examples.csv",
        index=False
    )

    # -----------------------------------------------------
    # dirs
    # -----------------------------------------------------

    trace_dir = out_dir / "traces"

    plan_dir = out_dir / "plans"

    tree_dir = out_dir / "plan_trees"

    trace_dir.mkdir(exist_ok=True)

    plan_dir.mkdir(exist_ok=True)

    tree_dir.mkdir(exist_ok=True)

    # -----------------------------------------------------
    # copy
    # -----------------------------------------------------

    for _, row in df_case.iterrows():

        # TRACE

        if "trace_path" in row:

            val = row["trace_path"]

            if pd.notna(val):

                safe_copy(
                    val,
                    trace_dir /
                    Path(str(val)).name
                )

        # PLAN TREE

        if "plan_tree_path" in row:

            val = row["plan_tree_path"]

            if pd.notna(val):

                safe_copy(
                    val,
                    tree_dir /
                    Path(str(val)).name
                )

        # PLAN JSON

        if "plan_json_path" in row:

            val = row["plan_json_path"]

            if pd.notna(val):

                safe_copy(
                    val,
                    plan_dir /
                    Path(str(val)).name
                )

# =========================================================
# USING FIRST TRUE
# =========================================================

ft_dir = OUTPUT_DIR / "using_first_true"

ft_case1 = merged[
    (merged["merged_plan_change"] == True)
    &
    (merged["merged_qerr"] < ft_x)
]

ft_case2 = merged[
    (merged["merged_plan_change"] == False)
    &
    (merged["merged_qerr"] > ft_x)
]

ft_case3 = merged[
    (merged["merged_plan_change"] == True)
    &
    (merged["merged_qerr"] > ft_x)
]

ft_case4 = merged[
    (merged["merged_plan_change"] == False)
    &
    (merged["merged_qerr"] < ft_x)
]

export_everything(
    ft_case1,
    ft_dir / "planchange_lt"
)

export_everything(
    ft_case2,
    ft_dir / "nochange_gt"
)

export_everything(
    ft_case3,
    ft_dir / "planchange_gt"
)

export_everything(
    ft_case4,
    ft_dir / "nochange_lt"
)

# =========================================================
# USING LAST FALSE
# =========================================================

lf_dir = OUTPUT_DIR / "using_last_false"

lf_case1 = merged[
    (merged["merged_plan_change"] == True)
    &
    (merged["merged_qerr"] < lf_x)
]

lf_case2 = merged[
    (merged["merged_plan_change"] == False)
    &
    (merged["merged_qerr"] > lf_x)
]

lf_case3 = merged[
    (merged["merged_plan_change"] == True)
    &
    (merged["merged_qerr"] > lf_x)
]

lf_case4 = merged[
    (merged["merged_plan_change"] == False)
    &
    (merged["merged_qerr"] < lf_x)
]

export_everything(
    lf_case1,
    lf_dir / "planchange_lt"
)

export_everything(
    lf_case2,
    lf_dir / "nochange_gt"
)

export_everything(
    lf_case3,
    lf_dir / "planchange_gt"
)

export_everything(
    lf_case4,
    lf_dir / "nochange_lt"
)

# =========================================================
# SUMMARY
# =========================================================

summary = {

    "first_true_qerr":
        ft_x,

    "last_false_qerr":
        lf_x,

    "overlap_gap":
        ft_x - lf_x,

    "using_first_true": {

        "planchange_lt":
            len(ft_case1),

        "nochange_gt":
            len(ft_case2),

        "planchange_gt":
            len(ft_case3),

        "nochange_lt":
            len(ft_case4),
    },

    "using_last_false": {

        "planchange_lt":
            len(lf_case1),

        "nochange_gt":
            len(lf_case2),

        "planchange_gt":
            len(lf_case3),

        "nochange_lt":
            len(lf_case4),
    }
}

with open(
    OUTPUT_DIR / "summary.json",
    "w"
) as f:

    json.dump(
        summary,
        f,
        indent=2
    )

print()
print(json.dumps(
    summary,
    indent=2
))

print()
print("DONE")