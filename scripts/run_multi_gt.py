# ========================
# scripts/run_multi_gt.py
# ========================

from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed
)

from pathlib import Path

import subprocess
import time
import os

import summary_all

import config_gt

# ======================================
# Config
# ======================================

os.environ["GT_RUN_SUFFIX"] = (
    f"_s{config_gt.SYSTEM_WORKERS}q{config_gt.QUERY_WORKERS}"
    if config_gt.SYSTEM_WORKERS != 1
    else f"_s1q{config_gt.QUERY_WORKERS}"
)

import config_gt

# LOG_DIR=Path(
#     "gt_run_logs"
# )

# LOG_DIR.mkdir(
#     exist_ok=True
# )


# =========================================================
# Human-readable duration
# =========================================================

def format_duration(seconds):

    seconds=max(
        int(seconds),
        0
    )

    days,remainder=divmod(
        seconds,
        86400
    )

    hours,remainder=divmod(
        remainder,
        3600
    )

    minutes,seconds=divmod(
        remainder,
        60
    )

    parts=[]

    if days>0:
        parts.append(
            f"{days}d"
        )

    if hours>0 or days>0:
        parts.append(
            f"{hours}h"
        )

    if minutes>0 or hours>0 or days>0:
        parts.append(
            f"{minutes}m"
        )

    parts.append(
        f"{seconds}s"
    )

    return " ".join(parts)


# ======================================
# Worker
# ======================================

def run_query(query_name):

    start=time.time()

    RES_STR = config_gt.get_query_resolution(query_name, config_gt.RUN_METHODS[0])

    query_dir = (
        config_gt.get_main_dir(RES_STR)
        / query_name
    )


    query_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    log_file = (
        query_dir
        / f"{query_name}.log"
    )

    cmd=[

        "python",
        "-u",
        "scripts/build_gt.py",

        "--query",
        query_name

    ]

    # ==================================================
    # logfile append mode
    # ==================================================

    file_exists=log_file.exists()

    with open(

        log_file,

        "a",

        buffering=1,

        encoding="utf-8"

    ) as f:

        # ------------------------------------------------
        # resume separator
        # ------------------------------------------------

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

        # ------------------------------------------------
        # timestamp
        # ------------------------------------------------

        f.write(

            f"START : "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        )

        f.flush()

        # ==================================================
        # environment variables
        # ==================================================

        env=dict(os.environ)
        
        env["GT_RUN_MODE"] = "multi"
        env["GT_LOGFILE_MODE"]="1"
        env["GT_TOTAL_QUERY_JOBS"]=str(len(config_gt.QUERIES))
        env["GT_QUERY_JOB_INDEX"]=str(config_gt.QUERIES.index(query_name)+1)
        env["GT_RUN_SUFFIX"] = os.environ["GT_RUN_SUFFIX"]

        GLOBAL_START_TS=str(time.time())
        env["GT_GLOBAL_START"]=GLOBAL_START_TS

        # ==================================================
        # execute
        # ==================================================

        result=subprocess.run(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
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
            f"{format_duration(elapsed)}\n"
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

    overall_start=time.time()

    print()
    print("="*70)
    print(
        f"Running "
        f"{len(config_gt.QUERIES)} "
        f"queries"
    )
    print(
        f"System workers={config_gt.SYSTEM_WORKERS}"
    )
    print(
        f"Query workers={config_gt.QUERY_WORKERS}"
    )    
    print("="*70)

    futures=[]

    completed=0

    with ProcessPoolExecutor(

        max_workers=config_gt.SYSTEM_WORKERS

    ) as executor:

        for q in config_gt.QUERIES:

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

            completed+=1

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

                f"Time: "
                f"{format_duration(result['time'])}"

            )

            print(
                f"Log: "
                f"{result['log']}"
            )

            # ==================================================
            # overall ETA
            # ==================================================

            elapsed=(
                time.time()
                -
                overall_start
            )

            progress=(
                completed
                /
                len(config_gt.QUERIES)
            )

            if progress>0:

                total_est=(
                    elapsed
                    /
                    progress
                )

                eta=(
                    total_est
                    -
                    elapsed
                )

                print(

                    f"Overall ETA: "
                    f"{format_duration(eta)}"

                )

    total_elapsed=(
        time.time()
        -
        overall_start
    )

    print()

    print("="*70)

    print(
        "ALL QUERY FINISHED"
    )

    print(
        f"Total Time: "
        f"{format_duration(total_elapsed)}"
    )

    print("="*70)

    print()
    print("=" * 70)
    print("SUMMARISING WHOLE RUN")
    print("=" * 70)

    summary_all.run(Path.cwd())

    print()
    print(
        f"WHOLE RUN SUMMARISED at gt_results_sf*/summaries"
    )