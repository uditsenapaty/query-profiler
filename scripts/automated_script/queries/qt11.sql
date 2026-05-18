-- QT11 — TPC-H Q11 (2D) | PSP: ps_supplycost, s_acctbal
select
    ps_partkey,
    sum(ps_supplycost * ps_availqty) as value
from
    partsupp, supplier, nation
where
    ps_suppkey = s_suppkey
    and s_nationkey = n_nationkey
    and n_name = 'GERMANY'
    and ps_supplycost <= :p1
    and s_acctbal <= :p2
group by
    ps_partkey
having
    sum(ps_supplycost * ps_availqty) > (
        select sum(ps_supplycost * ps_availqty) * 0.0001000000
        from partsupp, supplier, nation
        where ps_suppkey = s_suppkey
            and s_nationkey = n_nationkey
            and n_name = 'GERMANY'
    )
order by
    value desc