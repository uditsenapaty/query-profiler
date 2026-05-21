# =========================================================
# scripts/plot_compare_selectivity2.py
# =========================================================

from pathlib import Path
import argparse

import pandas as pd
import numpy as np

import matplotlib.pyplot as plt

from scipy.stats import ks_2samp

# =========================================================
# ARGS
# =========================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--gt1",
    required=True
)

parser.add_argument(
    "--gt2",
    required=True
)

parser.add_argument(
    "--name1",
    default="method1"
)

parser.add_argument(
    "--name2",
    default="method2"
)

args=parser.parse_args()

GT1=Path(args.gt1)
GT2=Path(args.gt2)

NAME1=args.name1
NAME2=args.name2

OUTDIR=Path(
    "selectivity2_comparison"
)

OUTDIR.mkdir(
    exist_ok=True
)

# =========================================================
# LOAD
# =========================================================

df1=pd.read_csv(
    GT1/"ground_truth.csv"
)

df2=pd.read_csv(
    GT2/"ground_truth.csv"
)

if "selectivity2" not in df1.columns:
    raise RuntimeError(
        "selectivity2 missing in GT1"
    )

if "selectivity2" not in df2.columns:
    raise RuntimeError(
        "selectivity2 missing in GT2"
    )

sel1=df1[
    "selectivity2"
].values

sel2=df2[
    "selectivity2"
].values

sel1=sel1[
    np.isfinite(sel1)
]

sel2=sel2[
    np.isfinite(sel2)
]

sel1=sel1[
    sel1>0
]

sel2=sel2[
    sel2>0
]

print()
print("================================================")
print("SELECTIVITY2 COMPARISON")
print("================================================")

print(
    f"{NAME1}: {len(sel1)} points"
)

print(
    f"{NAME2}: {len(sel2)} points"
)

# =========================================================
# SUMMARY
# =========================================================

summary=[]

for name,data in [

    (NAME1,sel1),
    (NAME2,sel2)
]:

    summary.append({

        "method":name,

        "mean":
            np.mean(data),

        "median":
            np.median(data),

        "std":
            np.std(data),

        "min":
            np.min(data),

        "max":
            np.max(data),

        "p90":
            np.percentile(
                data,
                90
            ),

        "p95":
            np.percentile(
                data,
                95
            )
    })

summary=pd.DataFrame(
    summary
)

summary.to_csv(

    OUTDIR/
    "summary.csv",

    index=False
)

print()
print(summary)

# =========================================================
# KS TEST
# =========================================================

ks=ks_2samp(
    sel1,
    sel2
)

with open(
    OUTDIR/"ks_test.txt",
    "w"
) as f:

    f.write(
        f"KS statistic: {ks.statistic}\n"
    )

    f.write(
        f"P-value: {ks.pvalue}\n"
    )

print()
print(
    f"KS={ks.statistic:.5f}"
)

print(
    f"P={ks.pvalue:.5e}"
)

# =========================================================
# CDF
# =========================================================

s1=np.sort(sel1)
s2=np.sort(sel2)

cdf1=np.arange(
    1,
    len(s1)+1
)/len(s1)

cdf2=np.arange(
    1,
    len(s2)+1
)/len(s2)

plt.figure(
    figsize=(9,6)
)

plt.plot(
    s1,
    cdf1,
    linewidth=2,
    label=NAME1
)

plt.plot(
    s2,
    cdf2,
    linewidth=2,
    label=NAME2
)

plt.xscale(
    "log"
)

plt.xlabel(
    "Selectivity2"
)

plt.ylabel(
    "CDF"
)

plt.title(
    "Selectivity2 Distribution"
)

plt.grid()

plt.legend()

plt.tight_layout()

plt.savefig(
    OUTDIR/
    "cdf_selectivity2.png",
    dpi=300
)

plt.close()

# =========================================================
# HISTOGRAM
# =========================================================

plt.figure(
    figsize=(9,6)
)

plt.hist(
    sel1,
    bins=50,
    alpha=.5,
    density=True,
    label=NAME1
)

plt.hist(
    sel2,
    bins=50,
    alpha=.5,
    density=True,
    label=NAME2
)

plt.xscale(
    "log"
)

plt.xlabel(
    "Selectivity2"
)

plt.ylabel(
    "Density"
)

plt.title(
    "Selectivity2 Histogram"
)

plt.legend()

plt.tight_layout()

plt.savefig(
    OUTDIR/
    "hist_selectivity2.png",
    dpi=300
)

plt.close()

# =========================================================
# BOXPLOT
# =========================================================

plt.figure(
    figsize=(8,5)
)

plt.boxplot(

    [sel1,sel2],

    labels=[
        NAME1,
        NAME2
    ]
)

plt.yscale(
    "log"
)

plt.ylabel(
    "Selectivity2"
)

plt.title(
    "Selectivity2 Boxplot"
)

plt.tight_layout()

plt.savefig(
    OUTDIR/
    "boxplot_selectivity2.png",
    dpi=300
)

plt.close()

print()
print(
    f"Saved results: {OUTDIR}"
)

print()
print("DONE")