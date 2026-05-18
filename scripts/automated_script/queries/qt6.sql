-- QT6 — TPC-H Q6 (1D) | PSP: l_extendedprice
select
    sum(l_extendedprice * l_discount) as revenue
from
    lineitem
where
    l_extendedprice <= :p1