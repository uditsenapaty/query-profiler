-- QT4 — TPC-H Q4 (2D) | PSP: o_totalprice, l_extendedprice (in EXISTS)
select
    o_orderpriority,
    count(*) as order_count
from
    orders
where
    o_totalprice <= :p1
    and exists (
        select *
        from lineitem
        where l_orderkey = o_orderkey
            and l_extendedprice <= :p2
    )
group by
    o_orderpriority
order by
    o_orderpriority