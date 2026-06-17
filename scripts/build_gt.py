# =========================================================
# scripts/build_gt.py
# =========================================================


#===========================================================
# CLI Arguements helper for running multiple queries
import argparse
import config_gt
import os

print(f"PID={os.getpid()}")

if os.environ.get("GT_RUN_MODE") == "multi":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--query",
        type=str,
        required=False,
    )

    args = parser.parse_args()

    if args.query:
        config_gt.QUERY = args.query

        config_gt.QUERY_SQL_PATH = (
            config_gt.Path(__file__).resolve().parent
            / "tpch"
            / "queries"
            / f"{config_gt.QUERY}.sql"
        )

        config_gt.QUERY_DIR = config_gt.Path(
            f"{config_gt.QUERY}"
        )
# ===========================================================


import pandas as pd
import bisect
import numpy as np
import time
import json
import sqlparse
from pathlib import Path
from decimal import Decimal
from itertools import product
from datetime import datetime, timedelta
from importlib import import_module
import importlib.util
from tqdm import tqdm
from collections import deque
import config_gt
import re
import psycopg2
import psycopg2.sql as sql
from tpch_query_parser import TPCHQueryParser
import sys

# Import comparator for plan hashing
from tpch.utils.comparator import structural_hash, plan_tree_str


#===========================================================
# Logging setup
import os

LOGFILE_MODE=(
    os.environ.get(
        "GT_LOGFILE_MODE",
        "0"
    )=="1"
)
#===========================================================


#===========================================================
# Multi Query ETA Support
TOTAL_QUERY_JOBS=int(
    os.environ.get(
        "GT_TOTAL_QUERY_JOBS",
        "1"
    )
)

QUERY_JOB_INDEX=int(
    os.environ.get(
        "GT_QUERY_JOB_INDEX",
        "1"
    )
)

GLOBAL_ALL_START=float(
    os.environ.get(
        "GT_GLOBAL_START",
        time.time()
    )
)
#===========================================================


# =========================================================
# Helper for Human-readable time duration
# =========================================================
def format_duration(seconds):

    # =====================================================
    # invalid / NaN
    # =====================================================

    if seconds is None:
        return "?"

    try:

        if np.isnan(seconds):
            return "?"

    except Exception:
        pass

    if np.isinf(seconds):
        return "∞"

    # =====================================================
    # normal formatting
    # =====================================================

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

# ===================================================
# Resolve Sampling Methods to run
# ===================================================
METHODS_TO_RUN=config_gt.get_active_methods()

# =====================================================
# Helper for processing results
# =====================================================
def run_processor(name, processor_dir, arg):

    processor_path=(
        Path(__file__).resolve().parent
        / processor_dir
        / f"{name}.py"
    )

    if not processor_path.exists():
        raise FileNotFoundError(
            f"\nProcessor not found:\n"
            f"{processor_path}"
        )

    spec=importlib.util.spec_from_file_location(
        name,
        processor_path
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"\nFailed loading processor:\n"
            f"{processor_path}"
        )

    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module,"run"):
        module.run(arg)

    else:
        raise RuntimeError(
            f"{name}.py missing run()"
        )

# =====================================================
# Helpers to Resume Script Run
# =====================================================
def run_missing_processors():

    resume_state = load_resume_state()

    completed = set(
        resume_state.get(
            "processors_completed",
            []
        )
    )

    for processor in config_gt.PER_METHOD_PROCESSORS:

        if processor in completed:
            continue

        print()
        print(
            f"[RESUME] Running processor: "
            f"{processor}"
        )

        run_processor(
            processor,
            "per_method_processors",
            config_gt.RESULTS_DIR
        )

        completed.add(processor)

        resume_state[
            "processors_completed"
        ] = sorted(completed)

        save_resume_state(
            resume_state
        )

def get_resume_file():

    return (
        config_gt.RESULTS_DIR
        / "resume_state.json"
    )


def load_resume_state():

    f=get_resume_file()

    if not f.exists():
        return {
            "completed":[],
            "finished":False
        }

    with open(f,"r") as x:
        return json.load(x)


def save_resume_state(state):

    with open(
        get_resume_file(),
        "w"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )


def combo_key(
        combo,
        round_id
):

    combo=list(
        map(
            str,
            combo
        )
    )

    return (
        f"r{round_id}_"
        +
        "|".join(combo)
    )

# =====================================================
# Helper for Json Serialize
# =====================================================

from decimal import Decimal
from datetime import (
    date,
    datetime,
    time as dt_time,
    timedelta
)
from pathlib import Path
from uuid import UUID
import numpy as np
import pandas as pd


def json_serializer(obj):

    # =====================================================
    # Native JSON-safe types
    # =====================================================
    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    # =====================================================
    # Decimal / PostgreSQL NUMERIC
    # =====================================================
    if isinstance(obj, Decimal):
        return float(obj)

    # =====================================================
    # Date / Time
    # =====================================================
    if isinstance(obj, (date, datetime, dt_time)):
        return obj.isoformat()

    if isinstance(obj, timedelta):
        return str(obj)

    # =====================================================
    # UUID
    # =====================================================
    if isinstance(obj, UUID):
        return str(obj)

    # =====================================================
    # pathlib
    # =====================================================
    if isinstance(obj, Path):
        return str(obj)

    # =====================================================
    # NumPy scalar types
    # =====================================================
    if isinstance(obj, np.integer):
        return int(obj)

    if isinstance(obj, np.floating):
        return float(obj)

    if isinstance(obj, np.bool_):
        return bool(obj)

    # =====================================================
    # NumPy arrays
    # =====================================================
    if isinstance(obj, np.ndarray):
        return obj.tolist()

    # =====================================================
    # Pandas NA / Timestamp
    # =====================================================
    if pd.isna(obj):
        return None

    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()

    if isinstance(obj, pd.Timedelta):
        return str(obj)

    # =====================================================
    # Sets / tuples
    # =====================================================
    if isinstance(obj, (set, tuple)):
        return list(obj)

    # =====================================================
    # Bytes
    # =====================================================
    if isinstance(obj, bytes):
        return obj.decode(
            "utf-8",
            errors="replace"
        )

    # =====================================================
    # Generic object fallback
    # =====================================================
    try:
        return vars(obj)

    except Exception:
        return str(obj)
    
# =========================================================
# Selectivity cache (table.column -> sorted values)
# =========================================================
SELECTIVITY_CACHE={}

# =========================================================
# Helper for Connecting to tpch database
# =========================================================

def get_conn(dbname):
    return psycopg2.connect(
        dbname=dbname,
        user=config_gt.USER,
        password=config_gt.PASSWORD,
        host=config_gt.HOST,
    )


# =======================================================
# Helper for Robust Cardinality compute
# (Predicate surviving) for Picasso Queries Q(5,7,8,10,16)
# =======================================================
def make_count_query(sql_query):

    # -----------------------------------------
    # remove -- comments
    # -----------------------------------------
    q = re.sub(
        r'--.*?$',
        '',
        sql_query,
        flags=re.M
    ).strip().rstrip(";")

    # -----------------------------------------
    # replace outer SELECT ... FROM
    # -----------------------------------------
    m = re.search(
        r'(?is)\bselect\b',
        q
    )

    if m is None:
        raise RuntimeError("No SELECT found")

    depth = 0
    from_pos = None

    i = m.end()

    while i < len(q):

        c = q[i]

        if c == '(':
            depth += 1

        elif c == ')':
            depth -= 1

        elif depth == 0:

            if q[i:i+4].upper() == "FROM":

                before = (
                    i == 0
                    or
                    not q[i-1].isalnum()
                )

                after = (
                    i+4 == len(q)
                    or
                    not q[i+4].isalnum()
                )

                if before and after:

                    from_pos = i
                    break

        i += 1

    if from_pos is None:
        raise RuntimeError(
            "Could not locate top-level FROM"
        )

    q = (
        "SELECT COUNT(*) "
        + q[from_pos:]
    )

    # -----------------------------------------
    # remove top-level GROUP BY / ORDER BY
    # -----------------------------------------
    depth = 0
    cut_pos = len(q)

    i = 0

    while i < len(q):

        c = q[i]

        if c == '(':
            depth += 1

        elif c == ')':
            depth -= 1

        elif depth == 0:

            s = q[i:].upper()

            if s.startswith("GROUP BY"):
                cut_pos = i
                break

            if s.startswith("ORDER BY"):
                cut_pos = i
                break

        i += 1

    q = q[:cut_pos].strip()

    return q

# ==========================================================================
# Find Minimum value for each axis for non 0 predicate surviving cardinality
# ==========================================================================
def find_min_positive_point_nd(
        card_fn,
        ndim,
        eps=1e-9,
        max_sel=1.0,
        tol=1e-9):

    # ---------- diagonal expansion ----------
    lo=0.0
    hi=eps

    while hi<=max_sel:

        if card_fn([hi]*ndim)>0:
            break

        lo=hi
        hi*=2

    if hi>max_sel:
        return None

    # ---------- binary search diagonal ----------
    while hi-lo>tol:

        mid=(lo+hi)/2

        if card_fn([mid]*ndim)>0:
            hi=mid
        else:
            lo=mid

    s=[hi]*ndim

    # ---------- coordinate descent ----------
    improved=True

    while improved:

        improved=False

        for axis in range(ndim):

            lo=0.0
            hi=s[axis]

            while hi-lo>tol:

                mid=(lo+hi)/2

                trial=s.copy()
                trial[axis]=mid

                if card_fn(trial)>0:
                    hi=mid
                else:
                    lo=mid

            if hi<s[axis]:
                s[axis]=hi
                improved=True

    return s,card_fn(s)

# =========================================================
# Helper functions for file storage
# =========================================================
def sanitize(v):
    s = str(v)
    s = s.replace("/", "_")
    s = s.replace(":", "_")
    s = s.replace(" ", "_")
    s = s.replace(".", "p")
    return s[:50]

def make_combo_filename(combo):
    """Convert combo tuple to filename string."""
    return "_".join([
        f"x{i+1}_{sanitize(v)}"
        for i, v in enumerate(combo)
    ])


# =========================================================
# Helper for Plan traversal
# =========================================================
def traverse_plan(node, depth=0):
    ops = []
    node_type = node.get("Node Type", "UNKNOWN")
    ops.append(node_type)
    max_depth = depth

    join_count = 0
    scan_count = 0
    hash_count = 0
    sort_count = 0
    aggregate_count = 0
    parallel_count = 0

    if "Join" in node_type or node_type == "Nested Loop":
        join_count += 1
    if "Scan" in node_type:
        scan_count += 1
    if "Hash" in node_type:
        hash_count += 1
    if "Sort" in node_type:
        sort_count += 1
    if "Aggregate" in node_type:
        aggregate_count += 1
    if "Parallel" in node_type:
        parallel_count += 1

    shared_hit = node.get("Shared Hit Blocks", 0)
    shared_read = node.get("Shared Read Blocks", 0)
    shared_dirtied = node.get("Shared Dirtied Blocks", 0)
    temp_read = node.get("Temp Read Blocks", 0)
    temp_written = node.get("Temp Written Blocks", 0)

    for child in node.get("Plans", []):
        (
            child_ops,
            child_depth,
            child_join,
            child_scan,
            child_hash,
            child_sort,
            child_agg,
            child_parallel,
            child_hit,
            child_read,
            child_dirtied,
            child_temp_read,
            child_temp_written
        ) = traverse_plan(child, depth + 1)

        ops.extend(child_ops)
        max_depth = max(max_depth, child_depth)
        join_count += child_join
        scan_count += child_scan
        hash_count += child_hash
        sort_count += child_sort
        aggregate_count += child_agg
        parallel_count += child_parallel
        shared_hit += child_hit
        shared_read += child_read
        shared_dirtied += child_dirtied
        temp_read += child_temp_read
        temp_written += child_temp_written

    return (
        ops, max_depth,
        join_count, scan_count, hash_count, sort_count, aggregate_count, parallel_count,
        shared_hit, shared_read, shared_dirtied, temp_read, temp_written
    )

# =========================================================
# Helper for Safe parameter substitution
# =========================================================
def substitute_params(sql_text, combo):

    result = sql_text

    for i, value in enumerate(combo):

        param = f":p{i+1}"

        # ---------------------------------------------
        # strings / dates
        # ---------------------------------------------

        if isinstance(value, str):

            replacement = "'" + value.replace("'", "''") + "'"

        elif hasattr(value, "isoformat"):

            replacement = "'" + value.isoformat() + "'"

        # ---------------------------------------------
        # numeric
        # ---------------------------------------------

        else:

            replacement = str(value)

        result = result.replace(param, replacement)

    return result

# =========================================================
# Helper to Resolve unqualified column
# =========================================================
def resolve_column(
    conn,
    column_expr,
    table_aliases
):

    # -----------------------------------------------------
    # Qualified
    # -----------------------------------------------------

    if "." in column_expr:

        alias, column = column_expr.split(".", 1)

        if alias not in table_aliases:

            raise RuntimeError(
                f"Unknown alias: {alias}"
            )

        return (
            table_aliases[alias],
            column
        )

    # -----------------------------------------------------
    # Unqualified
    # -----------------------------------------------------

    column = column_expr

    cur = conn.cursor()

    cur.execute("""
        SELECT table_name
        FROM information_schema.columns
        WHERE column_name = %s
    """, (column,))

    matches = [
        r[0]
        for r in cur.fetchall()
    ]

    cur.close()

    query_tables = set(
        table_aliases.values()
    )

    matches = [
        t for t in matches
        if t in query_tables
    ]

    if len(matches) == 0:

        raise RuntimeError(
            f"Could not resolve column: {column}"
        )

    if len(matches) > 1:

        raise RuntimeError(
            f"Ambiguous column: {column}"
        )

    return matches[0], column
    
# =====================================================
# Helper to find Methods using target selectivity space
# =====================================================
def method_uses_target_selectivities(method):

    cfg=config_gt.METHOD_CONFIGS[
        method
    ]

    sampler_name=cfg[
        "sampler"
    ].lower()

    # any sampler based on percentile/selectivity
    return (
        "selectivity"
        in sampler_name
    )

# =========================================================
# Helper for axis selectivity (1 scan + BINARY SEARCH)
# =========================================================
def get_axis_selectivity(
    conn,
    table,
    column,
    value
):

    cache_key=(
        table,
        column
    )

    # Build cache once
    if cache_key not in SELECTIVITY_CACHE:

        tqdm.write(
            f"Caching {table}.{column}"
        )

        # estimate row count
        count_cur=conn.cursor()

        count_cur.execute(
            f"""
            SELECT COUNT({column})
            FROM {table}
            """
        )
        total_rows=count_cur.fetchone()[0]

        count_cur.close()

        # stream sorted values
        cur=conn.cursor(
            name=f"cursor_{table}_{column}"
        )
        cur.itersize=100000

        cur.execute(
            f"""
            SELECT {column}
            FROM {table}
            WHERE {column} IS NOT NULL
            ORDER BY {column}
            """
        )

        vals=[]

        pbar=tqdm(
            total=total_rows,
            desc=(
                f"Cache "
                f"{table}.{column}"
            ),
            unit="row",
            disable=LOGFILE_MODE,
        )

        while True:

            batch=cur.fetchmany(
                100000
            )
            if not batch:
                break

            vals.extend(
                r[0]
                for r in batch
            )
            pbar.update(
                len(batch)
            )
        pbar.close()

        cur.close()

        SELECTIVITY_CACHE[
            cache_key
        ]=vals

        tqdm.write(
            f"Cached {len(vals):,} values"
        )

    vals=SELECTIVITY_CACHE[cache_key]
    total=len(vals)
    if total==0:
        return np.nan

    # Exact values : P(X<=value)
    idx=bisect.bisect_right(
        vals,
        value
    )
    sel=idx/total

    return sel

# =========================================================
# Multi Dimension Plan change detection (using plan_hash)
# =========================================================
def count_plan_changes_nd(plan_grid):
    """
    Count plan changes across all neighboring cells
    in an N-dimensional parameter grid.
    """

    plan_grid = np.array(plan_grid, dtype=object)

    total_changes = 0

    for axis in range(plan_grid.ndim):

        rolled = np.roll(plan_grid, shift=1, axis=axis)

        slicer = [slice(None)] * plan_grid.ndim
        slicer[axis] = slice(1, None)

        current = plan_grid[tuple(slicer)]
        previous = rolled[tuple(slicer)]

        diff = current != previous

        total_changes += int(np.sum(diff))

    return total_changes

# =========================================================
# Per-axis Plan Change Mask
# =========================================================

def compute_axis_plan_changes(plan_grid):

    masks = []

    for axis in range(plan_grid.ndim):

        mask = np.zeros(
            plan_grid.shape,
            dtype=bool
        )

        slicer_curr = [slice(None)] * plan_grid.ndim
        slicer_prev = [slice(None)] * plan_grid.ndim

        slicer_curr[axis] = slice(1, None)
        slicer_prev[axis] = slice(0, -1)

        curr = plan_grid[tuple(slicer_curr)]
        prev = plan_grid[tuple(slicer_prev)]

        diff = curr != prev

        mask[tuple(slicer_curr)] = diff

        masks.append(mask)

    return masks

# =========================================================
# Adjacent ND Q-error Per Axis
# =========================================================
def compute_axis_qerrors(runtime_grid):

    runtime_grid = np.array(runtime_grid)

    qerr_maps = []

    for axis in range(runtime_grid.ndim):

        qmap = np.full(
            runtime_grid.shape,
            np.nan
        )

        slicer_curr = [slice(None)] * runtime_grid.ndim
        slicer_prev = [slice(None)] * runtime_grid.ndim

        slicer_curr[axis] = slice(1, None)
        slicer_prev[axis] = slice(0, -1)

        curr = runtime_grid[tuple(slicer_curr)]
        prev = runtime_grid[tuple(slicer_prev)]

        q = np.maximum(
            curr / np.maximum(prev, 1e-9),
            prev / np.maximum(curr, 1e-9)
        )

        qmap[tuple(slicer_curr)] = q

        qerr_maps.append(qmap)

    return qerr_maps


# =========================================================
# WHOLE SCRIPT TIMER
# =========================================================
whole_script_start_wall = datetime.now()
whole_script_start_perf = time.time()


# =========================================================
# LOOP FOR EACH METHOD START HERE !!
# =========================================================
for CURRENT_METHOD in METHODS_TO_RUN:

    print()
    print("="*70)
    print(f"RUNNING METHOD: "f"{CURRENT_METHOD}")    
    print("="*70)

    # =======================================================================================
    # CAPTURE EXECUTION START TIME
    script_start_wall = datetime.now()
    script_start_perf = time.time()

    print("\n=================================================")
    print("SCRIPT START")
    print("=================================================")
    print(f"Start Time : {script_start_wall.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=================================================\n")
    # =======================================================================================


    # =========================================================
    # STABILITY CONFIGURATIONS
    # =========================================================
    conn = get_conn(config_gt.DATABASE_NAME)

    setup_cur = conn.cursor()
    setup_cur.execute("SET jit = off;")
    setup_cur.execute(f"SET max_parallel_workers_per_gather = {config_gt.QUERY_WORKERS};")
    setup_cur.execute("SET track_io_timing = on;")
    setup_cur.execute("SET enable_partitionwise_join = off;")
    setup_cur.execute("SET enable_partitionwise_aggregate = off;")
    setup_cur.execute("SET enable_memoize = off;")
    setup_cur.execute("SET enable_async_append = off;")
    setup_cur.execute("SET geqo = off;")
    setup_cur.execute("SET work_mem = '256MB';")
    setup_cur.close()


    # Switch Active method (config_gt.SAMPLING_METHOD=CURRENT_METHOD)
    DEFAULT_RESOLUTION,\
    PARAM_RESOLUTIONS=(
        config_gt.get_resolution_map(CURRENT_METHOD)
    )
    print(f"Sampler: {CURRENT_METHOD} (default resolution={DEFAULT_RESOLUTION})")

    sampler=import_module(
        "samplers."
        +
        config_gt.SAMPLER_FILES[
            CURRENT_METHOD
        ]
    )

    # =========================================================
    # Load SQL query and parse with sqlparse
    # =========================================================
    with open(config_gt.QUERY_SQL_PATH, "r") as f:
        sql_text = f.read()

    # =========================================================
    # Robust AST SQL parsing
    # =========================================================
    parser = TPCHQueryParser()
    parsed = parser.parse(sql_text)
    print("\nParsed query successfully")

    # =========================================================
    # Table aliases
    # =========================================================
    table_aliases = parsed["aliases"]

    # =========================================================
    # Parameter extraction and robust filename setup
    # =========================================================
    param_columns = [
        p.replace(":", "")
        for p in parsed["parameters"]
    ]

    param_columns = sorted(
        param_columns,
        key=lambda x: int(x[1:])
    )

    RES_STR = config_gt.get_resolution_string(
        CURRENT_METHOD,
        len(param_columns)
    )

    config_gt.set_main_dir(RES_STR)
    config_gt.set_method_paths(CURRENT_METHOD, RES_STR)

    config_gt.ensure_paths()


    # =====================================================
    # Resume state
    # =====================================================
    resume_state=load_resume_state()

    if resume_state.get("finished",False):

        print()
        print("="*70)
        print(f"{CURRENT_METHOD} GT already completed.")
        print("Checking processors...")
        print("="*70)

        run_missing_processors()
        continue


    completed_runs=set(
        resume_state[
            "completed"
        ]
    )

    resume_state["completed"]=list(
        completed_runs
    )

    save_resume_state(
        resume_state
    )

    print(
        f"Found "
        f"{len(completed_runs)} "
        f"completed runs"
    )

    print(f"Output directories ready:\n  {config_gt.PLANS_DIR}\n  {config_gt.PLAN_TREES_DIR}\n  {config_gt.TRACES_DIR}")


    # =========================================================
    # Parameter → column mapping
    # =========================================================
    param_to_column = {}

    for pred in parsed["predicates"]:

        cols = pred["columns"]
        params = pred["parameters"]

        if len(cols) == 0:
            continue

        if len(params) == 0:
            continue

        # use first column
        col = cols[0]

        for p in params:

            p_clean = p.replace(":", "")

            if p_clean not in param_to_column:
                param_to_column[p_clean] = col

    print("Detected parameters:", param_columns)
    print("Parameter mapping:", param_to_column)
    print("Table aliases:", table_aliases)


    # =========================================================
    # Compute total base relation size for selectivity
    # =========================================================
    query_tables = sorted(
        list(
            set(
                table_aliases.values()
            )
        )
    )

    total_relation_rows = 0

    cur = conn.cursor()

    for table in query_tables:

        cur.execute(
            f"SELECT COUNT(*) FROM {table}"
        )

        cnt = cur.fetchone()[0]

        total_relation_rows += cnt

    cur.close()

    print()
    print("=================================================")
    print("TABLES INFO")
    print("=================================================")
    print(f"Query tables: {query_tables}")
    print(f"Total rows across tables: "f"{total_relation_rows:,}")
    print("=================================================\n")



    # ==================================================================
    # Collect all values for each predicate
    # ==================================================================
    param_values_dict={}
    actual_axis_selectivities={}

    use_targets=method_uses_target_selectivities(
        CURRENT_METHOD
    )

    # build the COUNT(*) version once
    count_query_template = make_count_query(sql_text)

    # cache sorted values for each parameter column
    sorted_column_values = {}

    for param in param_columns:
        column_expr = param_to_column[param]
        real_table, column = resolve_column(conn, column_expr, table_aliases)

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {column}
            FROM {real_table}
            WHERE {column} IS NOT NULL
            ORDER BY {column}
            """
        )
        sorted_column_values[param] = [r[0] for r in cur.fetchall()]
        cur.close()
    # ==================================================================

    count_cur = conn.cursor()

    def card_fn(selectivities):
        values = []
        for d, param in enumerate(param_columns):
            vals = sorted_column_values[param]
            idx = int(selectivities[d] * (len(vals) - 1))
            idx = max(0, min(idx, len(vals) - 1))
            values.append(vals[idx])

        query = substitute_params(count_query_template, values)
        count_cur.execute(query)
        return count_cur.fetchone()[0]

    boundary_sels, boundary_count = find_min_positive_point_nd(
        card_fn,
        ndim=len(param_columns)
    )

    axis_lower_bounds = {}
    for d, param in enumerate(param_columns):
        vals = sorted_column_values[param]
        idx = int(boundary_sels[d] * (len(vals) - 1))
        idx = max(0, min(idx, len(vals) - 1))
        axis_lower_bounds[param] = vals[idx]

    count_cur.close()

    print("="*70)
    print("ADJUSTMENT TO ENSURE NON-ZERO JOINT CARDINALITY AT INITIAL BOUNDARY POINTS")
    print("="*70)
    print("initial_axes_sels:", boundary_sels)
    print("initial_point_count_rows:", boundary_count)
    print("initial_axis_lower_bounds:", axis_lower_bounds)
    print("="*70)

    print()

    print("="*50)
    print("PARAMETER PREPARATION")
    print("="*50)

    for param in param_columns:

        column_expr=param_to_column[param]

        real_table,column=resolve_column(
            conn,
            column_expr,
            table_aliases
        )

        resolution=PARAM_RESOLUTIONS.get(
            param,
            DEFAULT_RESOLUTION
        )

        print()
        print(
            f"[{param}] "
            f"Sampling..."
        )

        values=sampler.sample(
            conn,
            real_table,
            column,
            resolution,
            lower_bound=axis_lower_bounds[param]
        )

        param_values_dict[param]=values

        print(
            f"[{param}] "
            f"{len(values)} samples "
            f"[{values[0]} → {values[-1]}]"
        )


        # ====================================
        # use sampler targets directly
        # ====================================

        if use_targets:

            target_sels=(
                sampler.selectivities(
                    resolution
                )
            )

            if len(target_sels)!=len(values):

                raise RuntimeError(
                    f"{CURRENT_METHOD}: "
                    f"sample/selectivity mismatch "
                    f"for {param}"
                )
            
            actual_axis_selectivities[param]=target_sels

            print(
                f"[{param}] "
                f"Using target selectivities"
            )

        else:

            actual_sels=[]

            print(
                f"[{param}] "
                f"Computing actual selectivities"
            )

            for v in tqdm(
                values,
                desc=f"{param} selectivities",
                unit="point",
                leave=False,
                disable=LOGFILE_MODE,
            ):

                s=get_axis_selectivity(
                    conn,
                    real_table,
                    column,
                    v
                )

                actual_sels.append(s)

            actual_axis_selectivities[param]=actual_sels

    print()
    print("="*50)
    print("Parameter preparation complete")
    print("="*50)

    for i, col in enumerate(param_columns):
        print(f"Parameter [{col}] has {len(param_values_dict[col])} distinct values")

    # =========================================================
    # Prepare all combinations of parameters
    # =========================================================
    all_combinations = list(product(*param_values_dict.values()))

    shape=[
        len(param_values_dict[p])
        for p in param_columns
    ]

    if len(all_combinations) > config_gt.MAX_COMBINATIONS:
        raise RuntimeError(
            f"Too many combinations: {len(all_combinations)}"
        )

    print(f"\nTotal combinations to profile: {len(all_combinations)}")

    # =========================================================
    # Persistent cache for 3 runs per parameter combination
    # =========================================================
    all_temp_runs = {combo: [] for combo in all_combinations}

    # =========================================
    # Rebuild temp runs from trace files
    # =========================================
    for combo in all_combinations:

        combo_filename=make_combo_filename(combo)

        trace_path=(
            config_gt.TRACES_DIR
            /
            f"{combo_filename}_trace.json"
        )

        if not trace_path.exists():
            continue

        try:

            with open(trace_path,"r") as f:
                trace_data=json.load(f)

            runs=trace_data.get(
                "runs",
                []
            )

            rebuilt=[]

            for r in runs:

                rebuilt.append({

                    "runtime":
                    r["runtime"],

                    "round":
                    r["round"],

                    "explain":
                    r["full_explain"]

                })

            all_temp_runs[combo]=rebuilt

        except Exception as e:

            print(
                f"Failed rebuilding trace:"
                f"{trace_path}"
            )

            print(e)

    # =========================================
    # Validate rebuilt runs
    # =========================================
    valid_completed_runs=set()

    for combo in all_combinations:

        runs=all_temp_runs[combo]

        for r in runs:

            key=combo_key(
                combo,
                r["round"]-1
            )

            valid_completed_runs.add(key)


    # ==========================================================================
    # Merge trace recovery with resume file as resume_state is source of truth
    # ==========================================================================
    completed_runs |= valid_completed_runs

    resume_state["completed"]=list(
        completed_runs
    )

    save_resume_state(
        resume_state
    )

    print(
        f"Validated "
        f"{len(completed_runs)}/{len(all_combinations)*config_gt.TOTAL_ROUNDS} "
        f"completed runs from traces"
    )

    # =========================================================
    # GLOBAL ETAs
    # =========================================================
    method_start=time.time()
    recent_times=deque(maxlen=200)

    # ====================================================================================
    # Prepare cache for all query combinations with sampled predicate values
    print()
    print("Preparing cache for all query combinations with sampled predicate values...")

    combo_queries={}

    for combo in tqdm(
        all_combinations,
        desc="Caching queries",
        unit="query",
        disable=LOGFILE_MODE,
    ):
        combo_queries[combo]=(

            substitute_params(
                sql_text,
                combo
            )
        )
    print("Caching sampled queries complete")
    # ====================================================================================


    # ====================================================================================
    # Compute predicate surviving cardinality for each sampled query
    print()
    print("Preparing cache for predicate surviving cardinality for each sampled query...")

    combo_row_counts = {}

    count_cur = conn.cursor()

    for combo in tqdm(
        all_combinations,
        desc="Computing cardinalities",
        unit="combo",
        disable=LOGFILE_MODE,
    ):

        try:

            count_cur.execute(
                make_count_query(
                    combo_queries[combo]
                )
            )

            combo_row_counts[combo] = (
                count_cur.fetchone()[0]
            )

        except Exception as e:

            print(f"COUNT query failed for {combo}")
            print(e)

            conn.rollback()
            combo_row_counts[combo] = 0

    count_cur.close()

    max_filtered_cardinality = max(
        combo_row_counts.values(),
        default=1
    )

    print(f"Max output cardinality: {max_filtered_cardinality:,}")
    print()
    # ====================================================================================

   
    # =========================================================
    # LOGS
    global_start = time.time()
    total_queries = config_gt.TOTAL_ROUNDS * len(all_combinations)
    completed_queries = len(completed_runs)
    # =========================================================


    # ==============================================================
    # LOOP FOR EACH ROUND START HERE !!
    # Run all queries config_gt.TOTAL_ROUNDS times (discard warmup)
    # ==============================================================
    for round_id in range(config_gt.TOTAL_ROUNDS):
        # FOR STABILITY
        round_setup = conn.cursor()
        round_setup.execute("DISCARD PLANS;")
        round_setup.close()


        print(f"\n--- Round {round_id + 1} ---\n")

        combo_pbar=tqdm(
            all_combinations,
            desc=(
                f"{CURRENT_METHOD} "
                f"Round {round_id+1}"
            ),
            unit="combo",
            disable=LOGFILE_MODE,
        )

        for combo in combo_pbar:

            key=combo_key(combo,round_id)

            # =========================
            # skip completed
            # =========================
            if key in completed_runs:
                continue
            
            query_to_run = combo_queries[combo]

            cur = conn.cursor()

            try:

                cur.execute(
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query_to_run}"
                )
                explain_data = cur.fetchone()[0][0]

            except Exception as e:

                print(f"FAILED combo={combo}")
                print(e)
                conn.rollback()
                cur.close()
                continue

            cur.close()

            execution_time = explain_data["Execution Time"]

            # ======================================================
            # LOGS
            completed_queries+=1
            
            recent_times.append(execution_time)
            avg_ms=sum(recent_times)/max(len(recent_times),1)

            # METHOD ETA
            method_elapsed_sec=(time.time()-method_start)
            method_progress=(completed_queries/total_queries)

            if method_progress>0:
                method_total_est=(method_elapsed_sec/method_progress)
                method_eta_sec=(method_total_est-method_elapsed_sec)
            else:
                method_eta_sec=np.nan

            # WHOLE QUERY ETA
            query_elapsed_sec=(time.time()-script_start_perf)
            methods_done = METHODS_TO_RUN.index(CURRENT_METHOD)
            method_fraction = (completed_queries/total_queries)
            query_progress = (methods_done+method_fraction) / len(METHODS_TO_RUN)

            if query_progress>0:
                query_total_est=(query_elapsed_sec/query_progress)
                query_eta_sec=(query_total_est-query_elapsed_sec)
            else:
                query_eta_sec=np.nan

            # ALL MULTI QUERY ETA
            queries_completed=(QUERY_JOB_INDEX-1)
            overall_progress=((queries_completed+query_progress)/TOTAL_QUERY_JOBS)
            all_elapsed_sec=(time.time()-GLOBAL_ALL_START)

            if overall_progress>0:
                all_total_est=(all_elapsed_sec / overall_progress)
                all_queries_eta_sec=(all_total_est - all_elapsed_sec)
            else:
                all_queries_eta_sec=np.nan

            if not LOGFILE_MODE:
                combo_pbar.set_postfix({
                    # "rt_ms":
                    # f"{execution_time:.1f}",
                    "Elapsed-> "
                    # "m":
                    # format_duration(method_elapsed_sec),
                    "q":
                    format_duration(query_elapsed_sec),
                    # "all":
                    # format_duration(all_elapsed_sec),
                    "ETAs-> "
                    "m":
                    format_duration(method_eta_sec),
                    "q":
                    format_duration(query_eta_sec),
                    # "all":
                    # format_duration(all_queries_eta_sec),
                })
            else:
                # clean logfile progress
                if (
                    completed_queries % 100 == 0
                    or
                    completed_queries == total_queries
                ):

                    print(
                        f"["
                        f"{completed_queries}"
                        f"/"
                        f"{total_queries}"
                        f"] "
                        # f"rt_ms="
                        # f"{execution_time:.2f} "
                        "Elapsed-> "
                        "m:"
                        f"{format_duration(method_elapsed_sec)} ",
                        "q:"
                        f"{format_duration(query_elapsed_sec)} "
                        "all:"
                        f"{format_duration(all_elapsed_sec)} "
                        "ETAs-> "
                        "m:"
                        f"{format_duration(method_eta_sec)} "
                        "q:"
                        f"{format_duration(query_eta_sec)} "
                        # "all:"
                        # f"{format_duration(all_queries_eta_sec)} "
                    )
            # ======================================================

            if round_id >= config_gt.WARMUP_ROUND:
                all_temp_runs[combo].append({
                    "runtime": execution_time,
                    "explain": explain_data,
                    "round": round_id + 1
                })

            # =========================
            # SAVE PROGRESS IMMEDIATELY
            # =========================

            completed_runs.add(
                key
            )

            resume_state[
                "completed"
            ]=list(
                completed_runs
            )

            save_resume_state(
                resume_state
            )

        print(f"Completed round {round_id + 1}/{config_gt.TOTAL_ROUNDS}")

    print("\nFinished profiling all rounds")


    # =========================================================
    # Build rows for DataFrame
    # =========================================================
    value_to_idx={}

    for p in param_columns:

        value_to_idx[p]={
            v:i
            for i,v in enumerate(
                param_values_dict[p]
            )
        }

    rows = []

    for combo_idx, combo in enumerate(all_combinations):

        temp_runs = all_temp_runs[combo]

        if len(temp_runs) == 0:

            print(
                f"Skipping failed combo:{combo}"
            )
            continue


        runtimes = [
            r["runtime"]
            for r in temp_runs
        ]

        runtime_mean = np.mean(runtimes)
        runtime_std  = np.std(runtimes)

        best_run = min(
            temp_runs,
            key=lambda r: abs(r["runtime"] - runtime_mean)
        )

        explain_data = best_run["explain"]
        plan = explain_data["Plan"]


        # =====================================================
        # Selectivity
        # =====================================================
        count_rows = combo_row_counts[combo]

        selectivity_axes=[]

        for param,v in zip(param_columns,combo):

            idx=value_to_idx[param][v]
            selectivity_axes.append(actual_axis_selectivities[param][idx])

        # observed joint selectivity (proxy)
        joint_sel = (count_rows /max(max_filtered_cardinality,1))
        joint_sel = min(max(joint_sel,0.0),1.0)

        # =====================================================
        # Plan metrics
        # =====================================================
        root_node = plan.get("Node Type")
        startup_cost = plan.get("Startup Cost")
        total_cost = plan.get("Total Cost")
        plan_rows = plan.get("Plan Rows")
        rows_ret = int(plan.get("Actual Rows", 0))

        if rows_ret is None:
            rows_ret = 0
        rows_ret = int(float(rows_ret))

        # Fallback for DISTINCT mode
        if combo_row_counts[combo] is None:
            combo_row_counts[combo] = rows_ret
            count_rows = rows_ret

        workers_planned = plan.get("Workers Planned", 0)
        workers_launched = plan.get("Workers Launched", 0)
        execution_time = explain_data["Execution Time"]
        planning_time = explain_data.get("Planning Time", 0)

        (
            ops,
            max_depth,
            join_count, scan_count, hash_count, sort_count, aggregate_count, parallel_count,
            shared_hit, shared_read, shared_dirtied, temp_read, temp_written
        ) = traverse_plan(plan)

        node_count = len(ops)
        plan_signature = "->".join(ops)

        # =========================================================
        # Compute plan hash using comparator
        # =========================================================
        plan_hash = structural_hash(explain_data)

        # =========================================================
        # Generate human-readable tree
        # =========================================================
        plan_tree = plan_tree_str(explain_data)

        # =========================================================
        # Save plan JSON file
        # =========================================================
        combo_filename = make_combo_filename(combo)
        plan_json_path = config_gt.PLANS_DIR / f"{combo_filename}.json"
        with open(plan_json_path, "w") as f:
            json.dump(explain_data, f, indent=2, default=json_serializer)
        rel_plan_json_path = f"plans/{combo_filename}.json"

        # =========================================================
        # Save plan tree file
        # =========================================================
        plan_tree_path = config_gt.PLAN_TREES_DIR / f"{combo_filename}.txt"
        with open(plan_tree_path, "w") as f:
            f.write(plan_tree)
        rel_plan_tree_path = f"plan_trees/{combo_filename}.txt"

        # =========================================================
        # Save trace file (all measured runs)
        # =========================================================
        trace_data = {
            "combo": list(combo),
            "count_rows": count_rows,
            "param_names": param_columns,
            "MEASURED_ROUNDS": config_gt.MEASURED_ROUNDS,
            "runs": []
        }
        for run in temp_runs:
            run_plan = run["explain"]["Plan"]
            run_ops = traverse_plan(run_plan)[0]
            run_plan_signature = "->".join(run_ops)
            run_plan_hash = structural_hash(run["explain"])
            run_shared_hit = run_plan.get("Shared Hit Blocks", 0)
            run_shared_read = run_plan.get("Shared Read Blocks", 0)
            run_shared_dirtied = run_plan.get("Shared Dirtied Blocks", 0)
            run_temp_read = run_plan.get("Temp Read Blocks", 0)
            run_temp_written = run_plan.get("Temp Written Blocks", 0)

            trace_data["runs"].append({
                "round": run["round"],
                "runtime": run["runtime"],
                "execution_time": run["explain"]["Execution Time"],
                "planning_time": run["explain"].get("Planning Time", 0),
                "count_rows": count_rows,
                "plan_rows": run_plan.get("Plan Rows"),
                "rows_ret": run_plan.get("Actual Rows"),
                "startup_cost": run_plan.get("Startup Cost"),
                "total_cost": run_plan.get("Total Cost"),
                "workers_planned": run_plan.get("Workers Planned", 0),
                "workers_launched": run_plan.get("Workers Launched", 0),
                "shared_hit_blocks": run_shared_hit,
                "shared_read_blocks": run_shared_read,
                "shared_dirtied_blocks": run_shared_dirtied,
                "temp_read_blocks": run_temp_read,
                "temp_written_blocks": run_temp_written,
                "plan_signature": run_plan_signature,
                "plan_hash": run_plan_hash,
                "full_explain": run["explain"],
                "selectivity_axes": selectivity_axes,
                "joint_sel":joint_sel,
            })

        trace_path = config_gt.TRACES_DIR / f"{combo_filename}_trace.json"
        with open(trace_path, "w") as f:
            json.dump(trace_data, f, indent=2, default=json_serializer)
        rel_trace_path = f"traces/{combo_filename}_trace.json"

        # =========================================================
        # Compute convenience metrics
        # =========================================================
        shared_read_total = shared_hit + shared_read
        shared_hit_ratio = shared_hit / shared_read_total if shared_read_total > 0 else 1.0
        temp_total_blocks = temp_read + temp_written

        rows.append([
            *combo,  # x1, x2, x3...
            runtime_mean,
            runtime_std,
            count_rows,
            planning_time,
            execution_time,
            root_node,
            startup_cost,
            total_cost,
            plan_rows,
            rows_ret,
            shared_hit,
            shared_read,
            shared_dirtied,
            shared_read_total,
            shared_hit_ratio,
            temp_read,
            temp_written,
            temp_total_blocks,
            workers_planned,
            workers_launched,
            node_count,
            max_depth,
            join_count,
            scan_count,
            hash_count,
            sort_count,
            aggregate_count,
            parallel_count,
            plan_signature,
            plan_hash,
            rel_plan_json_path,
            rel_plan_tree_path,
            rel_trace_path,
            selectivity_axes,
            joint_sel,
        ])


    # Check for combos Processed combos check
    processed_combos=len(rows)
    expected_combos=len(all_combinations)

    if processed_combos==expected_combos:

        print(
            f"\nProcessed all "
            f"{processed_combos:,} combos\n"
        )

    else:

        print(
            f"\nWARNING: "
            f"processed "
            f"{processed_combos:,}/"
            f"{expected_combos:,} combos\n"
        )


    # =========================================================
    # Build DataFrame
    # =========================================================
    columns = [f"x{i+1}" for i in range(len(param_columns))] + [
        "runtime_mean",
        "runtime_std",
        "count_rows",
        "planning_time",
        "execution_time",
        "root_node",
        "startup_cost",
        "total_cost",
        "plan_rows",
        "rows_ret",
        "shared_hit_blocks",
        "shared_read_blocks",
        "shared_dirtied_blocks",
        "shared_read_total",
        "shared_hit_ratio",
        "temp_read_blocks",
        "temp_written_blocks",
        "temp_total_blocks",
        "workers_planned",
        "workers_launched",
        "node_count",
        "max_depth",
        "join_count",
        "scan_count",
        "hash_count",
        "sort_count",
        "aggregate_count",
        "parallel_count",
        "plan_signature",
        "plan_hash",
        "plan_json_path",
        "plan_tree_path",
        "trace_path",
        "selectivity_axes",
        "joint_sel",
    ]

    df = pd.DataFrame(rows, columns=columns)


    # =========================================================
    # N-dimensional plan change analysis
    # =========================================================

    sort_cols = [f"x{i+1}" for i in range(len(param_columns))]

    df = (
        df
        .sort_values(sort_cols)
        .reset_index(drop=True)
    )

    expected = np.prod(shape)

    if len(df) != expected:
        raise RuntimeError(
            f"Incomplete profiling results: "
            f"{len(df)} / {expected} combos succeeded"
        )

    plan_hash_grid = (
        df["plan_hash"]
        .values
        .reshape(shape)
    )

    runtime_grid = (
        df["runtime_mean"]
        .values
        .reshape(shape)
    )

    qerr_maps = compute_axis_qerrors(
        runtime_grid
    )

    plan_masks = compute_axis_plan_changes(
        plan_hash_grid
    )

    for axis in range(len(shape)):

        df[f"adjacent_qerr_x{axis+1}"] = (
            qerr_maps[axis]
            .flatten()
        )

        df[f"plan_change_x{axis+1}"] = (
            plan_masks[axis]
            .flatten()
        )

    # =====================================================
    # Store neighboring coordinates used in qerr
    # =====================================================

    xcols = sorted([
        c for c in df.columns
        if c.startswith("x")
    ])

    coords = (
        df[xcols]
        .values
        .reshape(
            *shape,
            len(shape)
        )
    )

    for axis in range(len(shape)):

        # object dtype preserves Decimal/date/string
        neighbor_grid = np.empty(
            coords.shape,
            dtype=object
        )

        neighbor_grid[:] = None

        slicer_curr = [
            slice(None)
        ] * len(shape)

        slicer_prev = [
            slice(None)
        ] * len(shape)

        slicer_curr[axis] = slice(
            1,
            None
        )

        slicer_prev[axis] = slice(
            0,
            -1
        )

        # copy neighboring coordinate point
        neighbor_grid[
            tuple(slicer_curr)
        ] = coords[
            tuple(slicer_prev)
        ]

        # save each coordinate separately
        for d in range(len(shape)):

            df[
                f"x{d+1}_neighbor_axis{axis+1}"
            ] = (
                neighbor_grid[
                    ...,
                    d
                ]
                .flatten()
            )

    # =====================================================
    # Create independent selectivity columns
    # =====================================================

    if "selectivity_axes" in df.columns:

        for d in range(len(shape)):

            df[
                f"selectivity_x{d+1}"
            ] = df[
                "selectivity_axes"
            ].apply(

                lambda x:
                x[d]
                if (
                    isinstance(x,(list,tuple))
                    and len(x)>d
                )
                else np.nan
            )

    else:

        for d in range(len(shape)):

            df[
                f"selectivity_x{d+1}"
            ]=np.nan


    # =====================================================
    # Store neighbor selectivities and dS
    # =====================================================

    for axis in range(len(shape)):
        
        lookup={}

        for idx,row in df.iterrows():

            key=tuple(
                row[f"x{i+1}"]
                for i in range(len(shape))
            )

            lookup[key]=idx


        neighbor_joint=[]

        for i,row in df.iterrows():

            neighbor_vals=[]

            for d in range(len(shape)):

                neighbor_vals.append(

                    row[
                        f"x{d+1}_neighbor_axis{axis+1}"
                    ]
                )

            # --------------------------------
            # boundary point
            # --------------------------------

            if any(
                pd.isna(v)
                for v in neighbor_vals
            ):

                neighbor_joint.append(
                    np.nan
                )

                for d in range(len(shape)):

                    df.loc[
                        i,
                        f"neighbor_selectivity_x{d+1}_axis{axis+1}"
                    ]=np.nan

                    df.loc[
                        i,
                        f"dS_x{d+1}_axis{axis+1}"
                    ]=np.nan

                continue


            # --------------------------------
            # locate neighbor row
            # --------------------------------

            neighbor_key=tuple(neighbor_vals)
            neighbor_row=df.iloc[lookup[neighbor_key]]

            # --------------------------------
            # actual independent selectivities
            # --------------------------------

            for d in range(len(shape)):

                curr_sel=row[
                    f"selectivity_x{d+1}"
                ]

                neigh_sel=neighbor_row[
                    f"selectivity_x{d+1}"
                ]

                df.loc[
                    i,
                    f"neighbor_selectivity_x{d+1}_axis{axis+1}"
                ]=neigh_sel

                df.loc[
                    i,
                    f"dS_x{d+1}_axis{axis+1}"
                ]=abs(
                    curr_sel
                    -
                    neigh_sel
                )


            # --------------------------------
            # observed joint selectivity (proxy)
            # --------------------------------

            curr_joint=row[
                "joint_sel"
            ]

            neigh_joint=neighbor_row[
                "joint_sel"
            ]

            neighbor_joint.append(
                neigh_joint
            )


        # --------------------------------
        # store joint values
        # --------------------------------

        df[
            f"neighbor_joint_sel_axis{axis+1}"
        ]=neighbor_joint


        df[
            f"joint_dS_axis{axis+1}"
        ]=abs(
            df["joint_sel"]
            -
            df[
                f"neighbor_joint_sel_axis{axis+1}"
            ]
        )


    total_plan_changes = count_plan_changes_nd(plan_hash_grid)

    print("\nPlan change summary:")
    print(f"  Total neighboring plan changes: {total_plan_changes}")
    print(f"  Unique plan hashes: {df['plan_hash'].nunique()}")


    # =========================================================
    # Save metadata
    # =========================================================
    db_meta = config_gt.get_db_metadata(conn)

    metadata = {
        "query_name": config_gt.query_name_from_path(config_gt.QUERY_SQL_PATH),
        "query_path": str(config_gt.QUERY_SQL_PATH),
        "parameters": param_columns,
        "parameter_counts": [len(param_values_dict[col]) for col in param_columns],
        "total_combinations": len(all_combinations),
        "WARMUP_ROUND": config_gt.WARMUP_ROUND,
        "MEASURED_ROUNDS": config_gt.MEASURED_ROUNDS,
        "collection_date": datetime.now().isoformat(),
        "database": db_meta.get("database"),
        "HOST": db_meta.get(f"{config_gt.HOST}"),
        "port": db_meta.get("port"),
        "USER": db_meta.get(f"{config_gt.USER}"),
        "server_version": db_meta.get("server_version"),
        "COMPARATOR_MODULE": config_gt.COMPARATOR_MODULE,
        "PLAN_HASH_METHOD": config_gt.PLAN_HASH_METHOD,
        "SAMPLING_METHOD": CURRENT_METHOD,
        "notes": "All stats from measured rounds only. CSV contains mean runtime + metrics from run closest to mean. Trace files keep all measured runs."
    }

    metadata_path = config_gt.RESULTS_DIR / config_gt.METADATA_FILENAME
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2, default=json_serializer)

    print(f"\nSaved metadata: {metadata_path}")

    # =========================================================
    # Save CSV
    # =========================================================
    out_path = config_gt.RESULTS_DIR / config_gt.RESULTS_FILENAME

    df.to_csv(out_path, index=False)
    resume_state["processors_completed"] = []
    save_resume_state(resume_state)

    print(f"\nSaved: {out_path}")
    print(f"\nColumns ({len(columns)}): {columns}")
    print(f"\nShape: {df.shape}")
    print("\nHead:")
    print(df.head())
    print("\nPlan change summary:")
    for axis in range(len(shape)):

        col = f"plan_change_x{axis+1}"

        print(
            f"  Axis {axis+1} plan changes: "
            f"{df[col].sum()}"
        )
    print(f"  Unique plan hashes: {df['plan_hash'].nunique()}")

    resume_state[
        "finished"
    ]=True

    save_resume_state(
        resume_state
    )

    print()
    print(
        f"{CURRENT_METHOD}"
        f" marked complete"
    )

    conn.close()

    # ==================================================
    # Run per-method processors
    # ==================================================

    resume_state = load_resume_state()

    completed_processors = set(
        resume_state.get(
            "processors_completed",
            []
        )
    )

    for processor in config_gt.PER_METHOD_PROCESSORS:

        if processor in completed_processors:
            continue

        print()
        print(
            f"[{CURRENT_METHOD}] "
            f"Running processor:"
            f"{processor}"
        )

        run_processor(
            processor,
            "per_method_processors",
            config_gt.RESULTS_DIR
        )

        completed_processors.add(
            processor
        )

        resume_state[
            "processors_completed"
        ] = sorted(
            completed_processors
        )

        save_resume_state(
            resume_state
        )


    print()
    print(
        f"{CURRENT_METHOD} finished"
    )

    # =========================================================
    # Final execution timing
    # =========================================================

    script_end_wall = datetime.now()
    script_total_seconds = time.time() - script_start_perf

    runtime_td = timedelta(seconds=int(script_total_seconds))
    hours, remainder = divmod(int(script_total_seconds),3600)
    minutes, seconds = divmod(remainder,60)

    print("\n=================================================")
    print(f"METHOD {CURRENT_METHOD} FINISHED")
    print("=================================================")

    print(f"Start Time : "f"{script_start_wall.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"End Time   : "f"{script_end_wall.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total Time : "f"{hours:02d}:{minutes:02d}:{seconds:02d}")
    print(f"Total Secs : "f"{script_total_seconds:.2f} sec")
    print("=================================================\n")

# ==================================================
# Global processors
# ==================================================

print()
print("="*70)
print("ALL METHODS COMPLETE")
print("="*70)

for processor in config_gt.GLOBAL_PROCESSORS:

    print(
        f"Running global processor:"
        f"{processor}"
    )

    run_processor(
        processor, "global_processors",
        #config_gt.get_main_dir(resolution) / config_gt.QUERY_DIR,
        config_gt.RESULTS_DIR.parent,
    )
    

# =========================================================
# WHOLE SCRIPT FINISHED
# =========================================================

whole_script_end_wall=datetime.now()

whole_script_total=(
    time.time()
    -whole_script_start_perf
)

hours,remainder=divmod(
    int(whole_script_total),
    3600
)

minutes,seconds=divmod(
    remainder,
    60
)

print()
print("="*80)
print("ENTIRE PIPELINE FINISHED")
print("="*80)

print(
    f"Start Time : "
    f"{whole_script_start_wall.strftime('%Y-%m-%d %H:%M:%S')}"
)

print(
    f"End Time   : "
    f"{whole_script_end_wall.strftime('%Y-%m-%d %H:%M:%S')}"
)

print(
    f"Total Time : "
    f"{hours:02d}:{minutes:02d}:{seconds:02d}"
)

print(
    f"Total Seconds : "
    f"{whole_script_total:.2f}"
)

print("="*80)

print(f"PID={os.getpid()} FINISHED")