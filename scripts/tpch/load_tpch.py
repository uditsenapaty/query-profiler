import psycopg2
import os
import tempfile

DB_NAME = "tpch"
DB_USER = "postgres"
DB_PASS = "112358"
DB_HOST = "127.0.0.1"
DB_PORT = "5432"

BASE_DIR = "/home/kiit/query-profiler"
TPCH_DATA_DIR = os.path.join(BASE_DIR, "data/tpch")

conn = psycopg2.connect(
    dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT
)
cur = conn.cursor()

# Tables in dependency order
tables_in_order = [
    ("region", "region.tbl"),
    ("nation", "nation.tbl"),
    ("supplier", "supplier.tbl"),
    ("customer", "customer.tbl"),
    ("part", "part.tbl"),
    ("partsupp", "partsupp.tbl"),
    ("orders", "orders.tbl"),
    ("lineitem", "lineitem.tbl")
]

for table, filename in tables_in_order:
    file_path = os.path.join(TPCH_DATA_DIR, filename)
    if not os.path.exists(file_path):
        print(f"File {file_path} not found, skipping {table}.")
        continue

    print(f"Loading {table} from {file_path}...")

    # Use a temporary file to stream cleaned data
    with tempfile.TemporaryFile(mode="w+t") as tmpfile:
        with open(file_path, "r") as f:
            for line in f:
                # Strip trailing '|' and newline, then write a clean newline
                tmpfile.write(line.rstrip("|\n") + "\n")
        # Go back to the beginning of the temp file
        tmpfile.seek(0)

        # COPY in text mode (no CSV) with delimiter '|'
        cur.copy_expert(
            sql=f"COPY {table} FROM STDIN WITH DELIMITER '|' NULL ''",
            file=tmpfile
        )
    conn.commit()

cur.close()
conn.close()
print("TPCH data load complete.")