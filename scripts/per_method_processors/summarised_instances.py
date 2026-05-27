# ==========================================================
# scripts/per_method_processors/summarised_instances.py
# ==========================================================

from pathlib import Path
import pandas as pd
import numpy as np


# ==========================================================

TOPK=1000


# ==========================================================

def run(results_dir):

    results_dir=Path(
        results_dir
    )

    infile=(

        results_dir
        /
        "merged_qerr_instances"
        /
        "all_qerr_instances_desc.csv"

    )

    if not infile.exists():

        print(
            f"missing: {infile}"
        )

        return


    outdir=(

        results_dir
        /
        "summaries"

    )

    outdir.mkdir(
        parents=True,
        exist_ok=True
    )


    print()
    print(
        "===================================="
    )
    print(
        "BUILDING INSTANCE SUMMARY"
    )
    print(
        "===================================="
    )


    # ======================================================
    # load
    # ======================================================

    df=pd.read_csv(
        infile
    )


    # ======================================================
    # coordinates
    # ======================================================

    x_cols=sorted([

        c

        for c in df.columns

        if (

            c.startswith("x")
            and
            "_neighbor" not in c

        )

    ])


    coord_cols=[
        "instance_id",
        *x_cols
    ]


    # ======================================================
    # top-k split
    # ======================================================

    top=df.head(
        min(
            TOPK,
            len(df)
        )
    )


    yes=top[

        top[
            "plan_change"
        ].astype(str)
        .str.upper()
        .isin([
            "TRUE",
            "YES",
            "1"
        ])

    ]


    no=top[

        ~top[
            "plan_change"
        ].astype(str)
        .str.upper()
        .isin([
            "TRUE",
            "YES",
            "1"
        ])

    ]


    # ======================================================
    # max qerror
    # ======================================================

    maxq=(

        df.groupby(
            coord_cols,
            dropna=False
        )["qerr"]

        .max()

        .reset_index()

        .rename(

            columns={

                "qerr":
                "max_qerr"

            }

        )
    )


    # ======================================================
    # plan-change counts
    # ======================================================

    yescnt=(

        yes.groupby(
            coord_cols,
            dropna=False
        )

        .size()

        .reset_index(
            name=
            "top1000_planchange_yes"
        )

    )


    nocnt=(

        no.groupby(
            coord_cols,
            dropna=False
        )

        .size()

        .reset_index(
            name=
            "top1000_planchange_no"
        )

    )


    # ======================================================
    # merge
    # ======================================================

    out=maxq.merge(

        yescnt,

        on=coord_cols,

        how="left"

    )


    out=out.merge(

        nocnt,

        on=coord_cols,

        how="left"

    )


    out[

        "top1000_planchange_yes"

    ]=(

        out[
            "top1000_planchange_yes"
        ]

        .fillna(0)
        .astype(int)

    )


    out[

        "top1000_planchange_no"

    ]=(

        out[
            "top1000_planchange_no"
        ]

        .fillna(0)
        .astype(int)

    )


    # ======================================================
    # sort
    # ======================================================

    out=out.sort_values(

        "max_qerr",

        ascending=False

    )


    out.insert(

        0,
        "rank",

        np.arange(
            1,
            len(out)+1
        )
    )


    # ======================================================
    # save
    # ======================================================

    outfile=(

        outdir
        /
        "summarised_instances.csv"

    )


    out.to_csv(

        outfile,
        index=False

    )


    print(
        f"saved: {outfile}"
    )

    print(
        f"rows: {len(out)}"
    )

    print()