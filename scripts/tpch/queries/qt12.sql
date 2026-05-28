-- QT12 — TPC-H Q12 (2D) | PSP: o_totalprice, l_extendedprice
select
    l_shipmode,
    sum(case when o_orderpriority = '1-URGENT' or o_orderpriority = '2-HIGH' then 1 else 0 end) as high_line_count,
    sum(case when o_orderpriority <> '1-URGENT' and o_orderpriority <> '2-HIGH' then 1 else 0 end) as low_line_count
from
    orders, lineitem
where
    o_orderkey = l_orderkey
    and o_totalprice <= :p1
    and l_extendedprice <= :p2
group by
    l_shipmode
order by
    l_shipmode