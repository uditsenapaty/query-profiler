# scripts/show_param_ranges.py

# =========================================================
from config_gt import QUERY_SQL_PATH
# =========================================================

import re
import psycopg2.sql as sql

from connect_db import get_conn
from tpch_query_parser import TPCHQueryParser

conn = get_conn("tpch")

# =========================================================
# Load SQL
# =========================================================

with open(QUERY_SQL_PATH, "r") as f:
    sql_text = f.read()

# =========================================================
# AST SQL parsing
# =========================================================

parser = TPCHQueryParser()

parsed = parser.parse(sql_text)

# =========================================================
# aliases
# =========================================================

table_aliases = parsed["aliases"]

# =========================================================
# parameters
# =========================================================

param_columns = [
    p.replace(":", "")
    for p in parsed["parameters"]
]

param_columns = sorted(
    param_columns,
    key=lambda x: int(x[1:])
)

# =========================================================
# param -> column mapping
# =========================================================

param_to_column = {}

for pred in parsed["predicates"]:

    cols = pred["columns"]
    params = pred["parameters"]

    if len(cols) == 0:
        continue

    if len(params) == 0:
        continue

    col = cols[0]

    for p in params:

        p_clean = p.replace(":", "")

        if p_clean not in param_to_column:
            param_to_column[p_clean] = col

print("Table aliases:", table_aliases)

print("Parameter mapping:", param_to_column)

# =========================================================
# Resolve unqualified column
# =========================================================

def resolve_column(
    conn,
    column_expr,
    table_aliases
):

    # -----------------------------------------------------
    # Qualified
    # -----------------------------------------------------

    if "." in column_expr:

        alias, column = column_expr.split(".", 1)

        if alias not in table_aliases:

            raise RuntimeError(
                f"Unknown alias: {alias}"
            )

        return (
            table_aliases[alias],
            column
        )

    # -----------------------------------------------------
    # Unqualified
    # -----------------------------------------------------

    column = column_expr

    cur = conn.cursor()

    cur.execute("""
        SELECT table_name
        FROM information_schema.columns
        WHERE column_name = %s
    """, (column,))

    matches = [
        r[0]
        for r in cur.fetchall()
    ]

    cur.close()

    query_tables = set(
        table_aliases.values()
    )

    matches = [
        t for t in matches
        if t in query_tables
    ]

    if len(matches) == 0:

        raise RuntimeError(
            f"Could not resolve column: {column}"
        )

    if len(matches) > 1:

        raise RuntimeError(
            f"Ambiguous column: {column}"
        )

    return matches[0], column

# =========================================================
# Show ranges
# =========================================================

from decimal import Decimal
from datetime import (
    date,
    datetime,
    timedelta
)

DEFAULT_RESOLUTION = 100

print("\n=================================================")
print("Parameter Ranges")
print("=================================================\n")

for param in sorted(param_to_column.keys()):

    column_expr = param_to_column[param]

    real_table, column = resolve_column(
        conn,
        column_expr,
        table_aliases
    )

    # -----------------------------------------------------
    # Query stats
    # -----------------------------------------------------

    cur = conn.cursor()

    query = sql.SQL("""
        SELECT
            MIN({col}),
            MAX({col}),
            COUNT(DISTINCT {col}),
            pg_typeof(MIN({col}))::text
        FROM {tbl}
    """).format(
        col=sql.Identifier(column),
        tbl=sql.Identifier(real_table)
    )

    cur.execute(query)

    min_val, max_val, distinct_count, pg_type = cur.fetchone()

    cur.close()

    # -----------------------------------------------------
    # Type detection
    # -----------------------------------------------------

    param_kind = "unknown"

    if isinstance(min_val, bool):

        param_kind = "boolean"

    elif isinstance(min_val, int):

        param_kind = "integer"

    elif isinstance(min_val, float):

        param_kind = "float"

    elif isinstance(min_val, Decimal):

        param_kind = "decimal"

    elif isinstance(min_val, datetime):

        param_kind = "timestamp"

    elif isinstance(min_val, date):

        param_kind = "date"

    # -----------------------------------------------------
    # Range computation
    # -----------------------------------------------------

    range_val = None

    try:
        range_val = max_val - min_val
    except:
        pass

    # -----------------------------------------------------
    # Max possible resolution
    # -----------------------------------------------------

    # FLOAT / DECIMAL:
    # theoretically continuous
    #
    # INTEGER / DATE:
    # bounded by actual domain size

    if param_kind in ["float", "decimal"]:

        max_resolution = "UNBOUNDED"

    elif param_kind == "integer":

        max_resolution = int(max_val - min_val + 1)

    elif param_kind == "date":

        max_resolution = (
            (max_val - min_val).days + 1
        )

    elif param_kind == "timestamp":

        # too granular to infer safely
        max_resolution = distinct_count

    else:

        max_resolution = distinct_count

    # -----------------------------------------------------
    # Recommended resolution
    # -----------------------------------------------------

    if isinstance(max_resolution, int):

        recommended_resolution = min(
            DEFAULT_RESOLUTION,
            max_resolution
        )

    else:

        recommended_resolution = DEFAULT_RESOLUTION

    # -----------------------------------------------------
    # Pretty print
    # -----------------------------------------------------

    print(f"{param}")
    print(f"  table                  : {real_table}")
    print(f"  column                 : {column}")
    print(f"  postgres type          : {pg_type}")
    print(f"  inferred param type    : {param_kind}")

    print(f"  min                    : {min_val}")
    print(f"  max                    : {max_val}")

    if range_val is not None:
        print(f"  range                  : {range_val}")
    else:
        print(f"  range                  : N/A")

    print(f"  distinct values        : {distinct_count}")

    print(f"  max possible resolution: {max_resolution}")

    print(
        f"  recommended resolution : "
        f"{recommended_resolution}"
    )

    print()

conn.close()