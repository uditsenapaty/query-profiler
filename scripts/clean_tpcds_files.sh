#!/bin/bash

SRC=/home/kiit/query-profiler/data/tpcds
DST=/home/kiit/query-profiler/data/tpcds_clean

mkdir -p $DST

for f in $SRC/*.dat; do
    name=$(basename "$f")
    sed 's/|$//' "$f" > "$DST/$name"
    echo "Cleaned $name"
done
