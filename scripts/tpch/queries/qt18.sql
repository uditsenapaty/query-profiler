-- QT18 — TPC-H Q18 (2D) | PSP: l_extendedprice (in IN subquery), c_acctbal
select
    c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice,
    sum(l_quantity)
from
    customer, orders, lineitem
where
    o_orderkey in (
        select l_orderkey
        from lineitem
        where l_extendedprice <= :p1
        group by l_orderkey
        having sum(l_quantity) > 300
    )
    and c_custkey = o_custkey
    and o_orderkey = l_orderkey
    and c_acctbal <= :p2
group by
    c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
order by
    o_totalprice desc, o_orderdate