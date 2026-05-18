# =========================================================
# scripts/find_planchange_boundaries.py
# =========================================================

import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from config_gt import RESULTS_DIR
from config_gt import RESULTS_FILENAME

CSV_PATH = Path(RESULTS_DIR) / RESULTS_FILENAME

OUTPUT_DIR = Path(
    "planchange_boundary_analysis"
)

OUTPUT_DIR.mkdir(exist_ok=True)

print()
print("================================================")
print("BOUNDARY ANALYSIS")
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
# FIND BOUNDARIES
# =========================================================

true_rows = merged[
    merged["merged_plan_change"] == True
]

false_rows = merged[
    merged["merged_plan_change"] == False
]

if len(true_rows) == 0:
    raise RuntimeError(
        "No plan-change rows found"
    )

if len(false_rows) == 0:
    raise RuntimeError(
        "No stable rows found"
    )

first_true = true_rows.iloc[0]

last_false = false_rows.iloc[-1]

# =========================================================
# SAVE CSV
# =========================================================

boundary_df = pd.DataFrame([
    first_true,
    last_false
])

boundary_df.to_csv(
    OUTPUT_DIR / "boundary_examples.csv",
    index=False
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
# EXPORT
# =========================================================

export_everything(
    pd.DataFrame([first_true]),
    OUTPUT_DIR / "first_true"
)

export_everything(
    pd.DataFrame([last_false]),
    OUTPUT_DIR / "last_false"
)

print()
print("DONE")