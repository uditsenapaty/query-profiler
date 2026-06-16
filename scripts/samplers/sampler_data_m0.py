# =========================================================
# sampler_normal.py
#
# resolution=10
#
# points:
#
# min,
# min+1/10 range,
# ...
# max
#
# => 11 points
# =========================================================

import numpy as np
import pandas as pd
from decimal import Decimal
import psycopg2.sql as sql


def get_param_range(
    conn,
    table,
    column
):

    cur=conn.cursor()

    cur.execute(
        sql.SQL("""
        SELECT
            MIN({col}),
            MAX({col}),
            COUNT(DISTINCT {col})
        FROM {tbl}
        """).format(
            col=sql.Identifier(column),
            tbl=sql.Identifier(table)
        )
    )

    lo,hi,distinct=cur.fetchone()

    cur.close()

    return lo,hi,distinct


def _linspace(
    start,
    end,
    resolution
):

    npoints=resolution+1


    if isinstance(start,int):

        vals=np.linspace(
            start,
            end,
            npoints
        )

        vals=np.round(
            vals
        ).astype(int)

        vals=np.unique(
            vals
        )

        return list(vals)


    if isinstance(
        start,
        float
    ):

        return list(
            np.linspace(
                float(start),
                float(end),
                npoints
            )
        )


    if isinstance(
        start,
        Decimal
    ):

        vals=np.linspace(
            float(start),
            float(end),
            npoints
        )

        return [
            Decimal(
                str(
                    round(v,10)
                )
            )
            for v in vals
        ]


    if isinstance(
        start,
        pd.Timestamp
    ):

        return list(
            pd.date_range(
                start=start,
                end=end,
                periods=npoints
            )
        )


    if hasattr(
        start,
        "toordinal"
    ):

        s=start.toordinal()
        e=end.toordinal()

        vals=np.linspace(
            s,
            e,
            npoints
        )

        vals=np.round(
            vals
        ).astype(int)

        return [
            type(start).fromordinal(
                int(v)
            )
            for v in vals
        ]

    raise RuntimeError(
        f"Unsupported type {type(start)}"
    )


def sample(
    conn,
    table,
    column,
    resolution,
    lower_bound=None
):

    lo,hi,_=get_param_range(
        conn,
        table,
        column
    )

    if lower_bound is not None:
        lo = lower_bound

    return _linspace(
        lo,
        hi,
        resolution
    )