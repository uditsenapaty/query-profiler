# =========================================================
# scripts/generate_tpch_schema.py
# =========================================================

import psycopg2

from tpch.setup_tpch import (
    DATABASE_NAME,
    USER,
    PASSWORD,
    HOST,
    PORT
)

conn=psycopg2.connect(
    dbname=DATABASE_NAME,
    user=USER,
    password=PASSWORD,
    host=HOST,
    port=PORT
)

cur=conn.cursor()


# ===============================
# CREATE TABLES
# ===============================
table_statements = [
    """
    CREATE TABLE IF NOT EXISTS region (
        r_regionkey INT PRIMARY KEY,
        r_name VARCHAR(25),
        r_comment VARCHAR(152)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS nation (
        n_nationkey INT PRIMARY KEY,
        n_name VARCHAR(25),
        n_regionkey INT REFERENCES region(r_regionkey),
        n_comment VARCHAR(152)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS supplier (
        s_suppkey INT PRIMARY KEY,
        s_name VARCHAR(25),
        s_address VARCHAR(40),
        s_nationkey INT REFERENCES nation(n_nationkey),
        s_phone VARCHAR(15),
        s_acctbal NUMERIC,
        s_comment VARCHAR(101)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS customer (
        c_custkey INT PRIMARY KEY,
        c_name VARCHAR(25),
        c_address VARCHAR(40),
        c_nationkey INT REFERENCES nation(n_nationkey),
        c_phone VARCHAR(15),
        c_acctbal NUMERIC,
        c_mktsegment VARCHAR(10),
        c_comment VARCHAR(117)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS part (
        p_partkey INT PRIMARY KEY,
        p_name VARCHAR(55),
        p_mfgr VARCHAR(25),
        p_brand VARCHAR(10),
        p_type VARCHAR(25),
        p_size INT,
        p_container VARCHAR(10),
        p_retailprice NUMERIC,
        p_comment VARCHAR(23)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS partsupp (
        ps_partkey INT REFERENCES part(p_partkey),
        ps_suppkey INT REFERENCES supplier(s_suppkey),
        ps_availqty INT,
        ps_supplycost NUMERIC,
        ps_comment VARCHAR(199),
        PRIMARY KEY (ps_partkey, ps_suppkey)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        o_orderkey INT PRIMARY KEY,
        o_custkey INT REFERENCES customer(c_custkey),
        o_orderstatus CHAR(1),
        o_totalprice NUMERIC,
        o_orderdate DATE,
        o_orderpriority CHAR(15),
        o_clerk CHAR(15),
        o_shippriority INT,
        o_comment VARCHAR(79)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS lineitem (
        l_orderkey INT REFERENCES orders(o_orderkey),
        l_partkey INT REFERENCES part(p_partkey),
        l_suppkey INT REFERENCES supplier(s_suppkey),
        l_linenumber INT,
        l_quantity NUMERIC,
        l_extendedprice NUMERIC,
        l_discount NUMERIC,
        l_tax NUMERIC,
        l_returnflag CHAR(1),
        l_linestatus CHAR(1),
        l_shipdate DATE,
        l_commitdate DATE,
        l_receiptdate DATE,
        l_shipinstruct CHAR(25),
        l_shipmode CHAR(10),
        l_comment VARCHAR(44),
        PRIMARY KEY (l_orderkey, l_linenumber)
    );
    """
]

for stmt in table_statements:
    cur.execute(stmt)
conn.commit()

cur.close()
conn.close()

print("TPCH Schema created.")