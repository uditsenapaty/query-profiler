# =========================================================
# sampler_normal.py
#
# Linear (equi-spaced) sampling in the *parameter-value*
# domain. This is the original ground-truth sampler.
#
# Pros: works for any number of dimensions; trivial.
# Cons: the resulting *selectivities* are NOT uniform — the
#       grid may bunch up in dense regions of the value
#       distribution and leave sparse regions barely covered.
# =========================================================

import numpy as np
import pandas as pd
from decimal import Decimal
import psycopg2.sql as sql


def get_param_range(conn, table, column):
    cur = conn.cursor()
    cur.execute(
        sql.SQL("""
            SELECT MIN({col}), MAX({col}), COUNT(DISTINCT {col})
            FROM {tbl}
        """).format(
            col=sql.Identifier(column),
            tbl=sql.Identifier(table),
        )
    )
    lo, hi, distinct = cur.fetchone()
    cur.close()
    return lo, hi, distinct


def _linspace(start, end, resolution):
    """Type-aware linear spacing between start and end."""

    if isinstance(start, int) and isinstance(end, int):
        resolution = min(resolution, int(end - start + 1))
        vals = np.linspace(start, end, resolution)
        vals = np.unique(np.round(vals).astype(int))
        return list(vals)

    if isinstance(start, float) or isinstance(end, float):
        return list(np.linspace(float(start), float(end), resolution))

    if isinstance(start, Decimal):
        vals = np.linspace(float(start), float(end), resolution)
        return [Decimal(str(round(v, 10))) for v in vals]

    if isinstance(start, pd.Timestamp):
        return list(pd.date_range(start=start, end=end, periods=resolution))

    if hasattr(start, "toordinal"):
        s = start.toordinal()
        e = end.toordinal()
        resolution = min(resolution, e - s + 1)
        vals = np.linspace(s, e, resolution, dtype=int)
        return [type(start).fromordinal(int(v)) for v in vals]

    raise RuntimeError(f"Unsupported parameter type: {type(start)}")


def sample(conn, table, column, resolution):
    """
    Return a list of `resolution` values linearly spaced between
    MIN({column}) and MAX({column}) on `table`.
    """
    lo, hi, _distinct = get_param_range(conn, table, column)
    return _linspace(lo, hi, resolution)
