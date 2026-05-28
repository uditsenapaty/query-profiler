-- QT14 — TPC-H Q14 (2D) | PSP: l_extendedprice, p_retailprice
select
    l_extendedprice * (1 - l_discount)
from
    lineitem, part
where
    l_partkey = p_partkey
    and l_extendedprice <= :p1
    and p_retailprice <= :p2