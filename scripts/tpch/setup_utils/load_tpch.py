# tpch/load_tpch.py

import tempfile
import psycopg2

from tpch.setup_tpch import (

    DATABASE_NAME,
    USER,
    PASSWORD,
    HOST,
    PORT,
    DATA_DIR,
    TABLE_LOAD_ORDER
)

conn=psycopg2.connect(

    dbname=DATABASE_NAME,
    user=USER,
    password=PASSWORD,
    host=HOST,
    port=PORT
)

cur=conn.cursor()

for table in TABLE_LOAD_ORDER:

    filepath=(
        DATA_DIR
        /f"{table}.tbl"
    )

    if not filepath.exists():

        print(
            f"Missing {filepath}"
        )

        continue

    print(
        f"Loading {table}"
    )

    with tempfile.TemporaryFile(
        mode="w+t"
    ) as tmp:

        with open(
            filepath,
            "r"
        ) as f:

            for line in f:

                tmp.write(
                    line.rstrip(
                        "|\n"
                    )
                    +"\n"
                )

        tmp.seek(0)

        cur.copy_expert(

            sql=
            f"""
            COPY {table}
            FROM STDIN
            WITH (
                DELIMITER '|',
                NULL ''
            )
            """,

            file=tmp
        )

        conn.commit()

cur.close()
conn.close()

print("TPCH data load complete.")