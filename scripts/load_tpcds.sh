#!/bin/bash

DB=tpcds
BASE=/home/kiit/query-profiler/data/tpcds
USER=postgres
HOST=localhost

for f in $BASE/*.dat; do
    table=$(basename "$f" .dat)

    echo "-----------------------------------"
    echo "Loading $table ..."

    psql -U $USER -h $HOST -d $DB -c "\copy $table FROM '$f' WITH (FORMAT csv, DELIMITER '|', NULL '')"

    if [ $? -ne 0 ]; then
        echo "Failed loading $table"
    else
        echo "Loaded $table successfully"
    fi
done
