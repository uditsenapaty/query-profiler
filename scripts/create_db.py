import psycopg2

DBS = ["tpch", "tpcds", "imdb"]

conn = psycopg2.connect(
    dbname="postgres",
    user="postgres",
    password="112358",
    host="localhost",
    port="5432"
)

conn.autocommit = True
cur = conn.cursor()

for db in DBS:
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s;", (db,))
    exists = cur.fetchone()

    if exists:
        print(f"{db} already exists")
    else:
        cur.execute(f'CREATE DATABASE {db};')
        print(f"Created {db}")

cur.close()
conn.close()