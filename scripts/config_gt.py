#config_gt.py
from pathlib import Path

# Directory layout for ground truth artifacts
RESULTS_DIR = Path("gt_results_sf10_qt8_10x10_m1")
PLANS_DIR = RESULTS_DIR / "plans"
PLAN_TREES_DIR = RESULTS_DIR / "plan_trees"
TRACES_DIR = RESULTS_DIR / "traces"

# SQL source for the profiled query
QUERY_SQL_PATH = Path(__file__).resolve().parent / "automated_script" / "queries" / "qt8.sql"

# Profiling rounds
TOTAL_ROUNDS = 4
WARMUP_ROUND = 1
MEASURED_ROUNDS = list(range(WARMUP_ROUND + 1, TOTAL_ROUNDS + 1))

# =========================================================
# Sampling method
# =========================================================
#
# "normal"          - linear spacing in the parameter-value
#                     domain (any N-D).
# "selectivity_m1"  - percentile_cont — exact CDF inverse
#                     from the data. 1-D or 2-D only.
# "selectivity_m2"  - Picasso-style histogram interpolation
#                     using pg_stats. 1-D or 2-D only.
#
# Used by build_gt.py to pick which sampler module to call.

SAMPLING_METHOD = "selectivity_m1"

# =========================================================
# Per-method resolutions
# =========================================================

# Linear value-spacing — works in any number of dimensions.
NORMAL_RES = {
    "default": 100,
    # "p1": 100,
    # "p2": 100,
}

# Method 1 (percentile_cont). 1-D / 2-D.
SELECTIVITY_RES_M1 = {
    "default": 10,
    # "p1": 100,
    # "p2": 100,
}

# Method 2 (Picasso histogram). 1-D / 2-D.
SELECTIVITY_RES_M2 = {
    "default": 10,
    # "p1": 100,
    # "p2": 100,
}

# Backwards-compat aliases — kept so older call sites
# don't break.
DEFAULT_RESOLUTION = NORMAL_RES["default"]
PARAM_RESOLUTIONS = {
    k: v for k, v in NORMAL_RES.items() if k != "default"
}


def get_resolution_map():
    """Return (default, per-param overrides) for the active method."""
    if SAMPLING_METHOD == "normal":
        src = NORMAL_RES
    elif SAMPLING_METHOD == "selectivity_m1":
        src = SELECTIVITY_RES_M1
    elif SAMPLING_METHOD == "selectivity_m2":
        src = SELECTIVITY_RES_M2
    else:
        raise RuntimeError(f"Unknown SAMPLING_METHOD: {SAMPLING_METHOD}")

    default = src.get("default", 100)
    overrides = {k: v for k, v in src.items() if k != "default"}
    return default, overrides

# =========================================================
# Hard caps (auto-clamped)
# =========================================================

# Integer/date params:
# cannot exceed distinct possible values
#
# Float/decimal:
# unrestricted

MAX_COMBINATIONS = 20000

# ===========================================================

# Output filenames
RESULTS_FILENAME = "ground_truth.csv"
METADATA_FILENAME = "gt_metadata.json"

# Comparator metadata
COMPARATOR_MODULE = "scripts/automated_script/comparator.py"
PLAN_HASH_METHOD = "structural_hash_md5"


def query_name_from_path(path: Path) -> str:
    return path.stem


def ensure_paths():
    for d in [RESULTS_DIR, PLANS_DIR, PLAN_TREES_DIR, TRACES_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_db_metadata(conn):
    metadata = {
        "database": None,
        "host": None,
        "port": None,
        "user": None,
        "server_version": None,
    }
    try:
        params = conn.get_dsn_parameters()
        metadata["database"] = params.get("dbname")
        metadata["host"] = params.get("host")
        metadata["port"] = params.get("port")
        metadata["user"] = params.get("user")
    except Exception:
        pass

    try:
        cur = conn.cursor()
        cur.execute("SELECT current_database(), current_user(), inet_server_addr(), inet_server_port(), version();")
        dbname, user, host, port, version = cur.fetchone()
        cur.close()
        metadata["database"] = metadata["database"] or dbname
        metadata["user"] = metadata["user"] or user
        metadata["host"] = metadata["host"] or (host if host else "localhost")
        metadata["port"] = metadata["port"] or (str(port) if port else None)
        metadata["server_version"] = version
    except Exception:
        pass

    return metadata
