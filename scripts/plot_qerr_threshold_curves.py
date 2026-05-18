# =========================================================
# scripts/plot_qerr_threshold_curves.py
# =========================================================

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from config_gt import RESULTS_DIR
from config_gt import RESULTS_FILENAME

CSV_PATH = Path(RESULTS_DIR) / RESULTS_FILENAME

OUTPUT_DIR = Path(
    "qerr_threshold_plots"
)

OUTPUT_DIR.mkdir(exist_ok=True)

print()
print("================================================")
print("QERR THRESHOLD CURVES")
print("================================================")

# =========================================================
# LOAD
# =========================================================

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

        rows.append({

            "axis": axis,

            "qerr": row[qcol],

            "plan_change": bool(
                row[pcol]
            )
        })

merged = pd.DataFrame(rows)

# =========================================================
# CLEAN
# =========================================================

merged = merged[
    np.isfinite(merged["qerr"])
]

merged = merged[
    merged["qerr"] > 0
]

merged = merged.sort_values(
    "qerr"
)

merged = merged.reset_index(
    drop=True
)

# =========================================================
# THRESHOLDS
# =========================================================

thresholds = np.sort(
    merged["qerr"].unique()
)

# =========================================================
# CURVES
# =========================================================

curve1 = []
curve2 = []
curve3 = []
curve4 = []

# ---------------------------------------------------------
# 1. plan change AND qerr < x
#
# TRUE POSITIVE BELOW
# ---------------------------------------------------------

# ---------------------------------------------------------
# 2. no plan change AND qerr > x
#
# FALSE POSITIVE ABOVE
# ---------------------------------------------------------

# ---------------------------------------------------------
# 3. plan change AND qerr > x
#
# TRUE POSITIVE ABOVE
# ---------------------------------------------------------

# ---------------------------------------------------------
# 4. no plan change AND qerr < x
#
# TRUE NEGATIVE BELOW
# ---------------------------------------------------------

for x in thresholds:

    case1 = merged[
        (merged["plan_change"] == True)
        &
        (merged["qerr"] < x)
    ]

    case2 = merged[
        (merged["plan_change"] == False)
        &
        (merged["qerr"] > x)
    ]

    case3 = merged[
        (merged["plan_change"] == True)
        &
        (merged["qerr"] > x)
    ]

    case4 = merged[
        (merged["plan_change"] == False)
        &
        (merged["qerr"] < x)
    ]

    curve1.append(len(case1))
    curve2.append(len(case2))
    curve3.append(len(case3))
    curve4.append(len(case4))

# =========================================================
# SAVE CSV
# =========================================================

curve_df = pd.DataFrame({

    "threshold_qerr": thresholds,

    "planchange_lt_x": curve1,

    "nochange_gt_x": curve2,

    "planchange_gt_x": curve3,

    "nochange_lt_x": curve4,
})

curve_csv = (
    OUTPUT_DIR
    /
    "threshold_curves.csv"
)

curve_df.to_csv(
    curve_csv,
    index=False
)

print(
    f"Saved: {curve_csv}"
)

# =========================================================
# PLOT
# =========================================================

plt.figure(figsize=(10,6))

plt.plot(
    thresholds,
    curve1,
    linewidth=2,
    label="Plan change & qerr < x"
)

plt.plot(
    thresholds,
    curve2,
    linewidth=2,
    label="No change & qerr > x"
)

plt.plot(
    thresholds,
    curve3,
    linewidth=2,
    label="Plan change & qerr > x"
)

plt.plot(
    thresholds,
    curve4,
    linewidth=2,
    label="No change & qerr < x"
)

plt.xscale("log")

plt.xlabel(
    "Q-error threshold (x)"
)

plt.ylabel(
    "Count"
)

plt.title(
    "Q-error Threshold Classification Curves"
)

plt.grid(True)

plt.legend()

plt.tight_layout()

plot_path = (
    OUTPUT_DIR
    /
    "threshold_curves.png"
)

plt.savefig(
    plot_path,
    dpi=300
)

print(
    f"Saved: {plot_path}"
)

print()
print("DONE")