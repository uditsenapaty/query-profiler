# =========================================================
# sampler_selectivity_m1.py
#
# resolution=10
#
# selectivities:
#
# 0.0,0.1,...,1.0
#
# => 11 points
# =========================================================

import psycopg2.sql as sql


def _target_selectivities(resolution):

    return [
        i/resolution
        for i in range(resolution+1)
    ]


def sample(conn,table,column,resolution,lower_bound=None):

    sels=_target_selectivities(
        resolution
    )

    query=sql.SQL("""
        SELECT percentile_cont(%s::float8[])
        WITHIN GROUP(
            ORDER BY {col}
        )
        FROM {tbl}
        WHERE (
            %s IS NULL
            OR
            {col} >= %s
        )
    """).format(
        col=sql.Identifier(column),
        tbl=sql.Identifier(table)
    )

    cur=conn.cursor()

    cur.execute(
        query,
        (
            sels,
            lower_bound,
            lower_bound
        )
    )

    values=cur.fetchone()[0]

    cur.close()

    values=_coerce(
        values,
        conn,
        table,
        column
    )

    return values


def _coerce(
    values,
    conn,
    table,
    column
):

    cur=conn.cursor()

    cur.execute("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name=%s
        AND column_name=%s
    """,
    (table,column))

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
        "smallint"
    ):
        return [
            int(round(v))
            for v in values
        ]

    return [
        float(v)
        for v in values
    ]


def selectivities(resolution):

    return _target_selectivities(
        resolution
    )