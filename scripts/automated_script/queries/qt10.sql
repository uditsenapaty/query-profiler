-- QT10 — TPC-H Q10 (2D) | PSP: c_acctbal, l_extendedprice
select
    c_custkey, c_name,
    sum(l_extendedprice * (1 - l_discount)) as revenue,
    c_acctbal, n_name, c_address, c_phone, c_comment
from
    customer, orders, lineitem, nation
where
    c_custkey = o_custkey
    and l_orderkey = o_orderkey
    and o_orderdate >= '1993-10-01'
    and o_orderdate < '1994-01-01'
    and c_nationkey = n_nationkey
    and c_acctbal <= :p1
    and l_extendedprice <= :p2
group by
    c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment
order by
    revenue desc