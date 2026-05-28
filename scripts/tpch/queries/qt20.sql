-- QT20 — TPC-H Q20 (2D) | PSP: l_extendedprice (nested subquery), s_acctbal
select
    s_name, s_address
from
    supplier, nation
where
    s_suppkey in (
        select ps_suppkey
        from partsupp
        where ps_partkey in (
            select p_partkey from part where p_name like 'forest%'
        )
        and ps_availqty < (
            select 0.5 * sum(l_quantity)
            from lineitem
            where l_partkey = ps_partkey
                and l_suppkey = ps_suppkey
                and l_extendedprice <= :p1
        )
    )
    and s_nationkey = n_nationkey
    and s_acctbal <= :p2
    and n_name = 'AMERICA'
order by
    s_name