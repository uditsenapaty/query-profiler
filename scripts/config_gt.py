#config_gt.py
from pathlib import Path

# =========================================================
# 1. Database Configs
# =========================================================
DATABASE_NAME = "tpch"
PASSWORD = "112358"
USER = "postgres"
HOST = "localhost"
SF = "sf1"

# Imports
# Plan Comparator
COMPARATOR_MODULE = "scripts/automated_script/comparator.py"
PLAN_HASH_METHOD = "structural_hash_md5"

# =========================================================
# 2. SQL source 
# =========================================================

# OPTIONAL : Input if run for 1 QUERY ONLY using "build_gt.py"!!
# For MULTIPLE QUERY runs together use : "run_multi_gt.py"!!
QUERY="qt8"

QUERY_SQL_PATH=(
    Path(__file__).resolve().parent
    / "automated_script"
    / "queries"
    / f"{QUERY}.sql"
)

# =========================================================
# 3. Method registry
# =========================================================

METHOD_CONFIGS = {

    "m0":{
        "sampler":"sampler_data_m0",
        "resolution":{
            "default":10,
            # "p1":100
        }
    },

    "m1":{
        "sampler":"sampler_selectivity_m1",
        "resolution":{
            "default":10,
        }
    },

    "m2":{

        "sampler":"sampler_selectivity_m2",
        "resolution":{
            "default":10,
        }
    },

    # "m3":{

    #     "sampler":"sampler_selectivity_m3",
    #     "resolution":{
    #         "default":10,
    #     }
    # },

}

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
elif SAMPLING_METHOD != None :
    RUN_METHODS = [SAMPLING_METHOD]
else:
    RUN_METHODS = ["m0", "m1", "m2", "m3"]


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

MAIN_DIR=Path( f"gt_results_{SF}_{QUERY}" )

RESULTS_DIR=None
PLANS_DIR=None
PLAN_TREES_DIR=None
TRACES_DIR=None
RESULTS_FILENAME = "ground_truth.csv"
METADATA_FILENAME = "gt_metadata.json"

def get_method_dir(method, resolution):
    return ( MAIN_DIR / f"{resolution}x{resolution}" / f"{method}" )

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
    "grid_overview",
    "merge_qerr_instances",
    "merge_qerr_instances_nb",
    "instance_grid_maps",
    "summarised_instances",
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