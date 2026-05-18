# Profiling Data Structure & Organization

## Overview

This document describes the modular folder and CSV structure for multi-parameter query profiling. The design separates concerns:
- **CSV** → queryable summary (one row per combo)
- **JSON files** → detailed plan and trace data (stored separately)
- **Metadata** → collection context and reproducibility

---

## Directory Structure

```
results/
├── profiling_results.csv           # Main ground truth (queryable summary)
├── profiling_metadata.json         # Collection context & parameters
├── plans/                          # EXPLAIN JSON per combo
│   ├── x1_100_x2_50_x3_200.json
│   ├── x1_100_x2_50_x3_201.json
│   └── ...
├── plan_trees/                     # Human-readable tree visualization
│   ├── x1_100_x2_50_x3_200.txt
│   ├── x1_100_x2_50_x3_201.txt
│   └── ...
└── traces/                         # Full run history (rounds 2-4)
    ├── x1_100_x2_50_x3_200_trace.json
    ├── x1_100_x2_50_x3_201_trace.json
    └── ...
```

---

## CSV: `results/profiling_results.csv`

Main index file with one row per parameter combination. All statistics from **rounds 2–4 only** (round 1 is warmup, excluded).

### Parameter Columns

```
x1, x2, x3, ...
```
- Parameter values from SQL WHERE clause parsing
- Example: `x1` = `l_quantity` value, `x2` = `l_shipdate` value, etc.
- Rows sorted by these columns for meaningful `adjacent_qerr` computation

### Runtime Metrics (Mean ± Std)

```
runtime_mean      (float)  - Mean execution time across rounds 2-4 (ms)
runtime_std       (float)  - Std dev across rounds 2-4 (ms)
planning_time     (float)  - From run closest to runtime_mean (ms)
execution_time    (float)  - From run closest to runtime_mean (ms)
```

**Key Logic:** 
- Compute mean runtime from 3 runs
- Find the run whose runtime is closest to that mean
- Extract ALL other metrics from that single "best" run

### Planner Estimates (from best run)

```
root_node         (str)    - Top-level node type (e.g., "Aggregate")
startup_cost      (float)  - Planner's estimated startup cost
total_cost        (float)  - Planner's estimated total cost
plan_rows         (int)    - Planner's estimated result rows
actual_rows       (int)    - Actual row count returned
```

### Buffer & I/O Stats (from best run)

```
shared_hit_blocks        (int)  - Blocks hit in shared buffer
shared_read_blocks       (int)  - Blocks read from disk (cache miss)
shared_dirtied_blocks    (int)  - Blocks written in shared buffer
shared_read_total        (int)  - hit + read (convenience column)
shared_hit_ratio         (float) - hit / total ratio, or 1.0 if total=0
temp_read_blocks         (int)  - Temporary space read
temp_written_blocks      (int)  - Temporary space written
temp_total_blocks        (int)  - read + written (convenience column)
```

### Parallelism (from best run)

```
workers_planned          (int)  - Workers PostgreSQL planned to use
workers_launched         (int)  - Workers actually launched
```

### Plan Structure Metrics (from best run)

```
node_count               (int)  - Total number of plan nodes
max_depth                (int)  - Maximum tree depth
join_count               (int)  - Number of join nodes
scan_count               (int)  - Number of scan nodes
hash_count               (int)  - Number of hash nodes
sort_count               (int)  - Number of sort nodes
aggregate_count          (int)  - Number of aggregate nodes
parallel_count           (int)  - Number of parallel nodes
```

### Plan Identity & Hashing

```
plan_signature           (str)  - String representation "Node1->Node2->..."
plan_hash                (str)  - MD5 hash from comparator.structural_hash()
```

### Storage Paths (Relative)

```
plan_json_path           (str)  - Relative path to plans/x1_VAL_x2_VAL.json
plan_tree_path           (str)  - Relative path to plan_trees/x1_VAL_x2_VAL.txt
trace_path               (str)  - Relative path to traces/x1_VAL_x2_VAL_trace.json
```

### Derived Metrics

```
adjacent_qerr x1           (float) - max(RT[i]/RT[i-1], RT[i-1]/RT[i])
                                   Computed after sorting by parameters per axis
```

---

## Supporting Files

### `results/plans/` — EXPLAIN JSON

**Naming Convention:** `x1_VAL_x2_VAL_x3_VAL.json`
- Example: `x1_100_x2_50_x3_200.json`
- One file per unique parameter combination

**Content:** Complete EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output
```json
{
  "Plan": { ... full plan tree ... },
  "Planning Time": 0.145,
  "Execution Time": 125.432,
  "Trigger Count": 0
}
```

**Purpose:**
- Reconstruct the exact PostgreSQL plan
- Analyze planner decision-making in detail
- Input to `comparator.structural_hash()` for plan deduplication

---

### `results/plan_trees/` — Human-Readable Tree

**Naming Convention:** `x1_VAL_x2_VAL_x3_VAL.txt`
- Example: `x1_100_x2_50_x3_200.txt`

**Content:** Output of `comparator.plan_tree_str(plan)` with tree structure

Example:
```
  └── Aggregate
    └── Gather
      └── Aggregate
        └── Seq Scan on lineitem
          Filter: l_quantity <= 100
          Rows: 49876 / 50000 (est)
```

**Purpose:**
- Quick visual inspection without parsing JSON
- Easy diffing between consecutive combos to spot changes
- Human-readable debugging reference

---

### `results/traces/` — Full Run History

**Naming Convention:** `x1_VAL_x2_VAL_x3_VAL_trace.json`
- Example: `x1_100_x2_50_x3_200_trace.json`
- One file per parameter combination

**Content:** All 3 measured runs (rounds 2, 3, 4)

```json
{
  "combo": [100, 50, 200],
  "param_names": ["l_quantity", "l_shipdate", "l_discount"],
  "runs": [
    {
      "round": 2,
      "runtime": 125.45,
      "execution_time": 125.40,
      "planning_time": 0.05,
      "plan_rows": 50000,
      "actual_rows": 49876,
      "startup_cost": 0.00,
      "total_cost": 50000.50,
      "workers_planned": 4,
      "workers_launched": 4,
      "shared_hit_blocks": 8000,
      "shared_read_blocks": 200,
      "shared_dirtied_blocks": 0,
      "temp_read_blocks": 0,
      "temp_written_blocks": 0,
      "plan_signature": "Aggregate->Gather->Seq Scan",
      "plan_hash": "abc123def456"
    },
    {
      "round": 3,
      "runtime": 127.20,
      ...
    },
    {
      "round": 4,
      "runtime": 124.80,
      ...
    }
  ]
}
```

**Purpose:**
- Preserve full variance history (all 3 runs)
- Support outlier detection and anomaly analysis
- Enable variance-based model training
- Allow retrospective analysis of measurement quality

---

### `results/profiling_metadata.json` — Collection Context

**Content:**
```json
{
  "query_name": "qt1",
  "parameters": ["l_quantity", "l_shipdate", "l_discount"],
  "parameter_counts": [50, 20, 10],
  "total_combinations": 10000,
  "warmup_round": 1,
  "measured_rounds": [2, 3, 4],
  "collection_date": "2026-05-08T14:30:00",
  "database": "tpchdb_sf10",
  "host": "localhost",
  "port": 5432,
  "comparator_module": "scripts/automated-script/comparator.py",
  "plan_hash_method": "structural_hash_md5",
  "notes": "All stats from runs 2-4. CSV contains mean runtime + metrics from run closest to mean."
}
```

**Purpose:**
- Reproducibility and auditability
- Query name and parameter configuration
- Database connection details
- Algorithm details (hash method, rounds used)

---

## Data Flow & Collection Logic

1. **SQL Parsing**
   - Load query (e.g., `qt1.sql`)
   - Extract parameter columns from WHERE clause (e.g., `l_quantity`, `l_shipdate`)

2. **Parameter Collection**
   - Query database for all distinct values per parameter
   - Generate all combinations via `itertools.product()`

3. **Warm-Up (Round 1)**
   - Run each combo once
   - Discard results (not stored)

4. **Measurement (Rounds 2–4)**
   - For each combo, run 3 times
   - Store execution time, EXPLAIN output, buffers, everything

5. **Per-Combo Aggregation**
   - Compute `runtime_mean` and `runtime_std` from the 3 runs
   - Find run closest to mean
   - Extract all other metrics (costs, buffers, etc.) from that run
   - Compute `plan_hash` via `comparator.structural_hash()`
   - Store plan JSON and tree representation
   - Store full trace (all 3 runs) for reference

6. **CSV Assembly**
   - Create one row per combo
   - Include parameters, aggregated runtime, best-run metrics, storage paths

7. **Adjacency Metrics**
   - Sort rows by parameter values
   - Compute `adjacent_qerr` based on sorted order for meaningful QERR

---

## Why This Structure?

| Design Choice | Benefit |
|---------------|---------|
| **CSV only has one row per combo** | Queryable, importable to ML, Pandas-friendly |
| **JSON files separated** | Scalability; don't embed large JSON in CSV |
| **Paths are relative** | Portability; works across machines/repos |
| **Trace file preserves all runs** | Enables variance analysis, outlier detection |
| **plan_hash computed** | Quick plan deduplication, change detection |
| **plan_tree file generated** | Quick human inspection without JSON parsing |
| **Metadata JSON stored** | Full reproducibility; answers "how was this collected?" |

---

## Example Workflow

### Generate profiling data
```bash
python3 scripts/profiler_1d.py  # Generates all CSV, plans/, traces/, etc.
```

### Query in pandas
```python
import pandas as pd
df = pd.read_csv("results/profiling_results.csv")
# Filter, group, analyze
plan_changes = df[df['plan_hash'].ne(df['plan_hash'].shift(1))]
```

### Inspect a specific combo
```bash
cat results/plan_trees/x1_100_x2_50_x3_200.txt  # Tree view
cat results/plans/x1_100_x2_50_x3_200.json      # Full EXPLAIN
cat results/traces/x1_100_x2_50_x3_200_trace.json  # All 3 runs
```

### Plot metrics
```python
# Plot adjacent_qerr vs parameters
df.plot(x='x1', y='adjacent_qerr')

# Overlay plan changes
plan_change_rows = df[df['plan_hash'].ne(df['plan_hash'].shift(1))]
plt.scatter(plan_change_rows['x1'], plan_change_rows['adjacent_qerr'])
```

---

## Summary Table

| File/Folder | Purpose | Scope | Format |
|-------------|---------|-------|--------|
| **profiling_results.csv** | Queryable summary index | 1 row per combo | CSV (pandas) |
| **profiling_metadata.json** | Collection metadata | Global | JSON |
| **plans/** | EXPLAIN JSON | 1 file per combo | JSON (PostgreSQL) |
| **plan_trees/** | Human-readable plans | 1 file per combo | TXT (tree format) |
| **traces/** | Full run history | 1 file per combo (3 runs each) | JSON (custom) |

---

