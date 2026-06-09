select
    count(*),
    sum(l.l_extendedprice)

from
    lineitem l
    join orders o
        on l.l_orderkey = o.o_orderkey

    join supplier s
        on s.s_suppkey = l.l_suppkey

where

(
    l.l_extendedprice <= :p1
)

or

(
    l.l_discount <= 0.01
    and s.s_acctbal > :p1 / 100
)

or

(
    l.l_quantity <= (:p1 / 1000)
)

or

(
    exists (
        select 1
        from lineitem lx
        where
            lx.l_orderkey = l.l_orderkey
            and lx.l_tax < (:p1 / 100000)
    )
)

group by
    o.o_orderpriority

order by
    sum(l.l_extendedprice);