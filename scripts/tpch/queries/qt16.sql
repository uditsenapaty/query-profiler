-- QT16 — TPC-H Q16 (2D) | PSP: p_retailprice, s_acctbal (in IN subquery)
select
    p_brand, p_type, p_retailprice,
    count(distinct ps_suppkey) as supplier_cnt
from
    partsupp, part
where
    p_partkey = ps_partkey
    and p_retailprice <= :p1
    and ps_suppkey in (
        select s_suppkey
        from supplier
        where s_acctbal <= :p2
    )
group by
    p_brand, p_type, p_retailprice
order by
    supplier_cnt desc, p_brand, p_type, p_retailprice