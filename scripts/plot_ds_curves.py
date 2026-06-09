# plot_ds_curves.py

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


# =====================================
# INPUT
# =====================================

CSV = (
    "gt_results_sf1_qt8_10x10_m0/"
    "merged_qerr_instances_nb/"
    "all_qerr_instances_desc_nb.csv"
)

df=pd.read_csv(CSV)


# =====================================
# Sort by qerror
# =====================================

df=df.sort_values(
    "qerr",
    ascending=False
).reset_index(drop=True)


# =====================================
# Find dS columns automatically
# =====================================

ds_cols=sorted([

    c
    for c in df.columns

    if (
        c.startswith("dS_x")
        and
        "_axis" not in c
    )
])


print()
print("Found dS columns:")
print(ds_cols)

print()


# =====================================
# Plot
# =====================================

plt.figure(
    figsize=(14,8)
)


# -------------------------------------
# Plot dS_x*
# -------------------------------------

for c in ds_cols:

    vals=(
        df[c]
        .replace(
            [np.inf,-np.inf],
            np.nan
        )
    )

    plt.plot(
        vals,
        linewidth=2,
        label=c
    )


# -------------------------------------
# Joint dS
# -------------------------------------

joint=(
    df["joint_dS"]
    .replace(
        [np.inf,-np.inf],
        np.nan
    )
)

plt.plot(
    joint,
    linewidth=2,
    label="joint_dS"
)


# =====================================
# Labels
# =====================================

plt.xlabel(
    "Neighbor instance rank"
)

plt.ylabel(
    "Selectivity difference"
)

plt.title(
    "Independent dS vs Joint dS"
)

plt.grid()

plt.legend()

plt.tight_layout()


# =====================================
# Save
# =====================================

out="ds_curves_m0.png"

plt.savefig(
    out,
    dpi=300
)

print(
    f"Saved: {out}"
)