# =========================================================
# config_gt.py
# =========================================================
from pathlib import Path
import os

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
PLAN_HASH_METHOD = "structural_hash_md5"

# =========================================================
# 2. SQL source 
# =========================================================

# OPTIONAL : Input if run for 1 QUERY ONLY using "build_gt.py"!!
# For MULTIPLE QUERY runs together use : "run_multi_gt.py"!!
QUERY="qt8"

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

# SET GLOBAL_PROCESSOR RES HELPER

res_cfg = METHOD_CONFIGS["m0"]["resolution"]
default_res = res_cfg["default"]

GLOBAL_PROCESSOR_RES = "x".join(

    str(
        res_cfg[k]
        if res_cfg[k] is not None
        else default_res
    )

    for k in sorted(res_cfg)
    if k.startswith("p")
)


# =========================================================
# 4. Sampling method
# =========================================================
# all  -> run all methods sequentially
# m0   -> data-space
# m1   -> selectivity uniform
# m2   -> Picasso exponential

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

RUN_SUFFIX=(
    "_m"
    if IS_MULTI_RUN
    else "_s"
)

# Main result directory
MAIN_DIR=Path(
    f"gt_results_sf{SF}_{QUERY}{RUN_SUFFIX}"
)

RESULTS_DIR=None
PLANS_DIR=None
PLAN_TREES_DIR=None
TRACES_DIR=None
RESULTS_FILENAME = "ground_truth.csv"
METADATA_FILENAME = "gt_metadata.json"

def get_method_dir(method, resolution):

    return (
        MAIN_DIR
        / str(resolution)
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
    "grid_sample",
    "grid_qerr",
    "grid_score",
    "grid_selectivity",
    "qerr_desc",
    "qerr_desc_nb",
    "summarised_instances",
    "qerr_threshold_curves",
    # "neighbor_analysis",
    # "qerr_stats",
    # "plan_summary",
]

# Runs ONCE after ALL methods
GLOBAL_PROCESSORS=[
    "compare_sampling_grid",
    "compare_sampling_grid_nb",
    # "compare_methods",
    # "merge_all",
    # "build_dashboard",
]

# ===========================================================


def get_resolution_map(method=None):

    method=(
        method
        or
        CURRENT_METHOD
        or
        SAMPLING_METHOD
    )

    cfg=METHOD_CONFIGS[method]
    src=cfg.get(
        "resolution",
        {
            "default":10
        }
    )
    default=src.get(
        "default",
        10
    )

    overrides={
        k:v
        for k,v in src.items()
        if k!="default"
    }

    return (
        default,
        overrides
    )


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