SELECT COUNT(*)
FROM (

    SELECT
        DATE_PART(
            'YEAR',
            o_orderdate
        ) AS o_year

    FROM
        part,
        supplier,
        lineitem,
        orders,
        customer,
        nation n1,
        nation n2,
        region

    WHERE

        p_partkey=l_partkey
        AND s_suppkey=l_suppkey
        AND l_orderkey=o_orderkey
        AND o_custkey=c_custkey
        AND c_nationkey=n1.n_nationkey
        AND n1.n_regionkey=r_regionkey
        AND r_name='AMERICA'
        AND s_nationkey=n2.n_nationkey
        AND o_orderdate
        BETWEEN
        '1995-01-01'
        AND '1996-12-31'
        AND p_type=
        'ECONOMY ANODIZED STEEL'

        AND s_acctbal<=-998.22
        AND l_extendedprice<=12461.9444444444

) x;