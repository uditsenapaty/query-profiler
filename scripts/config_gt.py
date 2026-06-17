# =========================================================
# config_gt.py
# =========================================================
from pathlib import Path
import os
from tpch_query_parser import TPCHQueryParser

# =========================================================
# 1. Database Configs
# =========================================================

from tpch import setup_tpch

DATABASE_NAME = setup_tpch.DATABASE_NAME
PASSWORD = setup_tpch.PASSWORD
USER = setup_tpch.USER
HOST = setup_tpch.HOST
PORT = setup_tpch.PORT
SF = setup_tpch.SF

# Imports
# Plan Comparator
COMPARATOR_MODULE = "./tpch/utils/comparator.py"
PLAN_HASH_METHOD = "structural_hash_sha256"

# Parallellism Support for Query runs
SYSTEM_WORKERS = 1 # MIN 1 
QUERY_WORKERS = 2 # MIN 0 / DEFAULT 2

# =========================================================
# 2. SQL source 
# =========================================================

# Input if run for 1 QUERY ONLY using "build_gt.py"!!
QUERY="mqt8"
# OPTIONAL : For MULTIPLE QUERY runs together use : "run_multi_gt.py"!!
QUERIES=[
    "qt5",
    "qt7",
    "qt8",
    "qt10",
    "qt16",
]

QUERY_SQL_PATH=(
    Path(__file__).resolve().parent
    / "tpch"
    / "queries"
    / f"{QUERY}.sql"
)

# =========================================================
# 3. Method registry
# =========================================================

# data_m0         – uniform resolution over the data space
# selectivity_m1  – uniform resolution over the selectivity
#                   space (percentile method).
# selectivity_m2  – exponential resolution over the selectivity
#                   space (geometric method).

# SET EITHER DEFAULT RES FOR ALL OR CUSTOM P1/P2... RES FOR ALL
DEF_RES_ALL = 10

P1_RES_ALL = None
P2_RES_ALL = None

# SET DEFAULT/CUSTOM RES FOR EACH METHOD
METHOD_CONFIGS = {

    "m0":{
        "sampler":"sampler_data_m0",
        "resolution":{
            "default":DEF_RES_ALL,
            "p1": P1_RES_ALL,
            "p2": P2_RES_ALL,
        }
    },

    "m1":{
        "sampler":"sampler_selectivity_m1",
        "resolution":{
            "default":DEF_RES_ALL,
            "p1": P1_RES_ALL,
            "p2": P2_RES_ALL,
        }
    },

    "m2":{

        "sampler":"sampler_selectivity_m2",
        "resolution":{
            "default":DEF_RES_ALL,
            "p1": P1_RES_ALL,
            "p2": P2_RES_ALL,
        }
    },

    # "m3":{

    #     "sampler":"sampler_selectivity_m3",
    #     "resolution":{
    #         "default":DEF_RES_ALL,
    #         "p1": P1_RES_ALL,
    #         "p2": P2_RES_ALL,
    #     }
    # },

}

# ================================================
# Helper for resolution string
# ================================================
def get_resolution_string(method, n_dims):

    res_cfg = METHOD_CONFIGS[method]["resolution"]
    default_res = res_cfg["default"]
    vals = []

    for i in range(1, n_dims + 1):
        key = f"p{i}"
        val = res_cfg.get(key)
        if val is None:
            val = default_res
        vals.append(str(val))

    return "x".join(vals)


# =========================================================
# 4. Sampling method
# =========================================================
# all  -> run all methods sequentially
# m0   -> data-space uniform resolution
# m1   -> selectivity-space uniform resolution
# m2   -> Picasso exponential resolution using Actual stats

CURRENT_METHOD=None
SAMPLING_METHOD = "all"

if SAMPLING_METHOD == "all" :
    RUN_METHODS=list(METHOD_CONFIGS.keys())
elif SAMPLING_METHOD == ("m0"or"m1"or"m2"or"m3") :
    RUN_METHODS = [SAMPLING_METHOD]
else:
    RUN_METHODS = ["m0", "m1"]


SAMPLER_FILES={
    k:v["sampler"]
    for k,v in METHOD_CONFIGS.items()
}

# =========================================================
# 5. Method → sampler file mapping
# =========================================================
def get_active_methods():

    if SAMPLING_METHOD=="all":
        return RUN_METHODS

    if SAMPLING_METHOD not in SAMPLER_FILES:
        raise RuntimeError(
            f"Unknown method: "
            f"{SAMPLING_METHOD}"
        )

    return [SAMPLING_METHOD]

# =========================================================
# 6. Result directories
# =========================================================

# Result mode suffix
IS_MULTI_RUN=(
    os.environ.get("GT_LOGFILE_MODE")
    == "1"
)

RUN_SUFFIX = (
    os.environ.get(
        "GT_RUN_SUFFIX",
        f"_s1q{QUERY_WORKERS}"
    )
)

# Query result directory
QUERY_DIR=Path(f"{QUERY}")

MAIN_DIR=None
RESULTS_DIR=None
PLANS_DIR=None
PLAN_TREES_DIR=None
TRACES_DIR=None
RESULTS_FILENAME = "ground_truth.csv"
METADATA_FILENAME = "gt_metadata.json"

def get_main_dir(resolution):

    return Path(
        f"gt_results_sf{SF}_{resolution}{RUN_SUFFIX}"
    )

def set_main_dir(resolution):
    global MAIN_DIR

    MAIN_DIR = Path(
        f"gt_results_sf{SF}_{resolution}{RUN_SUFFIX}"
    )

def get_method_dir(method, resolution):
    if MAIN_DIR is None:
        raise RuntimeError(
            "MAIN_DIR not initialized. "
            "Call set_main_dir() first."
        )

    return (
        get_main_dir(resolution)
        / QUERY_DIR
        / method
    )

def set_method_paths(method, resolution):
    global RESULTS_DIR
    global PLANS_DIR
    global PLAN_TREES_DIR
    global TRACES_DIR

    RESULTS_DIR=get_method_dir(method, resolution)
    PLANS_DIR=RESULTS_DIR/"plans"
    PLAN_TREES_DIR=(RESULTS_DIR/"plan_trees")
    TRACES_DIR=(RESULTS_DIR/"traces")

def get_num_dimensions(query_name):

    sql_path = (
        Path(__file__).resolve().parent
        / "tpch"
        / "queries"
        / f"{query_name}.sql"
    )

    with open(sql_path) as f:
        sql_text = f.read()

    parser = TPCHQueryParser()
    parsed = parser.parse(sql_text)
    return len(parsed["parameters"])

def get_query_resolution(query_name, method):

    from tpch_query_parser import TPCHQueryParser

    sql_path = (
        Path(__file__).resolve().parent
        / "tpch"
        / "queries"
        / f"{query_name}.sql"
    )

    with open(sql_path) as f:
        sql_text = f.read()

    parser = TPCHQueryParser()
    parsed = parser.parse(sql_text)

    ndim = len(parsed["parameters"])

    return get_resolution_string(
        method,
        ndim
    )

# =========================================================
# 7. Other Configs and Constraints
# =========================================================
# Profiling rounds
TOTAL_ROUNDS = 4
WARMUP_ROUND = 1
MEASURED_ROUNDS = list(range(WARMUP_ROUND + 1, TOTAL_ROUNDS + 1))

# Maximum points for ground truth sampling
# Integer/date params: cannot exceed distinct possible values; Float/decimal: unrestricted
MAX_COMBINATIONS = 20000


# =========================================================
# 8. Post-processing
# =========================================================

# Runs AFTER EACH method
PER_METHOD_PROCESSORS=[
    "grid_qerr",
    "grid_selectivity",
    "qerr_desc",
    "summarise",
    "qerr_threshold_curves",
    # "neighbor_analysis",
    # "qerr_stats",
    # "plan_summary",
]

# Runs ONCE after ALL methods
GLOBAL_PROCESSORS=[
    "compare_sampling_grid",
    "compare_sampling_grid_nb",
    "summary_global",
    # "compare_methods",
    # "merge_all",
    # "build_dashboard",
]

# ===========================================================


def get_resolution_map(method=None):

    method = (
        method
        or CURRENT_METHOD
        or SAMPLING_METHOD
    )

    src = METHOD_CONFIGS[method]["resolution"]
    default = src.get("default", 10)
    overrides = {}

    for k, v in src.items():
        if k == "default":
            continue

        if v is not None:
            overrides[k] = v

    return default, overrides


def query_name_from_path(path: Path) -> str:
    return path.stem

def ensure_paths():
    for d in [
        RESULTS_DIR,
        PLANS_DIR,
        PLAN_TREES_DIR,
        TRACES_DIR
    ]:
        if d is not None:
            d.mkdir(
                parents=True,
                exist_ok=True
            )

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