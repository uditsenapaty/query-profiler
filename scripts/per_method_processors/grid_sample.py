# ==========================================================
# scripts/per_method_processors/grid_sample.py
# ==========================================================

from pathlib import Path
import pandas as pd
import numpy as np


# ==========================================================

def run(results_dir):

    results_dir=Path(
        results_dir
    )

    csv=(
        results_dir/
        "ground_truth.csv"
    )

    if not csv.exists():
        return


    df=pd.read_csv(
        csv
    )

    outdir=(
        results_dir/
        "grid_sample"
    )

    outdir.mkdir(
        parents=True,
        exist_ok=True
    )


    x_cols=sorted([

        c

        for c in df.columns

        if (

            c.startswith("x")
            and
            "_neighbor_" not in c

        )

    ])

    ndim=len(
        x_cols
    )


    if ndim==0:
        return


    # ======================================================
    # 1D
    # ======================================================

    if ndim==1:

        x=x_cols[0]

        for axis in range(
                1,
                ndim+1
        ):

            col=(
                f"selectivity_x{axis}"
            )

            if col not in df.columns:
                continue


            out=df[[

                x,
                col

            ]].copy()


            out=out.sort_values(
                x
            )


            out.to_csv(

                outdir/
                f"axis_{axis}.csv",

                index=False
            )


        if "joint_sel" in df.columns:

            out=df[[

                x,
                "joint_sel"

            ]].copy()


            out=out.sort_values(
                x
            )


            out.to_csv(

                outdir/
                "joint_axis.csv",

                index=False
            )


    # ======================================================
    # 2D
    # ======================================================

    else:

        x=np.sort(
            df["x1"].unique()
        )

        y=np.sort(
            df["x2"].unique()
        )


        # ==========================================
        # axis selectivities
        # ==========================================

        for axis in range(
                1,
                ndim+1
        ):

            col=(
                f"selectivity_x{axis}"
            )

            if col not in df.columns:
                continue


            grid=df.pivot(

                index="x2",
                columns="x1",
                values=col

            )


            grid=grid.loc[
                y,
                x
            ]


            grid.to_csv(

                outdir/
                f"axis_{axis}.csv"
            )


        # ==========================================
        # joint selectivity
        # ==========================================

        if "joint_sel" in df.columns:

            grid=df.pivot(

                index="x2",
                columns="x1",
                values="joint_sel"
            )

            grid=grid.loc[
                y,
                x
            ]


            grid.to_csv(

                outdir/
                "joint_axis.csv"
            )


    print(
        f"saved: {outdir}"
    )