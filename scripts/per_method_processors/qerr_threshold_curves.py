# =========================================================
# per_method_processors/qerr_threshold_curves.py
# =========================================================

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config_gt


# =========================================================
# Processor entry
# =========================================================

def run(results_dir):

    results_dir=Path(results_dir)

    csv_path=(
        results_dir
        / config_gt.RESULTS_FILENAME
    )

    output_dir=(
        results_dir
        / "qerr_threshold_plots"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    print()
    print("="*60)
    print("QERR THRESHOLD CURVES")
    print("="*60)

    # =====================================================
    # LOAD
    # =====================================================

    if not csv_path.exists():

        print(
            f"Missing:\n{csv_path}"
        )

        return

    df=pd.read_csv(
        csv_path
    )

    # =====================================================
    # MERGE AXES DYNAMICALLY
    # =====================================================

    rows=[]

    qcols=sorted([

        c for c in df.columns
        if c.startswith(
            "adjacent_qerr_x"
        )

    ])

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

        sub=df.loc[
            np.isfinite(
                df[qcol]
            )
        ].copy()

        for _,row in sub.iterrows():

            verdict = str(row[pcol]).upper()

            rows.append({

                "axis":
                axis,

                "qerr":
                row[qcol],

                "plan_change":
                verdict == "STRUCTURAL"
            })

    merged=pd.DataFrame(
        rows
    )

    if merged.empty:

        print(
            "No valid rows."
        )

        return

    # =====================================================
    # CLEAN
    # =====================================================

    merged=merged[
        np.isfinite(
            merged["qerr"]
        )
    ]

    merged=merged[
        merged["qerr"]>0
    ]

    merged=merged.sort_values(
        "qerr"
    )

    merged=merged.reset_index(
        drop=True
    )

    # =====================================================
    # THRESHOLDS
    # =====================================================

    thresholds=np.sort(
        merged[
            "qerr"
        ].unique()
    )

    # =====================================================
    # CURVES
    # =====================================================

    curve1=[]
    curve2=[]
    curve3=[]
    curve4=[]

    for x in thresholds:

        curve1.append(

            (
                (
                    merged[
                        "plan_change"
                    ]==True
                )
                &
                (
                    merged[
                        "qerr"
                    ]<x
                )
            ).sum()
        )

        curve2.append(

            (
                (
                    merged[
                        "plan_change"
                    ]==False
                )
                &
                (
                    merged[
                        "qerr"
                    ]>x
                )
            ).sum()
        )

        curve3.append(

            (
                (
                    merged[
                        "plan_change"
                    ]==True
                )
                &
                (
                    merged[
                        "qerr"
                    ]>x
                )
            ).sum()
        )

        curve4.append(

            (
                (
                    merged[
                        "plan_change"
                    ]==False
                )
                &
                (
                    merged[
                        "qerr"
                    ]<x
                )
            ).sum()
        )

    # =====================================================
    # SAVE CSV
    # =====================================================

    curve_df=pd.DataFrame({

        "threshold_qerr":
        thresholds,

        "planchange_lt_x":
        curve1,

        "nochange_gt_x":
        curve2,

        "planchange_gt_x":
        curve3,

        "nochange_lt_x":
        curve4
    })

    curve_csv=(
        output_dir
        /
        "threshold_curves.csv"
    )

    curve_df.to_csv(

        curve_csv,
        index=False
    )

    print(
        f"Saved:\n{curve_csv}"
    )

    # =====================================================
    # PLOT
    # =====================================================

    plt.figure(
        figsize=(12,7)
    )

    plt.plot(

        thresholds,
        curve1,
        linewidth=2,
        label=
        "Plan change & qerr < x"
    )

    plt.plot(

        thresholds,
        curve2,
        linewidth=2,
        label=
        "No change & qerr > x"
    )

    plt.plot(

        thresholds,
        curve3,
        linewidth=2,
        label=
        "Plan change & qerr > x"
    )

    plt.plot(

        thresholds,
        curve4,
        linewidth=2,
        label=
        "No change & qerr < x"
    )

    plt.xscale(
        "log"
    )

    plt.xlabel(
        "Q-error threshold"
    )

    plt.ylabel(
        "Count"
    )

    plt.title(

        f"{config_gt.QUERY}"
        f" | "
        f"{config_gt.CURRENT_METHOD}"
        "\nQ-error threshold curves"
    )

    plt.grid(True)

    plt.legend()

    plt.tight_layout()

    plot_path=(
        output_dir
        /
        "threshold_curves.png"
    )

    plt.savefig(

        plot_path,
        dpi=300
    )

    plt.close()

    print(
        f"Saved:\n{plot_path}"
    )

    print()
    print("DONE")


if __name__ == "__main__":

    path = sys.argv[1] if len(sys.argv) > 1 else "gt_results_sf1_10x10_s1q0/qt8/m0"
    run(path)