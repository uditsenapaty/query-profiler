# =========================================================
# scripts/generate_tpch_data_dbgen.py
# =========================================================

import os
import subprocess

BASE_DIR = "/home/kiit/query-profiler"
TPCH_DIR = BASE_DIR + "/data/tpch"
DBGEN_EXE = BASE_DIR + "/data/tpch/tpch-dbgen/dbgen"  # adjust path

# Scale factor
SF = 1

tables = ["customer", "lineitem", "orders", "part", "partsupp", "supplier", "nation", "region"]

os.makedirs(TPCH_DIR, exist_ok=True)

for t in tables:
    tbl_file = os.path.join(TPCH_DIR, f"{t}.tbl")
    if os.path.exists(tbl_file):
        print(f"{tbl_file} already exists, skipping.")
        continue
    print(f"Generating {tbl_file}...")
    subprocess.run([DBGEN_EXE, "-s", str(SF), "-T", t[0].upper(), "-f", "-v"], cwd=TPCH_DIR)