# =========================================================
# scripts/per_method_processors/qerr_desc_nb.py
# =========================================================

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from config_gt import MAIN_DIR

def run(results_dir):

    RESULTS_DIR=Path(results_dir)

    CSV_PATH=(
        RESULTS_DIR/
        "ground_truth.csv"
    )

    OUTPUT_DIR=(
        RESULTS_DIR/
        "qerr_sorted"
    )

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    print()
    print("="*48)
    print("MERGING ALL QERR INSTANCES")
    print("="*48)

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

        valid=df.loc[
            np.isfinite(
                df[qcol]
            )
        ]

        # ======================================
        # remove ALL boundary points for current point
        # ======================================

        for c in x_cols:

            vals=np.sort(df[c].unique())

            if len(vals) <= 2:
                continue

            minv=vals[0]
            maxv=vals[-1]

            valid=valid.loc[
                (valid[c] != minv)
                &
                (valid[c] != maxv)
            ]


        # ======================================
        # remove ALL boundary neighbors
        # ======================================

        for c in x_cols:

            vals=np.sort(
                df[c].unique()
            )

            if len(vals) <= 2:
                continue

            minv=vals[0]
            maxv=vals[-1]

            ncol=f"{c}_neighbor_axis{axis}"

            valid=valid.loc[
                valid[ncol].notna()
            ]

            valid=valid.loc[
                (valid[ncol] != minv)
                &
                (valid[ncol] != maxv)
            ]

        # ======================================
        # Build instances
        # ======================================

        for _,row in valid.iterrows():

            instance={}

            instance["instance_id"]=instance_id
            instance["axis"]=axis
            instance["qerr"]=row[qcol]
            instance["plan_change"]=row[pcol]

            for c in x_cols:
                instance[c]=row[c]

            # --------------------------------
            # Neighbor coordinates
            # --------------------------------

            neighbor_coords=[]

            for c in x_cols:

                ncol=f"{c}_neighbor_axis{axis}"

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

            neighbor_key=tuple(
                neighbor_coords
            )

            neighbor_row=lookup.get(
                neighbor_key,
                None
            )

            ndim=len(x_cols)

            # --------------------------------
            # current selectivities
            # --------------------------------

            for a in range(ndim):

                instance[
                    f"selectivity_x{a+1}"
                ]=row.get(
                    f"selectivity_x{a+1}",
                    np.nan
                )

            # --------------------------------
            # neighbor selectivities
            # --------------------------------

            if neighbor_row is not None:

                for a in range(ndim):

                    instance[
                        f"neighbor_selectivity_x{a+1}"
                    ]=row.get(
                        f"neighbor_selectivity_x{a+1}_axis{axis}",
                        np.nan
                    )

                    instance[
                        f"dS_x{a+1}"
                    ]=row.get(
                        f"dS_x{a+1}_axis{axis}",
                        np.nan
                    )

                instance[
                    "joint_sel"
                ]=row.get(
                    "joint_sel",
                    np.nan
                )

                instance[
                    "neighbor_joint_sel"
                ]=row.get(
                    f"neighbor_joint_sel_axis{axis}",
                    np.nan
                )

                instance[
                    "joint_dS"
                ]=row.get(
                    f"joint_dS_axis{axis}",
                    np.nan
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

                for a in range(ndim):

                    instance[
                        f"neighbor_selectivity_x{a+1}"
                    ]=np.nan

                    instance[
                        f"dS_x{a+1}"
                    ]=np.nan

                instance[
                    "neighbor_joint_sel"
                ]=np.nan

                instance[
                    "joint_dS"
                ]=np.nan

            # =====================================
            # useful info
            # =====================================

            useful_cols=[

                "runtime_mean",
                "count_rows",
                "execution_time",
                "planning_time",
                "rows_ret",
                "plan_rows",
                "plan_hash",

                *[
                    f"selectivity_x{i+1}"
                    for i in range(ndim)
                ],

                *[
                    f"neighbor_selectivity_x{i+1}"
                    for i in range(ndim)
                ],

                *[
                    f"dS_x{i+1}"
                    for i in range(ndim)
                ],

                "joint_sel",
                "neighbor_joint_sel",
                "joint_dS"
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

    if len(rows)==0:
        print("No non-boundary qerr instances found")
        return

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

    out_csv=(OUTPUT_DIR / "qerr_desc_nb.csv")

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


    # ==========================================
    # Load file
    # ==========================================

    df = pd.read_csv(
        OUTPUT_DIR / "qerr_desc_nb.csv"
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
        df["joint_dS"]
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
        label="Joint dS CDF"
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
        "qerror_vs_planchange_nb_cdf_GLOBAL.png"
    )

    plt.savefig(
        out_path,
        dpi=300
    )

    print(
        f"Saved global plot: {out_path}"
    )