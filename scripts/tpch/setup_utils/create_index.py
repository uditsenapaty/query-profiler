# scripts/create_index.py

import psycopg2
from tpch.setup_tpch import (
    DATABASE_NAME,
    USER,
    PASSWORD,
    HOST
)

# ==========================================================
# Consolidated Picasso/TPCH workload indexes
# ==========================================================

INDEXES = [

    # ======================================================
    # LINEITEM
    # ======================================================

    (
        "idx_lineitem_extendedprice",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_extendedprice
        ON lineitem(l_extendedprice)
        """
    ),

    (
        "idx_lineitem_orderkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_orderkey
        ON lineitem(l_orderkey)
        """
    ),

    (
        "idx_lineitem_partkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_partkey
        ON lineitem(l_partkey)
        """
    ),

    (
        "idx_lineitem_suppkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_suppkey
        ON lineitem(l_suppkey)
        """
    ),

    (
        "idx_lineitem_part_supp",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_part_supp
        ON lineitem(
            l_partkey,
            l_suppkey
        )
        """
    ),

    (
        "idx_lineitem_order_supp",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_order_supp
        ON lineitem(
            l_orderkey,
            l_suppkey
        )
        """
    ),

    (
        "idx_lineitem_shipdate",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_shipdate
        ON lineitem(l_shipdate)
        """
    ),

    (
        "idx_lineitem_receipt_commit",
        """
        CREATE INDEX IF NOT EXISTS
        idx_lineitem_receipt_commit
        ON lineitem(
            l_receiptdate,
            l_commitdate
        )
        """
    ),

    # ======================================================
    # ORDERS
    # ======================================================

    (
        "idx_orders_totalprice",
        """
        CREATE INDEX IF NOT EXISTS
        idx_orders_totalprice
        ON orders(o_totalprice)
        """
    ),

    (
        "idx_orders_custkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_orders_custkey
        ON orders(o_custkey)
        """
    ),

    (
        "idx_orders_orderdate",
        """
        CREATE INDEX IF NOT EXISTS
        idx_orders_orderdate
        ON orders(o_orderdate)
        """
    ),

    (
        "idx_orders_status",
        """
        CREATE INDEX IF NOT EXISTS
        idx_orders_status
        ON orders(o_orderstatus)
        """
    ),

    (
        "idx_orders_cust_total",
        """
        CREATE INDEX IF NOT EXISTS
        idx_orders_cust_total
        ON orders(
            o_custkey,
            o_totalprice
        )
        """
    ),

    # ======================================================
    # CUSTOMER
    # ======================================================

    (
        "idx_customer_acctbal",
        """
        CREATE INDEX IF NOT EXISTS
        idx_customer_acctbal
        ON customer(c_acctbal)
        """
    ),

    (
        "idx_customer_nationkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_customer_nationkey
        ON customer(c_nationkey)
        """
    ),

    (
        "idx_customer_mktsegment",
        """
        CREATE INDEX IF NOT EXISTS
        idx_customer_mktsegment
        ON customer(c_mktsegment)
        """
    ),

    # ======================================================
    # SUPPLIER
    # ======================================================

    (
        "idx_supplier_acctbal",
        """
        CREATE INDEX IF NOT EXISTS
        idx_supplier_acctbal
        ON supplier(s_acctbal)
        """
    ),

    (
        "idx_supplier_nationkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_supplier_nationkey
        ON supplier(s_nationkey)
        """
    ),

    # ======================================================
    # PART
    # ======================================================

    (
        "idx_part_retailprice",
        """
        CREATE INDEX IF NOT EXISTS
        idx_part_retailprice
        ON part(p_retailprice)
        """
    ),

    (
        "idx_part_type",
        """
        CREATE INDEX IF NOT EXISTS
        idx_part_type
        ON part(p_type)
        """
    ),

    (
        "idx_part_name",
        """
        CREATE INDEX IF NOT EXISTS
        idx_part_name
        ON part(p_name)
        """
    ),

    (
        "idx_part_name_pattern",
        """
        CREATE INDEX IF NOT EXISTS
        idx_part_name_pattern
        ON part(
            p_name text_pattern_ops
        )
        """
    ),

    # ======================================================
    # PARTSUPP
    # ======================================================

    (
        "idx_partsupp_supplycost",
        """
        CREATE INDEX IF NOT EXISTS
        idx_partsupp_supplycost
        ON partsupp(ps_supplycost)
        """
    ),

    (
        "idx_partsupp_partkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_partsupp_partkey
        ON partsupp(ps_partkey)
        """
    ),

    (
        "idx_partsupp_suppkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_partsupp_suppkey
        ON partsupp(ps_suppkey)
        """
    ),

    (
        "idx_partsupp_part_supp",
        """
        CREATE INDEX IF NOT EXISTS
        idx_partsupp_part_supp
        ON partsupp(
            ps_partkey,
            ps_suppkey
        )
        """
    ),

    (
        "idx_partsupp_supply_part",
        """
        CREATE INDEX IF NOT EXISTS
        idx_partsupp_supply_part
        ON partsupp(
            ps_supplycost,
            ps_partkey
        )
        """
    ),

    # ======================================================
    # NATION / REGION
    # ======================================================

    (
        "idx_nation_regionkey",
        """
        CREATE INDEX IF NOT EXISTS
        idx_nation_regionkey
        ON nation(n_regionkey)
        """
    ),

    (
        "idx_nation_name",
        """
        CREATE INDEX IF NOT EXISTS
        idx_nation_name
        ON nation(n_name)
        """
    ),

    (
        "idx_region_name",
        """
        CREATE INDEX IF NOT EXISTS
        idx_region_name
        ON region(r_name)
        """
    ),

]


def connect():

    return psycopg2.connect(
        dbname=DATABASE_NAME,
        user=USER,
        password=PASSWORD,
        host=HOST
    )


def create_indexes():

    conn = connect()

    try:

        conn.autocommit = False

        cur = conn.cursor()

        print("="*60)
        print("Creating Picasso indexes")
        print("="*60)

        for idx_name, sql in INDEXES:

            try:

                print(
                    f"[CREATE] {idx_name}"
                )

                cur.execute(sql)

            except Exception as e:

                conn.rollback()

                print(
                    f"[FAILED] {idx_name}"
                )

                print(e)

                continue

        print("\nRunning ANALYZE ...")

        cur.execute(
            """
            ANALYZE lineitem;
            ANALYZE orders;
            ANALYZE customer;
            ANALYZE supplier;
            ANALYZE part;
            ANALYZE partsupp;
            ANALYZE nation;
            ANALYZE region;
            """
        )

        conn.commit()

        cur.close()

        print("\nDone.")

    finally:

        conn.close()


if __name__=="__main__":

    create_indexes()