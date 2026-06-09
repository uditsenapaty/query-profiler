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
# Build empirical CDF
# =====================================

def make_cdf(x):

    x=(
        pd.Series(x)
        .replace(
            [np.inf,-np.inf],
            np.nan
        )
        .dropna()
        .values
    )

    x=np.sort(x)

    y=np.arange(
        1,
        len(x)+1
    )/len(x)

    return x,y


# =====================================
# Plot CDF
# =====================================

plt.figure(
    figsize=(12,7)
)


# -------------------------------------
# dS_x*
# -------------------------------------

for c in ds_cols:

    x,y=make_cdf(
        df[c]
    )

    plt.plot(
        x,
        y,
        linewidth=2,
        label=c
    )


# -------------------------------------
# joint_dS
# -------------------------------------

x,y=make_cdf(
    df["joint_dS"]
)

plt.plot(
    x,
    y,
    linewidth=4,
    label="joint_dS"
)


# =====================================
# Labels
# =====================================

plt.xlabel(
    "Selectivity Difference"
)

plt.ylabel(
    "CDF"
)

plt.title(
    "CDF of dS_x* and joint_dS"
)

plt.grid()

plt.legend()

plt.tight_layout()


# =====================================
# Save
# =====================================

out="ds_curves_cdf_m0.png"

plt.savefig(
    out,
    dpi=300
)

print(
    f"Saved: {out}"
)