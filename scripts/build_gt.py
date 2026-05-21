# =========================================================
# scripts/build_gt.py
# =========================================================

import pandas as pd
import numpy as np
import time
import json
import sqlparse
import sys
import os
from pathlib import Path
from decimal import Decimal
from itertools import product
from datetime import datetime, timedelta
from config_gt import (
    ensure_paths,
    QUERY_SQL_PATH,
    RESULTS_DIR,
    PLANS_DIR,
    PLAN_TREES_DIR,
    TRACES_DIR,
    TOTAL_ROUNDS,
    WARMUP_ROUND,
    MEASURED_ROUNDS,
    RESULTS_FILENAME,
    METADATA_FILENAME,
    COMPARATOR_MODULE,
    PLAN_HASH_METHOD,
    MAX_COMBINATIONS,
    SAMPLING_METHOD,
    get_resolution_map,
    query_name_from_path,
    get_db_metadata,
    DATABASE_NAME,
    USER,
    HOST,
    PASSWORD,
)
import re
import psycopg2
import psycopg2.sql as sql
from tpch_query_parser import TPCHQueryParser

import sampler_normal
import sampler_selectivity_m1
import sampler_selectivity_m2

SAMPLERS = {
    "normal": sampler_normal,
    "selectivity_m1": sampler_selectivity_m1,
    "selectivity_m2": sampler_selectivity_m2,
}

# Import comparator for plan hashing
from automated_script.comparator import structural_hash, plan_tree_str

# =====================================================
# Sampler dispatch
# =====================================================
#
# The three sampling strategies live in dedicated modules
# (sampler_normal, sampler_selectivity_m1,
# sampler_selectivity_m2). The active strategy is chosen
# by SAMPLING_METHOD in config_gt.py.

DEFAULT_RESOLUTION, PARAM_RESOLUTIONS = get_resolution_map()
sampler = SAMPLERS[SAMPLING_METHOD]
print(f"Sampler: {SAMPLING_METHOD} (default resolution={DEFAULT_RESOLUTION})")

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
# Connect to tpch database
# =========================================================

def get_conn(dbname):
    return psycopg2.connect(
        dbname=dbname,
        user=USER,
        password=PASSWORD,
        host=HOST,
    )

conn = get_conn(DATABASE_NAME)

# FOR STABILITY
setup_cur = conn.cursor()
setup_cur.execute("SET jit = off;")
setup_cur.execute("SET max_parallel_workers_per_gather = 0;")
setup_cur.execute("SET track_io_timing = on;")
setup_cur.execute("SET enable_partitionwise_join = off;")
setup_cur.execute("SET enable_partitionwise_aggregate = off;")
setup_cur.close()

# =========================================================
# Create output directories
# =========================================================
ensure_paths()

print(f"Output directories ready:\n  {PLANS_DIR}\n  {PLAN_TREES_DIR}\n  {TRACES_DIR}")


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
# Helper to Find largest intermediate cardinality
# =========================================================
def get_max_actual_rows(node):
    rows = node.get("Actual Rows",0)

    for child in node.get("Plans",[]):
        rows = max(rows,get_max_actual_rows(child))

    return rows

# =========================================================
# Create output directories
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
# Load SQL query and parse with sqlparse
# =========================================================
with open(QUERY_SQL_PATH, "r") as f:
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
# Parameter extraction
# =========================================================

param_columns = [
    p.replace(":", "")
    for p in parsed["parameters"]
]

param_columns = sorted(
    param_columns,
    key=lambda x: int(x[1:])
)

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
print("SELECTIVITY INFO")
print("=================================================")

print(
    f"Query tables: {query_tables}"
)

print(
    f"Total rows across tables: "
    f"{total_relation_rows:,}"
)

print("=================================================\n")


# =========================================================
# Safe parameter substitution
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
# Resolve unqualified column
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

# =========================================================
# Cache DISTINCT column values
# =========================================================
distinct_cache = {}
# =========================================================
# Collect all values for each parameter
# =========================================================
# Selectivity-based methods are defined for 1-D and 2-D
# only (matches the Picasso paper). Bail out early if the
# template has more parameters.
if SAMPLING_METHOD in ("selectivity_m1", "selectivity_m2"):
    if len(param_columns) not in (1, 2):
        raise RuntimeError(
            f"SAMPLING_METHOD={SAMPLING_METHOD} only supports "
            f"1-D or 2-D templates; got {len(param_columns)} "
            f"parameters: {param_columns}"
        )

param_values_dict = {}

for param in param_columns:

    column_expr = param_to_column[param]

    real_table, column = resolve_column(
        conn,
        column_expr,
        table_aliases
    )

    resolution = PARAM_RESOLUTIONS.get(
        param,
        DEFAULT_RESOLUTION
    )

    values = sampler.sample(
        conn,
        real_table,
        column,
        resolution,
    )

    param_values_dict[param] = values

    print(
        f"{param}: "
        f"{len(values)} samples "
        f"[{values[0]} → {values[-1]}]"
    )

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

if len(all_combinations) > MAX_COMBINATIONS:
    raise RuntimeError(
        f"Too many combinations: {len(all_combinations)}"
    )

print(f"Total combinations to profile: {len(all_combinations)}")

# =========================================================
# Persistent cache for 3 runs per parameter combination
# =========================================================
all_temp_runs = {combo: [] for combo in all_combinations}

# =========================================================
# Run all queries TOTAL_ROUNDS times (discard warmup)
# =========================================================
def strip_order_by(sql_query):

    parsed = sqlparse.parse(sql_query)[0]

    output = []

    depth = 0

    tokens = list(parsed.flatten())

    i = 0

    while i < len(tokens):

        token = tokens[i]

        value = token.value
        upper = value.upper()

        depth += value.count("(")
        depth -= value.count(")")

        if depth == 0:

            if upper == "ORDER":

                j = i + 1

                while j < len(tokens) and tokens[j].is_whitespace:
                    j += 1

                if j < len(tokens):

                    if tokens[j].value.upper() == "BY":
                        break

        output.append(value)

        i += 1

    return "".join(output).strip()

def get_filtered_cardinality(conn, query):

    query_no_order = strip_order_by(query)
    query_no_order = query_no_order.rstrip().rstrip(";")

    wrapped = f"""
    EXPLAIN (ANALYZE, FORMAT JSON)
    {query_no_order}
    """

    cur = conn.cursor()
    cur.execute(wrapped)

    explain = cur.fetchone()[0][0]

    cur.close()

    plan = explain["Plan"]

    return get_max_actual_rows(plan)

# =========================================================
# Precompute exact query output row counts
# =========================================================

combo_queries = {}
combo_row_counts = {}

for combo in all_combinations:

    query_to_run = substitute_params(
        sql_text,
        combo
    )

    combo_queries[combo] = query_to_run

    combo_row_counts[combo] = get_filtered_cardinality(
        conn,
        query_to_run
    )
    
    #logs
    if len(combo_queries) % 25 == 0:

        print(
            f"Preparation progress: "
            f"{len(combo_queries)}/{len(all_combinations)}"
        )
    
# =========================================================
# LOGS
global_start = time.time()
total_queries = TOTAL_ROUNDS * len(all_combinations)
completed_queries = 0
# =========================================================

for round_id in range(TOTAL_ROUNDS):
    # FOR STABILITY
    round_setup = conn.cursor()
    round_setup.execute("DISCARD PLANS;")
    round_setup.close()


    print(f"\n--- Round {round_id + 1} ---\n")
    for combo in all_combinations:
        query_to_run = combo_queries[combo]

        cur = conn.cursor()

        try:

            cur.execute(
                f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query_to_run}"
            )
            explain_data = cur.fetchone()[0][0]

        except Exception as e:

            # failed_combos.append({
            #     "combo": combo,
            #     "error": str(e)
            # })

            print(f"FAILED combo={combo}")
            print(e)
            conn.rollback()
            cur.close()
            continue

        cur.close()

        execution_time = explain_data["Execution Time"]

        # ======================================================
        # LOGS
        completed_queries += 1
        elapsed = time.time() - global_start
        avg_time = elapsed / completed_queries
        remaining = total_queries - completed_queries
        eta_seconds = avg_time * remaining
        eta_minutes = eta_seconds / 60

        print(
            f"[{completed_queries}/{total_queries}] "
            f"combo={combo} "
            f"time={execution_time:.2f} ms "
            f"ETA={eta_minutes:.1f} min"
        )
        # ======================================================

        if round_id >= WARMUP_ROUND:
            all_temp_runs[combo].append({
                "runtime": execution_time,
                "explain": explain_data,
                "round": round_id + 1
            })

    print(f"Completed round {round_id + 1}/{TOTAL_ROUNDS}")

print("\nFinished precomputing row counts")


# =========================================================
# Compute global max cardinality
# =========================================================

max_count = max(
    combo_row_counts.values()
)

print()
print("=================================================")
print("SELECTIVITY NORMALIZATION")
print("=================================================")

print(
    f"Max output cardinality: "
    f"{max_count:,}"
)

print("=================================================")
print()


# =========================================================
# Precompute selectivity lookup
# =========================================================

axis_selectivities = {}

for param in param_columns:

    resolution = PARAM_RESOLUTIONS.get(
        param,
        DEFAULT_RESOLUTION
    )

    if SAMPLING_METHOD.startswith(
        "selectivity"
    ):
        axis_selectivities[param] = (
            sampler.selectivities(
                resolution
            )
        )
    else:
        axis_selectivities[param] = None


# =========================================================
# Build rows for DataFrame
# =========================================================

all_intermediate_rows=[]

for combo in all_combinations:

    temp_runs=all_temp_runs[combo]

    if len(temp_runs)==0:
        continue

    explain_data=temp_runs[0]["explain"]
    plan=explain_data["Plan"]

    all_intermediate_rows.append(
        get_max_actual_rows(plan)
    )

max_filtered_cardinality=max(combo_row_counts.values())

rows=[]

for combo_idx,combo in enumerate(all_combinations):

    temp_runs=all_temp_runs[combo]

    if len(temp_runs)==0:

        print(
            f"Skipping failed combo:{combo}"
        )
        continue


    runtimes=[
        r["runtime"]
        for r in temp_runs
    ]

    runtime_mean=np.mean(
        runtimes
    )

    runtime_std=np.std(
        runtimes
    )


    best_run=min(
        temp_runs,
        key=lambda r:abs(
            r["runtime"]
            -runtime_mean
        )
    )

    explain_data=best_run["explain"]

    plan=explain_data["Plan"]


    # =====================================================
    # Cardinality for selectivity
    # =====================================================

    count_rows=combo_row_counts[combo]

    selectivity=(
        count_rows/
        max(max_filtered_cardinality,1)
    )

    selectivity_percent = selectivity * 100

    selectivity_axes = None


    selectivity_percent=(
        selectivity*100
    )


    root_node = plan.get("Node Type")
    startup_cost = plan.get("Startup Cost")
    total_cost = plan.get("Total Cost")
    plan_rows = plan.get("Plan Rows")
    root_rows = int(plan.get("Actual Rows", 0))

    if root_rows is None:
        root_rows = 0
    root_rows = int(float(root_rows))


    # =====================================================
    # DISTINCT mode: use actual executed cardinality
    # =====================================================
    if combo_row_counts[combo] is None:
        combo_row_counts[combo] = root_rows

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
    plan_json_path = PLANS_DIR / f"{combo_filename}.json"
    with open(plan_json_path, "w") as f:
        json.dump(explain_data, f, indent=2, default=json_serializer)
    rel_plan_json_path = f"plans/{combo_filename}.json"

    # =========================================================
    # Save plan tree file
    # =========================================================
    plan_tree_path = PLAN_TREES_DIR / f"{combo_filename}.txt"
    with open(plan_tree_path, "w") as f:
        f.write(plan_tree)
    rel_plan_tree_path = f"plan_trees/{combo_filename}.txt"

    # =========================================================
    # Save trace file (all measured runs)
    # =========================================================
    trace_data = {
        "combo": list(combo),
        "count_rows": combo_row_counts[combo],
        "param_names": param_columns,
        "measured_rounds": MEASURED_ROUNDS,
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
            "count_rows": combo_row_counts[combo],
            "plan_rows": run_plan.get("Plan Rows"),
            "root_rows": run_plan.get("Actual Rows"),
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
            "selectivity": selectivity,
            "selectivity_percent": selectivity_percent,
        })

    trace_path = TRACES_DIR / f"{combo_filename}_trace.json"
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
        root_rows,
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
        selectivity,
        selectivity_percent,
    ])

    print(f"Combo={combo} | runtime={runtime_mean:.4f} ms | plan_hash={plan_hash[:8]}... | plan={root_node}")


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
    "root_rows",
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
    "selectivity",
    "selectivity_percent",
]

df = pd.DataFrame(rows, columns=columns)

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

        #qmap = np.ones(runtime_grid.shape)
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
        

total_plan_changes = count_plan_changes_nd(plan_hash_grid)

print("\nPlan change summary:")
print(f"  Total neighboring plan changes: {total_plan_changes}")
print(f"  Unique plan hashes: {df['plan_hash'].nunique()}")


# =========================================================
# Save metadata
# =========================================================
db_meta = get_db_metadata(conn)

metadata = {
    "query_name": query_name_from_path(QUERY_SQL_PATH),
    "query_path": str(QUERY_SQL_PATH),
    "parameters": param_columns,
    "parameter_counts": [len(param_values_dict[col]) for col in param_columns],
    "total_combinations": len(all_combinations),
    "warmup_round": WARMUP_ROUND,
    "measured_rounds": MEASURED_ROUNDS,
    "collection_date": datetime.now().isoformat(),
    "database": db_meta.get("database"),
    "host": db_meta.get("host"),
    "port": db_meta.get("port"),
    "user": db_meta.get("user"),
    "server_version": db_meta.get("server_version"),
    "comparator_module": COMPARATOR_MODULE,
    "plan_hash_method": PLAN_HASH_METHOD,
    "sampling_method": SAMPLING_METHOD,
    "notes": "All stats from measured rounds only. CSV contains mean runtime + metrics from run closest to mean. Trace files keep all measured runs."
}

metadata_path = RESULTS_DIR / METADATA_FILENAME
with open(metadata_path, "w") as f:
    json.dump(metadata, f, indent=2, default=json_serializer)

print(f"\nSaved metadata: {metadata_path}")

# =========================================================
# Save CSV
# =========================================================
out_path = RESULTS_DIR / RESULTS_FILENAME
df.to_csv(out_path, index=False)
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

conn.close()

# =========================================================
# Final execution timing
# =========================================================

script_end_wall = datetime.now()
script_total_seconds = time.time() - script_start_perf

runtime_td = timedelta(
    seconds=int(script_total_seconds)
)

hours, remainder = divmod(
    int(script_total_seconds),
    3600
)

minutes, seconds = divmod(
    remainder,
    60
)

print("\n=================================================")
print("SCRIPT FINISHED")
print("=================================================")

print(
    f"Start Time : "
    f"{script_start_wall.strftime('%Y-%m-%d %H:%M:%S')}"
)

print(
    f"End Time   : "
    f"{script_end_wall.strftime('%Y-%m-%d %H:%M:%S')}"
)

print(
    f"Total Time : "
    f"{hours:02d}:{minutes:02d}:{seconds:02d}"
)

print(
    f"Total Secs : "
    f"{script_total_seconds:.2f} sec"
)

print("=================================================\n")