# =========================================================
# scripts/merge_all_qerr_instances.py
# =========================================================

from pathlib import Path

import numpy as np
import pandas as pd

from config_gt import RESULTS_DIR
from config_gt import RESULTS_FILENAME

CSV_PATH = Path(RESULTS_DIR) / RESULTS_FILENAME

OUTPUT_DIR = Path(
    RESULTS_DIR / "merged_qerr_instances"
)

OUTPUT_DIR.mkdir(
    exist_ok=True
)

print()
print("================================================")
print("MERGING ALL QERR INSTANCES")
print("================================================")

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

    c for c in df.columns

    if c.startswith("x")
])

# =========================================================
# FIND AXES
# =========================================================

qcols = sorted([

    c for c in df.columns

    if c.startswith(
        "adjacent_qerr_x"
    )
])

rows=[]

instance_id=0

# =========================================================
# BUILD INSTANCES
# =========================================================

for qcol in qcols:

    axis=int(
        qcol.split(
            "_x"
        )[-1]
    )

    pcol=(
        f"plan_change_x{axis}"
    )

    if pcol not in df.columns:
        continue

    valid=df.loc[
        np.isfinite(
            df[qcol]
        )
    ]

    for _,row in valid.iterrows():

        instance={}

        instance[
            "instance_id"
        ]=instance_id

        instance[
            "axis"
        ]=axis

        instance[
            "qerr"
        ]=row[qcol]

        instance[
            "plan_change"
        ]=row[pcol]

        # ---------------------------------
        # Selectivities
        # ---------------------------------

        for c in [
            "selectivity1",
            "selectivity1_percent",

            "selectivity2",
            "selectivity2_percent"
        ]:

            if c in row:
                instance[c] = row[c]

        # ---------------------------------
        # useful runtime/cardinality info
        # ---------------------------------

        useful_cols=[

            "runtime_mean",

            "count_rows",

            "execution_time",

            "planning_time",

            "root_rows",

            "plan_rows",

            "plan_hash"
        ]

        for c in useful_cols:

            if c in row:

                instance[c]=row[c]

        # ---------------------------------
        # parameter coordinates
        # ---------------------------------

        for c in x_cols:

            instance[c]=row[c]

        rows.append(
            instance
        )

        instance_id += 1

# =========================================================
# FINAL TABLE
# =========================================================

merged=pd.DataFrame(
    rows
)

merged=merged.sort_values(

    "qerr",

    ascending=False
)

merged=merged.reset_index(
    drop=True
)

merged.insert(

    0,

    "rank",

    np.arange(
        1,
        len(merged)+1
    )
)

# =========================================================
# SAVE
# =========================================================

out_csv=(

    OUTPUT_DIR
    /
    "all_qerr_instances_desc.csv"
)

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