import psycopg2

PASSWORD = "112358"

def get_conn(dbname):
    return psycopg2.connect(
        dbname=dbname,
        user="postgres",
        password=PASSWORD,
        host="localhost"
    )