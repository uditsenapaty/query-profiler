# =====================
# scripts/run_multi_gt.py
# =====================

from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed
)

from pathlib import Path
import subprocess
import time


# ======================================
# Config
# ======================================

QUERIES=[

    "qt8",
    "qt7",
    "qt11",
    "qt12",
    "qt13",

]

MAX_WORKERS=5


LOG_DIR=Path(
    "gt_run_logs"
)

LOG_DIR.mkdir(
    exist_ok=True
)


# ======================================
# Worker
# ======================================

def run_query(query_name):

    start=time.time()

    log_file=(
        LOG_DIR
        /
        f"{query_name}.log"
    )

    cmd=[

        "python",
        "-u",
        "scripts/build_gt.py",

        "--query",
        query_name

    ]

    # ==================================================
    # append mode
    # ==================================================

    file_exists=log_file.exists()

    with open(

        log_file,

        "a",

        buffering=1,

        encoding="utf-8"

    ) as f:

        # ----------------------------------------------
        # separator between runs
        # ----------------------------------------------

        if file_exists:

            f.write("\n\n")

            f.write(
                "#"*80
                + "\n"
            )

            f.write(
                "RESUMING / RESTARTING RUN\n"
            )

            f.write(
                "#"*80
                + "\n\n"
            )

        else:

            f.write(
                "\n"
                + "="*70
                + "\n"
            )

            f.write(
                f"QUERY : {query_name}\n"
            )

            f.write(
                "="*70
                + "\n\n"
            )

        # ----------------------------------------------
        # timestamp
        # ----------------------------------------------

        f.write(

            f"START : "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        )

        f.flush()

        # ==================================================
        # execute
        # ==================================================

        result=subprocess.run(

            cmd,

            stdout=f,
            stderr=subprocess.STDOUT,

            text=True

        )

        # ==================================================
        # end marker
        # ==================================================

        elapsed=(
            time.time()
            -
            start
        )

        f.write("\n")

        f.write(
            "-"*70
            + "\n"
        )

        f.write(
            f"END : "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        f.write(
            f"ELAPSED : "
            f"{elapsed:.2f} sec\n"
        )

        f.write(
            f"RETURN CODE : "
            f"{result.returncode}\n"
        )

        f.write(
            "-"*70
            + "\n"
        )

        f.flush()

    return {

        "query":
        query_name,

        "returncode":
        result.returncode,

        "time":
        elapsed,

        "log":
        str(log_file)

    }


# ======================================
# Main
# ======================================

if __name__=="__main__":

    print()

    print("="*70)
    print(
        f"Running "
        f"{len(QUERIES)} "
        f"queries"
    )

    print(
        f"Workers={MAX_WORKERS}"
    )
    print("="*70)

    futures=[]

    with ProcessPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        for q in QUERIES:

            futures.append(

                executor.submit(
                    run_query,
                    q
                )

            )


        for future in as_completed(
                futures
        ):

            result=future.result()

            status=(
                "SUCCESS"
                if result[
                    "returncode"
                ]==0
                else "FAILED"
            )

            print()

            print(
                f"[{status}] "
                f"{result['query']}"
            )

            print(
                f"Time:"
                f"{result['time']:.2f}s"
            )

            print(
                f"Log:"
                f"{result['log']}"
            )


    print()
    print("="*70)
    print("ALL FINISHED")
    print("="*70)