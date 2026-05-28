# tpch/setup_tpch.py

from pathlib import Path
import subprocess

# ==========================================================
# DATABASE CONFIG
# ==========================================================

DATABASE_NAME="tpch"
USER="postgres"
PASSWORD="112358"
HOST="localhost"
PORT="5432"

# ==========================================================
# TPCH CONFIG
# ==========================================================

SF="1"

BASE_DIR=Path(__file__).resolve().parent.parent

TPCH_DIR=BASE_DIR/"data"/"tpch"
DBGEN_DIR=(TPCH_DIR/"tpch-dbgen")
DBGEN_EXE=(DBGEN_DIR/"dbgen")
DATA_DIR=TPCH_DIR

# ==========================================================
# DBGEN TABLE MAP
# ==========================================================

TABLE_CODES={

    "customer":"C",
    "lineitem":"L",
    "nation":"N",
    "orders":"O",
    "part":"P",
    "partsupp":"S",
    "region":"R",
    "supplier":"S"
}

TABLE_LOAD_ORDER=[

    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem"
]

# ==========================================================
# PIPELINE
# ==========================================================

PIPELINE=[

    "generate_tpch_schema.py",
    "generate_tpch_data_dbgen.py",
    "load_tpch.py",
    "create_index.py"
]

# ==========================================================
# EXECUTE PIPELINE
# ==========================================================

def run_pipeline():

    here=Path(__file__).parent

    for script in PIPELINE:

        script_path=here/script

        print("\n"+"="*70)
        print(f"RUNNING : {script}")
        print("="*70)

        subprocess.run(
            [
                "python",
                str(script_path)
            ],
            check=True
        )


if __name__=="__main__":

    run_pipeline()