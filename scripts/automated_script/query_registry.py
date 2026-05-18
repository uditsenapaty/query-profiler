"""
query_registry.py — Metadata for all 19 tpch modified query templates.

Each entry defines:
  - sql_file: path to the .sql file
  - dims: 1 or 2 (number of PSP axes)
  - params: list of dicts, each with:
      name:   :p1 or :p2
      table:  source table for the column
      column: column name (used to discover min/max range)
      label:  human-readable label for reports
"""

QUERIES = {
    "qt1": {
        "label": "QT1 — TPC-H Q1 (Pricing Summary)",
        "sql_file": "queries/qt1.sql",
        "dims": 1,
        "tables": ["lineitem"],
        "params": [
            {"name": "p1", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt2": {
        "label": "QT2 — TPC-H Q2 (Min Cost Supplier)",
        "sql_file": "queries/qt2.sql",
        "dims": 2,
        "tables": ["part", "supplier", "partsupp", "nation", "region"],
        "params": [
            {"name": "p1", "table": "part", "column": "p_retailprice",
             "label": "p_retailprice"},
            {"name": "p2", "table": "partsupp", "column": "ps_supplycost",
             "label": "ps_supplycost"},
        ],
    },
    "qt3": {
        "label": "QT3 — TPC-H Q3 (Shipping Priority)",
        "sql_file": "queries/qt3.sql",
        "dims": 2,
        "tables": ["customer", "orders", "lineitem"],
        "params": [
            {"name": "p1", "table": "orders", "column": "o_totalprice",
             "label": "o_totalprice"},
            {"name": "p2", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt4": {
        "label": "QT4 — TPC-H Q4 (Order Priority)",
        "sql_file": "queries/qt4.sql",
        "dims": 2,
        "tables": ["orders", "lineitem"],
        "params": [
            {"name": "p1", "table": "orders", "column": "o_totalprice",
             "label": "o_totalprice"},
            {"name": "p2", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt5": {
        "label": "QT5 — TPC-H Q5 (Local Supplier Volume)",
        "sql_file": "queries/qt5.sql",
        "dims": 2,
        "tables": ["customer", "orders", "lineitem", "supplier", "nation", "region"],
        "params": [
            {"name": "p1", "table": "customer", "column": "c_acctbal",
             "label": "c_acctbal"},
            {"name": "p2", "table": "supplier", "column": "s_acctbal",
             "label": "s_acctbal"},
        ],
    },
    "qt6": {
        "label": "QT6 — TPC-H Q6 (Forecasting Revenue)",
        "sql_file": "queries/qt6.sql",
        "dims": 1,
        "tables": ["lineitem"],
        "params": [
            {"name": "p1", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt7": {
        "label": "QT7 — TPC-H Q7 (Volume Shipping)",
        "sql_file": "queries/qt7.sql",
        "dims": 2,
        "tables": ["supplier", "lineitem", "orders", "customer", "nation"],
        "params": [
            {"name": "p1", "table": "orders", "column": "o_totalprice",
             "label": "o_totalprice"},
            {"name": "p2", "table": "customer", "column": "c_acctbal",
             "label": "c_acctbal"},
        ],
    },
    "qt8": {
        "label": "QT8 — TPC-H Q8 (National Market Share)",
        "sql_file": "queries/qt8.sql",
        "dims": 2,
        "tables": ["part", "supplier", "lineitem", "orders", "customer", "nation", "region"],
        "params": [
            {"name": "p1", "table": "supplier", "column": "s_acctbal",
             "label": "s_acctbal"},
            {"name": "p2", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt9": {
        "label": "QT9 — TPC-H Q9 (Product Type Profit)",
        "sql_file": "queries/qt9.sql",
        "dims": 2,
        "tables": ["part", "supplier", "lineitem", "partsupp", "orders", "nation"],
        "params": [
            {"name": "p1", "table": "supplier", "column": "s_acctbal",
             "label": "s_acctbal"},
            {"name": "p2", "table": "partsupp", "column": "ps_supplycost",
             "label": "ps_supplycost"},
        ],
    },
    "qt10": {
        "label": "QT10 — TPC-H Q10 (Returned Items)",
        "sql_file": "queries/qt10.sql",
        "dims": 2,
        "tables": ["customer", "orders", "lineitem", "nation"],
        "params": [
            {"name": "p1", "table": "customer", "column": "c_acctbal",
             "label": "c_acctbal"},
            {"name": "p2", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt11": {
        "label": "QT11 — TPC-H Q11 (Important Stock)",
        "sql_file": "queries/qt11.sql",
        "dims": 2,
        "tables": ["partsupp", "supplier", "nation"],
        "params": [
            {"name": "p1", "table": "partsupp", "column": "ps_supplycost",
             "label": "ps_supplycost"},
            {"name": "p2", "table": "supplier", "column": "s_acctbal",
             "label": "s_acctbal"},
        ],
    },
    "qt12": {
        "label": "QT12 — TPC-H Q12 (Shipping Modes)",
        "sql_file": "queries/qt12.sql",
        "dims": 2,
        "tables": ["orders", "lineitem"],
        "params": [
            {"name": "p1", "table": "orders", "column": "o_totalprice",
             "label": "o_totalprice"},
            {"name": "p2", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt13": {
        "label": "QT13 — TPC-H Q13 (Customer Distribution)",
        "sql_file": "queries/qt13.sql",
        "dims": 1,
        "tables": ["customer", "orders"],
        "params": [
            {"name": "p1", "table": "orders", "column": "o_totalprice",
             "label": "o_totalprice"},
        ],
    },
    "qt14": {
        "label": "QT14 — TPC-H Q14 (Promotion Effect)",
        "sql_file": "queries/qt14.sql",
        "dims": 2,
        "tables": ["lineitem", "part"],
        "params": [
            {"name": "p1", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
            {"name": "p2", "table": "part", "column": "p_retailprice",
             "label": "p_retailprice"},
        ],
    },
    "qt16": {
        "label": "QT16 — TPC-H Q16 (Parts/Supplier)",
        "sql_file": "queries/qt16.sql",
        "dims": 2,
        "tables": ["partsupp", "part", "supplier"],
        "params": [
            {"name": "p1", "table": "part", "column": "p_retailprice",
             "label": "p_retailprice"},
            {"name": "p2", "table": "supplier", "column": "s_acctbal",
             "label": "s_acctbal"},
        ],
    },
    "qt17": {
        "label": "QT17 — TPC-H Q17 (Small-Quantity-Order)",
        "sql_file": "queries/qt17.sql",
        "dims": 2,
        "tables": ["lineitem", "part"],
        "params": [
            {"name": "p1", "table": "part", "column": "p_retailprice",
             "label": "p_retailprice"},
            {"name": "p2", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
    "qt18": {
        "label": "QT18 — TPC-H Q18 (Large Volume Customer)",
        "sql_file": "queries/qt18.sql",
        "dims": 2,
        "tables": ["customer", "orders", "lineitem"],
        "params": [
            {"name": "p1", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
            {"name": "p2", "table": "customer", "column": "c_acctbal",
             "label": "c_acctbal"},
        ],
    },
    "qt20": {
        "label": "QT20 — TPC-H Q20 (Potential Part Promotion)",
        "sql_file": "queries/qt20.sql",
        "dims": 2,
        "tables": ["supplier", "nation", "partsupp", "part", "lineitem"],
        "params": [
            {"name": "p1", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
            {"name": "p2", "table": "supplier", "column": "s_acctbal",
             "label": "s_acctbal"},
        ],
    },
    "qt21": {
        "label": "QT21 — TPC-H Q21 (Suppliers Who Kept Orders Waiting)",
        "sql_file": "queries/qt21.sql",
        "dims": 2,
        "tables": ["supplier", "lineitem", "orders", "nation"],
        "params": [
            {"name": "p1", "table": "supplier", "column": "s_acctbal",
             "label": "s_acctbal"},
            {"name": "p2", "table": "lineitem", "column": "l_extendedprice",
             "label": "l_extendedprice"},
        ],
    },
}

# Ordered list for batch processing
QUERY_ORDER = [
    "qt1", "qt2", "qt3", "qt4", "qt5", "qt6", "qt7", "qt8", "qt9",
    "qt10", "qt11", "qt12", "qt13", "qt14", "qt16", "qt17", "qt18",
    "qt20", "qt21",
]