# =========================================================
# scripts/merge_all_qerr_instances.py
# =========================================================

from pathlib import Path
import numpy as np
import pandas as pd

from config_gt import RESULTS_DIR
from config_gt import RESULTS_FILENAME

CSV_PATH = Path(RESULTS_DIR) / RESULTS_FILENAME

OUTPUT_DIR = (
    RESULTS_DIR /
    "merged_qerr_instances"
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

        # =====================================
        # current point coordinates
        # =====================================

        for c in x_cols:

            instance[c]=row[c]

        # =====================================
        # current selectivity
        # =====================================

        instance[
            "selectivity"
        ]=row.get(
            "selectivity",
            np.nan
        )

        instance[
            "selectivity_percent"
        ]=row.get(
            "selectivity_percent",
            np.nan
        )

        # =====================================
        # exact neighbor coordinates
        # =====================================

        neighbor_coords=[]

        for c in x_cols:

            ncol=(
                f"{c}_neighbor_axis{axis}"
            )

            val=row.get(
                ncol,
                np.nan
            )

            instance[
                f"{c}_neighbor"
            ]=val

            neighbor_coords.append(
                val
            )

        # =====================================
        # lookup exact neighboring point
        # =====================================

        neighbor_key=tuple(
            neighbor_coords
        )

        neighbor_row=lookup.get(
            neighbor_key,
            None
        )

        if neighbor_row is not None:

            instance[
                "neighbor_selectivity"
            ]=neighbor_row.get(
                "selectivity",
                np.nan
            )

            instance[
                "neighbor_selectivity_percent"
            ]=neighbor_row.get(
                "selectivity_percent",
                np.nan
            )

            # =====================================
            # high precision selectivity difference
            # =====================================

            sel1 = np.float64(
                row.get(
                    "selectivity",
                    np.nan
                )
            )

            sel2 = np.float64(
                neighbor_row.get(
                    "selectivity",
                    np.nan
                )
            )

            instance[
                "selectivity_difference"
            ] = np.abs(
                sel1 - sel2
            )

            # relative change also useful
            instance[
                "selectivity_ratio"
            ] = (
                max(sel1,sel2)
                /
                max(
                    min(sel1,sel2),
                    1e-30
                )
            )

            instance[
                "neighbor_runtime"
            ]=neighbor_row.get(
                "runtime_mean",
                np.nan
            )

            instance[
                "neighbor_count_rows"
            ]=neighbor_row.get(
                "count_rows",
                np.nan
            )

            instance[
                "neighbor_plan_hash"
            ]=neighbor_row.get(
                "plan_hash",
                ""
            )

        else:

            instance[
                "neighbor_selectivity"
            ]=np.nan

            instance[
                "neighbor_selectivity_percent"
            ]=np.nan

            instance[
                "selectivity_difference"
            ]=np.nan

        # =====================================
        # useful info
        # =====================================

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

        rows.append(
            instance
        )

        instance_id+=1


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

# Make format compatible
pd.options.display.float_format = (
    lambda x:
    f"{x:.16e}"
)


# =========================================================
# SAVE
# =========================================================

out_csv=(OUTPUT_DIR / "all_qerr_instances_desc.csv")

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

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ==========================================
# Load file
# ==========================================

df = pd.read_csv(
    OUTPUT_DIR / "all_qerr_instances_desc.csv"
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
    df["selectivity_difference"]
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
        len(x)+1
    ) / len(x)

    return x, y


qx, qy = make_cdf(qerr)
sx, sy = make_cdf(sel_diff)

# ==========================================
# Plot
# ==========================================

plt.figure(figsize=(10,6))

plt.plot(
    qx,
    qy,
    label="Q-error CDF"
)

plt.plot(
    sx,
    sy,
    label="Selectivity Difference CDF"
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
    OUTPUT_DIR
    /
    "qerror_vs_planchange_cdf_GLOBAL.png"
)

plt.savefig(
    out_path,
    dpi=300
)

print(
    f"Saved global plot: {out_path}"
)