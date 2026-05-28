# tpch/generate_tpch_data_dbgen.py

import os
import subprocess

from tpch.setup_tpch import (

    DBGEN_EXE,
    DATA_DIR,
    SF,
    TABLE_LOAD_ORDER,
    TABLE_CODES
)

os.makedirs(
    DATA_DIR,
    exist_ok=True
)

for table in TABLE_LOAD_ORDER:

    outfile=(
        DATA_DIR
        /f"{table}.tbl"
    )

    if outfile.exists():

        print(
            f"{outfile.name} exists"
        )

        continue

    code=TABLE_CODES[table]

    print(
        f"Generating {table}"
    )

    subprocess.run(

        [
            str(DBGEN_EXE),
            "-s",
            str(SF),
            "-T",
            code,
            "-f",
            "-v"
        ],

        cwd=str(DATA_DIR),
        check=True
    )

print(
    "\nGeneration complete."
)