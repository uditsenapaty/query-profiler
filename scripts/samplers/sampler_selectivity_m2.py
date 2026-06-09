# =========================================================
# sampler_selectivity_m2.py
#
# Picasso-style selectivity sampling
#
# resolution = number of intervals
#
# resolution=10
#
# 0-----1-----2-----...-----10
#
# => 11 points
#
# Uses:
#
# Picasso exponential selectivities
# +
# PostgreSQL percentile_cont()
#
# =========================================================

import numpy as np
import psycopg2.sql as sql

from functools import lru_cache


# ==========================================================
# Dynamic Picasso skew computation
# ==========================================================

@lru_cache(maxsize=None)
def _compute_r(
        resolution,
        target_space=0.20,
        target_points=0.80,
        tol=1e-6):

    n = resolution + 1

    k = int(
        round(
            target_points *
            resolution
        )
    )

    def ratio(r):

        num = (
            0.5 +
            sum(
                r**i
                for i in range(1,k)
            )
        )

        den = (
            0.5 +
            sum(
                r**i
                for i in range(
                    1,
                    n-1
                )
            )
            +
            0.5*(r**(n-1))
        )

        return num/den


    lo=1.000001
    hi=100.0


    while hi-lo>tol:

        mid=(lo+hi)/2

        val=ratio(mid)

        if val>target_space:
            lo=mid
        else:
            hi=mid


    return (lo+hi)/2


# ==========================================================
# Picasso selectivities
# ==========================================================

def _target_selectivities(
        resolution):

    n=resolution+1

    r=_compute_r(
        resolution
    )

    a=1.0

    cur=a
    total=a/2


    for i in range(
            1,
            n+1):

        cur*=r

        if i!=n:
            total+=cur
        else:
            total+=cur/2


    a=1/total


    vals=[]

    cur=a
    cumulative=a/2


    for i in range(
            1,
            n+1):

        vals.append(
            cumulative
        )

        cur*=r

        inc=cur

        if i==n:
            inc/=2

        cumulative+=inc


    vals=np.array(vals)

    vals/=vals[-1]

    vals[0]=0.0
    vals[-1]=1.0

    return vals.tolist()


# ==========================================================
# Datatype handling
# ==========================================================

def _coerce(
        values,
        conn,
        table,
        column):

    cur=conn.cursor()

    cur.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name=%s
        AND column_name=%s
        """,
        (
            table,
            column
        )
    )

    row=cur.fetchone()

    cur.close()

    dtype=(
        row[0]
        if row
        else "double precision"
    )


    if dtype in (
            "integer",
            "bigint",
            "smallint"):

        return [
            int(
                round(v)
            )
            for v in values
        ]


    return [
        float(v)
        for v in values
    ]


# ==========================================================
# Main sampler
# ==========================================================

def sample(
        conn,
        table,
        column,
        resolution):

    sels=(
        _target_selectivities(
            resolution
        )
    )


    query=sql.SQL(
        """
        SELECT
        percentile_cont(
            %s::float8[]
        )
        WITHIN GROUP(
            ORDER BY {col}
        )
        FROM {tbl}
        """
    ).format(
        col=sql.Identifier(
            column
        ),
        tbl=sql.Identifier(
            table
        )
    )


    cur=conn.cursor()

    cur.execute(
        query,
        (sels,)
    )

    values=(
        cur.fetchone()[0]
    )

    cur.close()


    values=_coerce(
        values,
        conn,
        table,
        column
    )


    return values


def selectivities(
        resolution):

    return _target_selectivities(
        resolution
    )