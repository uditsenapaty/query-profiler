#plot_cdf_qerr.py

# =========================================================
from pathlib import Path

from config_gt import RESULTS_DIR
from config_gt import RESULTS_FILENAME
CSV_PATH = Path(RESULTS_DIR) / Path(RESULTS_FILENAME)
# =========================================================

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

df = pd.read_csv(CSV_PATH)

qerr_cols = sorted([
    c for c in df.columns
    if c.startswith("adjacent_qerr_x")
])

for qcol in qerr_cols:

    axis = qcol.split("_x")[-1]

    pcol = f"plan_change_x{axis}"

    q_all = df[qcol].values
    q_all = q_all[np.isfinite(q_all)]
    q_all = q_all[q_all > 0]

    q_all = np.sort(q_all)

    cdf_all = (
        np.arange(1, len(q_all)+1)
        / len(q_all)
    )

    q_switch = df.loc[
        df[pcol] == True,
        qcol
    ].values

    q_switch = q_switch[
        np.isfinite(q_switch)
    ]

    q_switch = q_switch[
        q_switch > 0
    ]

    q_switch = np.sort(q_switch)

    cdf_switch = (
        np.arange(1, len(q_switch)+1)
        / len(q_switch)
    )

    plt.figure(figsize=(8,5))

    plt.plot(
        q_all,
        cdf_all,
        label=f"All qerrors ({qcol})"
    )

    plt.plot(
        q_switch,
        cdf_switch,
        linestyle="--",
        label=f"Switch qerrors ({qcol})"
    )

    plt.xscale("log")

    plt.xlabel("Adjacent Q-error")
    plt.ylabel("Empirical CDF")

    plt.title(
        f"Axis {axis} Q-error CDF"
    )

    plt.grid(True)
    plt.legend()

    plt.tight_layout()

    plt.savefig(
        RESULTS_DIR / f"qerror_vs_planchange_cdf_axis_{axis}.png",
        dpi=300
    )

    print(
        f"Saved axis {axis}"
    )

# =========================================================
# GLOBAL MERGED CDF
# =========================================================

print()
print("================================================")
print("GLOBAL MERGED QERROR CDF")
print("================================================")

all_qerrs = []

all_switch_qerrs = []

for qcol in qerr_cols:

    axis = qcol.split("_x")[-1]

    pcol = f"plan_change_x{axis}"

    # -----------------------------------------------------
    # all qerrs
    # -----------------------------------------------------

    q_all = df[qcol].values

    q_all = q_all[
        np.isfinite(q_all)
    ]

    q_all = q_all[
        q_all > 0
    ]

    all_qerrs.extend(
        q_all.tolist()
    )

    # -----------------------------------------------------
    # switch qerrs
    # -----------------------------------------------------

    if pcol in df.columns:

        q_switch = df.loc[
            df[pcol] == True,
            qcol
        ].values

        q_switch = q_switch[
            np.isfinite(q_switch)
        ]

        q_switch = q_switch[
            q_switch > 0
        ]

        all_switch_qerrs.extend(
            q_switch.tolist()
        )

# =========================================================
# SORT
# =========================================================

all_qerrs = np.array(
    sorted(all_qerrs)
)

all_switch_qerrs = np.array(
    sorted(all_switch_qerrs)
)

# =========================================================
# CDF
# =========================================================

cdf_all = (
    np.arange(
        1,
        len(all_qerrs)+1
    )
    /
    len(all_qerrs)
)

cdf_switch = (
    np.arange(
        1,
        len(all_switch_qerrs)+1
    )
    /
    len(all_switch_qerrs)
)

# =========================================================
# PLOT
# =========================================================

plt.figure(figsize=(9,6))

plt.plot(
    all_qerrs,
    cdf_all,
    linewidth=2,
    label="All Adjacent Q-errors"
)

plt.plot(
    all_switch_qerrs,
    cdf_switch,
    linestyle="--",
    linewidth=2,
    label="Plan-change Q-errors"
)

plt.xscale("log")

plt.xlabel(
    "Adjacent Q-error"
)

plt.ylabel(
    "Empirical CDF"
)

plt.title(
    "Global Adjacent Q-error Distribution"
)

plt.grid(True)

plt.legend()

plt.tight_layout()

out_path = (
    RESULTS_DIR
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