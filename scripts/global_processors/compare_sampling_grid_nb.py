# =========================================================
# scripts/global_processors/compare_sampling_grid_nb.py
# =========================================================

from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde
import config_gt


# ======================================
# CUSTOM COLORS
# ======================================

METHOD_COLORS={

    "m0":"blue",
    "m1":"red",
    "m2":"green"
}

GRID_ALPHA=.55
GRID_WIDTH=1.5
POINT_SIZE=60


# ======================================
# callable
# ======================================

def run(main_dir=None):

    if main_dir is None:
        main_dir=config_gt.MAIN_DIR

    main_dir=Path(main_dir)

    methods=[]


    # ==================================
    # dynamically load methods
    # ==================================

    for m in config_gt.METHOD_CONFIGS:

        dirs=list(

            main_dir.glob(
                f"{m}_*"
            )

        )

        if len(dirs)==0:
            continue

        df=pd.read_csv(
            dirs[0]/
            "ground_truth.csv"
        )

        methods.append(
            (m,df)
        )


    if len(methods)==0:
        return


    # ==================================
    # density background
    # use ALL points
    # ==================================

    allx=np.concatenate([

        df["x1"].values

        for _,df in methods

    ])

    ally=np.concatenate([

        df["x2"].values

        for _,df in methods

    ])


    xy=np.vstack([

        allx,
        ally

    ])


    kde=gaussian_kde(
        xy
    )


    xx,yy=np.mgrid[

        allx.min():allx.max():300j,

        ally.min():ally.max():300j

    ]


    coords=np.vstack([

        xx.ravel(),
        yy.ravel()

    ])


    z=kde(
        coords
    ).reshape(
        xx.shape
    )


    plt.figure(
        figsize=(15,12)
    )


    plt.contourf(

        xx,
        yy,
        z,

        levels=25,
        alpha=.35

    )


    # ==================================
    # grids
    # ==================================

    for method,df in methods:

        color=METHOD_COLORS.get(
            method,
            "black"
        )


        x=np.sort(
            df["x1"].unique()
        )

        y=np.sort(
            df["x2"].unique()
        )


        # ==========================
        # remove only boundary lines
        # ==========================

        x_draw=x[1:-1]
        y_draw=y[1:-1]


        # --------------------------
        # horizontal
        # --------------------------

        for yy in y_draw:

            plt.plot(

                x_draw,

                [yy]*len(x_draw),

                "-",

                color=color,

                alpha=GRID_ALPHA,

                linewidth=GRID_WIDTH

            )


        # --------------------------
        # vertical
        # --------------------------

        for xx in x_draw:

            plt.plot(

                [xx]*len(y_draw),

                y_draw,

                "-",

                color=color,

                alpha=GRID_ALPHA,

                linewidth=GRID_WIDTH

            )


        # ==========================
        # KEEP ALL POINTS
        # ==========================

        plt.scatter(

            df["x1"],
            df["x2"],

            color=color,

            s=POINT_SIZE,

            label=method

        )


    plt.xticks([])
    plt.yticks([])

    plt.legend()

    plt.tight_layout()


    out=(

        main_dir/
        "sampling_grid_compare_nb.png"

    )


    plt.savefig(

        out,
        dpi=300

    )

    plt.close()


    print(
        f"Saved: {out}"
    )


# ======================================
# standalone
# ======================================

if __name__=="__main__":

    run()