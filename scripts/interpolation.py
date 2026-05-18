# =========================================================
# scripts/interpolation.py
# =========================================================
#
# Generic N-dimensional interpolation framework
#
# Supports:
#
# 1. Ground Truth
# 2. Uniform Sampling
# 3. Random Sampling
# 4. Adaptive Midpoint
# 5. Adaptive Adjacent QERR
# 6. Budget Adaptive
# 7. Error Estimation
# 8. Curvature Sampling
#
# Works for:
# - 1D
# - 2D
# - ND
#
# Plotting:
# - 1D plots
# - 2D contour/scatter plots
# - skips plotting for >2D
#
# =========================================================

import os
import json
import random
import warnings

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scipy.interpolate import (
    interp1d,
    LinearNDInterpolator,
    griddata,
)

warnings.filterwarnings("ignore")

# =========================================================
# CONFIG
# =========================================================

GROUND_TRUTH_CSV = "gt_results_mqt8_500/ground_truth.csv"

OUTPUT_DIR = "interpolation_results"

SAMPLE_PERCENT = 0.10

SEED = 42

INTERP_KIND = "linear"

DEBUG = True

random.seed(SEED)
np.random.seed(SEED)

# =========================================================
# HELPERS
# =========================================================

def dbg(msg):
    if DEBUG:
        print(msg, flush=True)

def symmetric_ratio(a, b):

    a = max(float(a), 1e-9)
    b = max(float(b), 1e-9)

    return max(a / b, b / a)

# =========================================================
# LOAD DATA
# =========================================================

df = pd.read_csv(GROUND_TRUTH_CSV)

xcols = sorted([
    c for c in df.columns
    if c.startswith("x")
])

if len(xcols) == 0:
    raise RuntimeError("No x-columns found")

print("\n================================================")
print("Detected dimensions")
print("================================================")
print(xcols)

# =========================================================
# FEATURES
# =========================================================

X = df[xcols].values.astype(float)

# runtime_mean preferred
if "runtime_mean" in df.columns:
    y = df["runtime_mean"].values.astype(float)
elif "runtime" in df.columns:
    y = df["runtime"].values.astype(float)
else:
    raise RuntimeError("No runtime column found")

n = len(df)
dim = X.shape[1]

print(f"\nPoints      : {n}")
print(f"Dimensions  : {dim}")


# =========================================================
# ND-safe minimum budget
# =========================================================

MIN_BUDGET = max(
    5,
    2 * dim + 1,
    dim + 2
)

BUDGET = max(
    MIN_BUDGET,
    int(SAMPLE_PERCENT * n)
)

BUDGET = min(BUDGET, n)

print(f"Budget      : {BUDGET}")

# =========================================================
# OUTPUT
# =========================================================

os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================================================
# Ensure ND sample diversity
# =========================================================

def ensure_nd_coverage(sample_idx):

    sample_idx = list(sorted(set(sample_idx)))

    # -----------------------------------------------------
    # 1D needs no fixing
    # -----------------------------------------------------

    if dim == 1:
        return sample_idx

    # -----------------------------------------------------
    # need enough points
    # -----------------------------------------------------

    target = max(
        dim + 2,
        2 * dim + 1
    )

    remaining = list(
        set(range(n)) - set(sample_idx)
    )

    random.shuffle(remaining)

    # -----------------------------------------------------
    # keep adding points until:
    # - enough samples
    # - rank becomes full dimensional
    # -----------------------------------------------------

    while (
        len(sample_idx) < target
    ):

        if len(remaining) == 0:
            break

        sample_idx.append(
            remaining.pop()
        )

    # -----------------------------------------------------
    # ensure geometric rank
    # -----------------------------------------------------

    while True:

        pts = X[sample_idx]

        centered = pts - pts.mean(axis=0)

        rank = np.linalg.matrix_rank(centered)

        # full dimensional
        if rank >= dim:
            break

        if len(remaining) == 0:
            break

        sample_idx.append(
            remaining.pop()
        )

    return sorted(list(set(sample_idx)))

# =========================================================
# Robust interpolation
# =========================================================

def interpolate_surface(
    sample_idx,
):

    sample_idx = ensure_nd_coverage(
        sample_idx
    )

    sample_points = X[sample_idx]
    sample_values = y[sample_idx]

    # =====================================================
    # 1D
    # =====================================================

    if dim == 1:

        sx = sample_points[:, 0]

        order = np.argsort(sx)

        sx = sx[order]
        sy = sample_values[order]

        sx_unique, unique_idx = np.unique(
            sx,
            return_index=True
        )

        sy_unique = sy[unique_idx]

        f = interp1d(
            sx_unique,
            sy_unique,
            kind=INTERP_KIND,
            fill_value="extrapolate",
            assume_sorted=True
        )

        pred = f(X[:, 0])

        return pred

    # =====================================================
    # ND
    # =====================================================

    # -----------------------------------------------------
    # need minimum points
    # -----------------------------------------------------

    min_points = dim + 1

    if len(sample_points) < min_points:

        dbg(
            f"[WARN] insufficient points for "
            f"{dim}D interpolation "
            f"({len(sample_points)} < {min_points})"
        )

        pred = griddata(
            sample_points,
            sample_values,
            X,
            method="nearest"
        )

        return pred

    # -----------------------------------------------------
    # try linear interpolation
    # -----------------------------------------------------

    try:

        interp = LinearNDInterpolator(
            sample_points,
            sample_values,
            fill_value=np.nan,
            rescale=True
        )

        pred = interp(X)

        nan_mask = np.isnan(pred)

        # fallback nearest for NaNs
        if np.any(nan_mask):

            pred[nan_mask] = griddata(
                sample_points,
                sample_values,
                X[nan_mask],
                method="nearest"
            )

        return pred

    # -----------------------------------------------------
    # QHull failed
    # -----------------------------------------------------

    except Exception as e:

        dbg(
            f"[WARN] LinearNDInterpolator failed: {e}"
        )

        dbg(
            "[WARN] Falling back to nearest neighbor"
        )

        pred = griddata(
            sample_points,
            sample_values,
            X,
            method="nearest"
        )

        return pred

# =========================================================
# Save interpolation results
# =========================================================

def save_method(
    method_name,
    sample_idx,
    pred,
):

    method_dir = os.path.join(
        OUTPUT_DIR,
        method_name
    )

    os.makedirs(
        method_dir,
        exist_ok=True
    )

    # -----------------------------------------------------
    # prediction dataframe
    # -----------------------------------------------------

    pred_df = pd.DataFrame()

    # dimensions
    for i, col in enumerate(xcols):

        pred_df[col] = X[:, i]

    pred_df["y_true"] = y
    pred_df["y_pred"] = pred

    pred_df["abs_error"] = np.abs(
        pred_df["y_true"]
        - pred_df["y_pred"]
    )

    pred_df["q_error"] = np.maximum(
        pred_df["y_true"]
        / np.maximum(pred_df["y_pred"], 1e-9),

        pred_df["y_pred"]
        / np.maximum(pred_df["y_true"], 1e-9)
    )

    # -----------------------------------------------------
    # sampled points
    # -----------------------------------------------------

    pred_df["is_sampled"] = 0

    pred_df["sample_order"] = -1

    for order, idx in enumerate(sample_idx):

        pred_df.loc[idx, "is_sampled"] = 1

        pred_df.loc[idx, "sample_order"] = order

    # -----------------------------------------------------
    # sort
    # -----------------------------------------------------

    pred_df = pred_df.sort_values(
        xcols
    ).reset_index(drop=True)

    # -----------------------------------------------------
    # save predictions
    # -----------------------------------------------------

    pred_df.to_csv(
        os.path.join(
            method_dir,
            "predictions.csv"
        ),
        index=False
    )

    # -----------------------------------------------------
    # sampled points only
    # -----------------------------------------------------

    samples_df = pred_df[
        pred_df["is_sampled"] == 1
    ].copy()

    samples_df.to_csv(
        os.path.join(
            method_dir,
            "samples.csv"
        ),
        index=False
    )

    # -----------------------------------------------------
    # metadata
    # -----------------------------------------------------

    metadata = {

        "method": method_name,

        "budget": int(len(sample_idx)),

        "dimension": int(dim),

        "num_points": int(n),

        "sample_fraction": float(
            len(sample_idx) / n
        ),
    }

    with open(
        os.path.join(
            method_dir,
            "metadata.json"
        ),
        "w"
    ) as f:

        json.dump(
            metadata,
            f,
            indent=2
        )

    print(
        f"Saved: {method_name}"
    )

# =========================================================
# 1. GROUND TRUTH
# =========================================================

save_method(
    "ground_truth",
    list(range(n)),
    y.copy()
)

# =========================================================
# 2. UNIFORM SAMPLING
# =========================================================

if dim == 1:

    uniform_idx = np.linspace(
        0,
        n - 1,
        BUDGET,
        dtype=int
    )

else:

    # -----------------------------------------------------
    # ND-safe uniform random coverage
    # -----------------------------------------------------

    uniform_idx = random.sample(
        range(n),
        BUDGET
    )

uniform_idx = ensure_nd_coverage(
    uniform_idx
)

pred_uniform = interpolate_surface(
    uniform_idx
)

save_method(
    "uniform",
    uniform_idx,
    pred_uniform
)

# =========================================================
# 3. RANDOM
# =========================================================

random_idx = sorted(
    random.sample(
        range(n),
        BUDGET
    )
)

pred_random = interpolate_surface(
    random_idx
)

save_method(
    "random",
    random_idx,
    pred_random
)

# =========================================================
# 4. ADAPTIVE MIDPOINT
# =========================================================

mid_idx = [0, n - 1]

while len(mid_idx) < BUDGET:

    mid_idx = sorted(mid_idx)

    best_gap = -1
    best_pair = None

    for i in range(len(mid_idx) - 1):

        a = mid_idx[i]
        b = mid_idx[i + 1]

        gap = b - a

        if gap <= 1:
            continue

        if gap > best_gap:
            best_gap = gap
            best_pair = (a, b)

    if best_pair is None:
        break

    a, b = best_pair

    new_idx = (a + b) // 2

    if new_idx in mid_idx:
        break

    mid_idx.append(new_idx)

mid_idx = sorted(mid_idx)[:BUDGET]

mid_idx = ensure_nd_coverage(
    mid_idx
)

pred_mid = interpolate_surface(
    mid_idx
)

save_method(
    "adaptive_midpoint",
    mid_idx,
    pred_mid
)

# =========================================================
# 5. ADAPTIVE ADJACENT QERR
# =========================================================

adj_idx = [0, n // 2, n - 1]

while len(adj_idx) < BUDGET:

    adj_idx = sorted(adj_idx)

    best_score = -1
    best_pair = None

    for i in range(len(adj_idx) - 1):

        a = adj_idx[i]
        b = adj_idx[i + 1]

        q = symmetric_ratio(
            y[a],
            y[b]
        )

        if q > best_score:

            best_score = q
            best_pair = (a, b)

    if best_pair is None:
        break

    a, b = best_pair

    if b - a <= 1:
        break

    new_idx = (a + b) // 2

    if new_idx in adj_idx:
        break

    adj_idx.append(new_idx)

adj_idx = sorted(adj_idx)[:BUDGET]

adj_idx = ensure_nd_coverage(
    adj_idx
)

pred_adj = interpolate_surface(
    adj_idx
)

save_method(
    "adaptive_adjacent_qerr",
    adj_idx,
    pred_adj
)

# =========================================================
# 6. BUDGET ADAPTIVE
# =========================================================

budget_idx = [0, n - 1]

while len(budget_idx) < BUDGET:

    pred_partial = interpolate_surface(
        budget_idx
    )

    best_score = -1
    best_new = None

    unsampled = list(
        set(range(n)) - set(budget_idx)
    )

    if len(unsampled) == 0:
        break

    for idx in unsampled:

        pred_val = pred_partial[idx]

        nearest = min(
            budget_idx,
            key=lambda j: np.linalg.norm(
                X[idx] - X[j]
            )
        )

        score = symmetric_ratio(
            pred_val,
            y[nearest]
        )

        if score > best_score:

            best_score = score
            best_new = idx

    if best_new is None:
        break

    budget_idx.append(best_new)

budget_idx = sorted(
    budget_idx
)[:BUDGET]

budget_idx = ensure_nd_coverage( budget_idx )

pred_budget = interpolate_surface(
    budget_idx
)

save_method(
    "budget_adaptive",
    budget_idx,
    pred_budget
)

# =========================================================
# 7. ERROR ESTIMATION
# =========================================================

err_idx = [0, n - 1]

while len(err_idx) < BUDGET:

    pred_partial = interpolate_surface(
        err_idx
    )

    best_error = -1
    best_new = None

    unsampled = list(
        set(range(n)) - set(err_idx)
    )

    for idx in unsampled:

        err = abs(
            pred_partial[idx] - y[idx]
        )

        if err > best_error:

            best_error = err
            best_new = idx

    if best_new is None:
        break

    err_idx.append(best_new)

err_idx = sorted(
    err_idx
)[:BUDGET]

err_idx = ensure_nd_coverage( err_idx )

pred_err = interpolate_surface(
    err_idx
)

save_method(
    "error_estimation",
    err_idx,
    pred_err
)

# =========================================================
# 8. CURVATURE SAMPLING
# =========================================================

curv_idx = sorted(list(set([
    0,
    n // 3,
    2 * n // 3,
    n - 1
])))

while len(curv_idx) < BUDGET:

    best_score = -1
    best_new = None

    for i in range(1, len(curv_idx) - 1):

        a = curv_idx[i - 1]
        b = curv_idx[i]
        c = curv_idx[i + 1]

        curvature = abs(
            y[c] - 2 * y[b] + y[a]
        )

        if curvature > best_score:

            best_score = curvature

            left_mid = (a + b) // 2
            right_mid = (b + c) // 2

            if (b - a) >= (c - b):
                best_new = left_mid
            else:
                best_new = right_mid

    if best_new is None:
        break

    if best_new in curv_idx:
        break

    curv_idx.append(best_new)

curv_idx = sorted(curv_idx)[:BUDGET]

curv_idx = ensure_nd_coverage( curv_idx )

pred_curv = interpolate_surface(
    curv_idx
)

save_method(
    "curvature_sampling",
    curv_idx,
    pred_curv
)

# =========================================================
# PLOTTING
# =========================================================

# ---------------------------------------------------------
# 1D
# ---------------------------------------------------------

if dim == 1:

    methods = [
        ("ground_truth", y, list(range(n))),
        ("uniform", pred_uniform, uniform_idx),
        ("random", pred_random, random_idx),
        ("adaptive_midpoint", pred_mid, mid_idx),
        ("adaptive_adjacent_qerr", pred_adj, adj_idx),
        ("budget_adaptive", pred_budget, budget_idx),
        ("error_estimation", pred_err, err_idx),
        ("curvature_sampling", pred_curv, curv_idx),
    ]

    xvals = X[:, 0]

    order = np.argsort(xvals)

    x_sorted = xvals[order]
    y_sorted = y[order]

    # =====================================================
    # individual plots
    # =====================================================

    for method_name, pred, sample_idx in methods:

        plt.figure(figsize=(14, 7))

        pred_sorted = pred[order]

        # ---------------------------------------------
        # ground truth
        # ---------------------------------------------

        plt.plot(
            x_sorted,
            y_sorted,
            lw=3,
            label="Ground Truth"
        )

        # ---------------------------------------------
        # prediction
        # ---------------------------------------------

        plt.plot(
            x_sorted,
            pred_sorted,
            '--',
            lw=2,
            label=method_name
        )

        # ---------------------------------------------
        # sampled points colored by order
        # ---------------------------------------------

        sx = X[sample_idx, 0]
        sy = y[sample_idx]

        sorder = np.argsort(sx)

        sample_orders = np.arange(
            len(sample_idx)
        )

        scatter = plt.scatter(
            sx[sorder],
            sy[sorder],
            c=sample_orders[sorder],
            s=100,
            cmap="viridis",
            edgecolors="black",
            label="Samples"
        )

        plt.colorbar(
            scatter,
            label="Sample Order"
        )


        # ---------------------------------------------
        # cosmetics
        # ---------------------------------------------

        plt.xlabel(xcols[0])

        plt.ylabel("runtime")

        plt.title(
            f"1D Interpolation - {method_name}"
        )

        plt.grid(True)

        plt.legend()

        plt.tight_layout()

        out_file = os.path.join(
            OUTPUT_DIR,
            f"{method_name}_1d.png"
        )

        plt.savefig(out_file)

        plt.close()

    print("Saved separate 1D plots")

# ---------------------------------------------------------
# 2D
# ---------------------------------------------------------

elif dim == 2:

    methods = [
        ("ground_truth", y, list(range(n))),
        ("uniform", pred_uniform, uniform_idx),
        ("random", pred_random, random_idx),
        ("adaptive_midpoint", pred_mid, mid_idx),
        ("adaptive_adjacent_qerr", pred_adj, adj_idx),
        ("budget_adaptive", pred_budget, budget_idx),
        ("error_estimation", pred_err, err_idx),
        ("curvature_sampling", pred_curv, curv_idx),
    ]

    for name, pred, sample_idx in methods:

        plt.figure(figsize=(10, 8))

        plt.tricontourf(
            X[:, 0],
            X[:, 1],
            pred,
            levels=20
        )

        plt.colorbar()

        # -----------------------------------------------------
        # sampled points
        # -----------------------------------------------------

        sample_points = X[sample_idx]

        sample_orders = np.arange(
            len(sample_idx)
        )

        scatter = plt.scatter(
            sample_points[:, 0],
            sample_points[:, 1],
            c=sample_orders,
            cmap="viridis",
            s=80,
            edgecolors="black"
        )

        plt.colorbar(
            scatter,
            label="Sample Order"
        )


        plt.xlabel(xcols[0])
        plt.ylabel(xcols[1])

        plt.title(name)

        plt.tight_layout()

        plt.savefig(
            os.path.join(
                OUTPUT_DIR,
                f"{name}_2d.png"
            )
        )

        plt.close()

    print("Saved 2D plots")

# ---------------------------------------------------------
# >2D
# ---------------------------------------------------------

else:

    print(
        "\nSkipping plotting for dimension > 2"
    )

print("\n================================================")
print("DONE")
print("================================================")