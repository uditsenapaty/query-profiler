#!/usr/bin/env python3
# =========================================================
# scripts/bo_interpolation.py
# =========================================================
# Bayesian Optimization used as an ONLINE SAMPLER to discover
# high-qerr (boundary) regions for a FIXED query template on a
# FIXED database (predicate values are the only variables).
#
# Instance = axis-neighbour pair of grid points.  Label = qerr.
#
# Input representations (Rep A "pair" is the default / first):
#   A "pair"        : input (P1, P2)              -> feature [P1 , P2]
#   B "point"       : input P (det. neighbour)    -> feature [P]  (H+V share X)
#   B "point_split" : input P, one BO PER AXIS    -> feature [P], no collision
#
# For every GP kernel:  rbf, matern12, matern32, matern52, rquad.
# Baselines (like interpolation.py): ground_truth, random, uniform_stride.
#
# BUDGET = 10 % of the total pair instances.
# Acquisitions (every one, per kernel): ucb, ei, pi, sigma, ts (thompson)
# — surrogate refit after every new observation (online).
#
# Output (per method dir):
#   {method_dir}/bo_interpolation_results/<method>/{predictions.csv,metadata.json}
#
# Runs over every qt*/m* under a gt_results_* root (default root
# taken from config_gt resolution).
#
# Usage:
#   python scripts/bo_interpolation.py                       # default root from config
#   python scripts/bo_interpolation.py gt_results_sf1_10x10_s1q0        # a whole root
#   python scripts/bo_interpolation.py gt_results_sf1_10x10_s1q0/qt8/m0 # one method dir
# =========================================================

import os
import re
import sys
import json
import random
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from scipy.interpolate import LinearNDInterpolator, griddata
from scipy.stats import norm

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import (
    RBF, Matern, RationalQuadratic, ConstantKernel as C, WhiteKernel,
)

warnings.filterwarnings("ignore")

import config_gt


# --------------------------------------------------------- config
BUDGET_PERCENT  = 0.10                    # 10 % of total pair instances
KAPPA           = 2.0                     # UCB exploration weight
SEED            = 42
REPRESENTATIONS = ["pair", "point", "point_split"]   # "pair" (Rep A) is default / first
KERNELS         = ["rbf", "matern12", "matern32", "matern52", "rquad"]
ACQUISITIONS    = ["ucb", "ei", "pi", "sigma", "ts"]   # every acquisition, per kernel

random.seed(SEED)
np.random.seed(SEED)


# --------------------------------------------------------- helpers
def symmetric_ratio(a, b):
    a = max(float(a), 1e-9); b = max(float(b), 1e-9)
    return max(a / b, b / a)


def make_gp(kernel_name):
    """A GaussianProcessRegressor with the requested kernel (MLE-tuned HPs)."""
    base = {
        "rbf":      RBF(1.0, (1e-2, 1e2)),
        "matern12": Matern(1.0, (1e-2, 1e2), nu=0.5),
        "matern32": Matern(1.0, (1e-2, 1e2), nu=1.5),
        "matern52": Matern(1.0, (1e-2, 1e2), nu=2.5),
        "rquad":    RationalQuadratic(length_scale=1.0, alpha=1.0),
    }[kernel_name]
    kernel = C(1.0, (1e-2, 1e2)) * base + WhiteKernel(1e-3, (1e-6, 1e1))
    return GaussianProcessRegressor(
        kernel=kernel, normalize_y=True,
        n_restarts_optimizer=0, random_state=SEED,
    )


def build_pairs(df):
    """Grid → axis-neighbour pairs with their true q-errors."""
    xcols = sorted([c for c in df.columns if re.fullmatch(r"x\d+", c)])
    if not xcols:
        raise RuntimeError("no x-columns (expected x1, x2, …)")
    ycol = "runtime_mean" if "runtime_mean" in df.columns else "runtime"
    if ycol not in df.columns:
        raise RuntimeError("no runtime column")

    g      = df.groupby(xcols, as_index=False)[ycol].mean()
    Xgrid  = g[xcols].values.astype(float)
    ygrid  = g[ycol].values.astype(float)
    dim    = len(xcols)
    axes   = [np.array(sorted(g[c].unique())) for c in xcols]
    idx_of = {tuple(r): i for i, r in enumerate(Xgrid)}

    axis_l, ia_l, ib_l = [], [], []
    for i, row in enumerate(Xgrid):
        for ax in range(dim):
            pos = np.searchsorted(axes[ax], row[ax])
            if pos + 1 >= len(axes[ax]):
                continue
            nb = row.copy(); nb[ax] = axes[ax][pos + 1]
            j  = idx_of.get(tuple(nb))
            if j is not None:
                axis_l.append(ax); ia_l.append(i); ib_l.append(j)

    axis_arr = np.array(axis_l); ia = np.array(ia_l); ib = np.array(ib_l)
    mid  = (Xgrid[ia] + Xgrid[ib]) / 2.0
    qerr = np.array([symmetric_ratio(ygrid[a], ygrid[b]) for a, b in zip(ia, ib)])
    return dict(xcols=xcols, Xgrid=Xgrid, dim=dim, n_grid=len(Xgrid),
                axis=axis_arr, ia=ia, ib=ib, mid=mid, qerr=qerr, P=len(ia))


def make_features(rep, D):
    """
    Features are exactly the specified BO inputs — no extra encoding.
    rep "pair"  → [P1 , P2]   — Rep A: input is exactly the pair (P1, P2)
    rep "point" → [P1]        — Rep B: input is exactly the point P
    rep "mid"   → midpoint     — baselines' linear interp only
    """
    if rep == "pair":
        return np.hstack([D["Xgrid"][D["ia"]], D["Xgrid"][D["ib"]]])
    if rep == "point":
        return D["Xgrid"][D["ia"]].copy()
    if rep == "mid":
        return D["mid"].copy()
    raise ValueError(rep)


def linear_interp(F, qerr, ids):
    """Linear interpolation (log-qerr) on the sampled pairs → all pairs."""
    sf = F[ids]; sq = np.log(np.maximum(qerr[ids], 1e-9))
    if F.shape[1] == 1:
        from scipy.interpolate import interp1d
        order   = np.argsort(sf[:, 0])
        xu, ui  = np.unique(sf[order, 0], return_index=True)
        f1      = interp1d(xu, sq[order][ui], kind="linear",
                           fill_value="extrapolate", assume_sorted=True)
        return np.maximum(np.exp(f1(F[:, 0])), 1.0)
    try:
        it = LinearNDInterpolator(sf, sq, fill_value=np.nan, rescale=True)
        lp = it(F)
        if np.any(np.isnan(lp)):
            nm = np.isnan(lp)
            lp[nm] = griddata(sf, sq, F[nm], method="nearest")
        return np.maximum(np.exp(lp), 1.0)
    except Exception:
        lp = griddata(sf, sq, F, method="nearest")
        return np.maximum(np.exp(lp), 1.0)


def _acq_score(acq, mu, sd, best):
    """Acquisition score (higher = pick next).  best = max observed log-qerr."""
    if acq == "ucb":
        return mu + KAPPA * sd
    if acq == "sigma":
        return sd.copy()
    z = (mu - best) / np.maximum(sd, 1e-12)
    if acq == "ei":
        return (mu - best) * norm.cdf(z) + sd * norm.pdf(z)
    if acq == "pi":
        return norm.cdf(z)
    raise ValueError(f"unknown acquisition {acq}")


def run_bo(F, qerr, budget, kernel_name, acq, seed_ids):
    """Online GP sampler with the given kernel & acquisition; refit each step."""
    log_q = np.log(np.maximum(qerr, 1e-9))
    Fs    = (F - F.mean(0)) / (F.std(0) + 1e-12)
    ids   = list(dict.fromkeys(int(i) for i in seed_ids))
    step  = 0
    while len(ids) < budget:
        gp = make_gp(kernel_name).fit(Fs[ids], log_q[ids])
        if acq == "ts":                                   # Thompson: sample posterior
            score = gp.sample_y(Fs, n_samples=1, random_state=SEED + step).ravel()
        else:
            mu, sd = gp.predict(Fs, return_std=True)
            score  = _acq_score(acq, mu, sd, float(log_q[ids].max()))
        score[ids] = -np.inf
        ids.append(int(np.argmax(score)))
        step += 1
    gp   = make_gp(kernel_name).fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return ids, pred


def run_bo_axis_split(D, budget, kernel_name, acq):
    """
    Rep B, axis-split: a SEPARATE BO per axis.  Feature is the point P
    (no one-hot); within one axis each P maps to exactly one pair, so there
    is no X-collision.  The 10% budget is divided across axes in proportion
    to their pair counts; predictions are stitched back over all pairs.
    """
    P = D["P"]; dim = D["dim"]
    pred_full = np.ones(P, dtype=float)
    sampled   = []
    for a in range(dim):
        gmask = np.where(D["axis"] == a)[0]         # global pair ids on axis a
        Pa = len(gmask)
        if Pa == 0:
            continue
        ba = min(Pa, max(3, int(round(budget * Pa / P))))
        Fa = D["Xgrid"][D["ia"][gmask]]             # source point P (feature)
        qa = D["qerr"][gmask]
        rng = random.Random(SEED + 1 + a)
        na  = min(ba, max(4, dim + 2))
        seed_local = sorted(rng.sample(range(Pa), na))
        local_ids, pred_a = run_bo(Fa, qa, ba, kernel_name, acq, seed_local)
        pred_full[gmask] = pred_a
        sampled.extend(int(gmask[i]) for i in local_ids)
    return sorted(set(sampled)), pred_full


def save_method(out_dir, name, D, ids, pred, extra=None):
    mdir = out_dir / name
    mdir.mkdir(parents=True, exist_ok=True)
    P = D["P"]; xcols = D["xcols"]

    out = pd.DataFrame({"pair_id": np.arange(P), "axis": D["axis"]})
    for k, c in enumerate(xcols):
        out[f"a_{c}"] = D["Xgrid"][D["ia"], k]
        out[f"b_{c}"] = D["Xgrid"][D["ib"], k]
    out["y_true"]     = D["qerr"]
    out["y_pred"]     = np.maximum(pred, 1.0)
    out["q_error"]    = np.maximum(out.y_true / np.maximum(out.y_pred, 1e-9),
                                   out.y_pred / np.maximum(out.y_true, 1e-9))
    out["is_sampled"] = 0
    out.loc[list(ids), "is_sampled"] = 1
    out.to_csv(mdir / "predictions.csv", index=False)

    ids = list(ids)
    meta = {
        "method"          : name,
        "representation"  : (extra or {}).get("representation", "-"),
        "kernel"          : (extra or {}).get("kernel", "-"),
        "acquisition"     : (extra or {}).get("acquisition", "-"),
        "budget_pairs"    : int(len(ids)),
        "total_pairs"     : int(P),
        "budget_percent"  : float(BUDGET_PERCENT),
        "sample_fraction" : float(len(ids) / P),
        "dimension"       : int(D["dim"]),
        "total_grid_points": int(D["n_grid"]),
        "max_qerr_true"   : float(D["qerr"].max()),
        "max_qerr_found"  : float(D["qerr"][ids].max()),
    }
    with open(mdir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    return meta


# --------------------------------------------------------- per-method-dir run
def run(method_dir):
    method_dir = Path(method_dir)
    csv = method_dir / "ground_truth.csv"
    if not csv.exists():
        print(f"[skip] no ground_truth.csv in {method_dir}")
        return

    D = build_pairs(pd.read_csv(csv))
    P = D["P"]
    if P == 0:
        print(f"[skip] no axis-neighbour pairs in {method_dir}")
        return

    dim    = D["dim"]
    budget = min(P, max(max(5, 2 * dim + 2), int(BUDGET_PERCENT * P)))

    out_dir = method_dir / "bo_interpolation_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    # one common seed (pair ids) reused by every BO run → fair comparison
    rng      = random.Random(SEED)
    n_seed   = min(budget, max(6, 2 * dim + 2))
    seed_ids = sorted(rng.sample(range(P), n_seed))

    F_mid = make_features("mid", D)
    feats = {"pair": make_features("pair", D), "point": make_features("point", D)}

    print(f"\n=== {method_dir}  (pairs={P}, budget={budget} = "
          f"{100*budget/P:.0f}%, seed={n_seed}) ===")

    # baselines
    save_method(out_dir, "ground_truth", D, list(range(P)), D["qerr"].copy())
    r_ids = sorted(rng.sample(range(P), budget))
    save_method(out_dir, "random", D, r_ids, linear_interp(F_mid, D["qerr"], r_ids))
    s_ids = sorted(set(np.linspace(0, P - 1, budget, dtype=int).tolist()))
    save_method(out_dir, "uniform_stride", D, s_ids,
                linear_interp(F_mid, D["qerr"], s_ids))

    # BO: representation × kernel × acquisition
    for rep in REPRESENTATIONS:
        for kern in KERNELS:
            best_found = 0.0
            for acq in ACQUISITIONS:
                if rep == "point_split":
                    ids, pred = run_bo_axis_split(D, budget, kern, acq)
                else:
                    ids, pred = run_bo(feats[rep], D["qerr"], budget, kern, acq, seed_ids)
                m = save_method(out_dir, f"bo_{rep}_{kern}_{acq}", D, ids, pred,
                                extra={"representation": rep, "kernel": kern,
                                       "acquisition": acq})
                best_found = max(best_found, m["max_qerr_found"])
            print(f"  bo_{rep:11s}_{kern:9s}  best max_found over "
                  f"{len(ACQUISITIONS)} acq = {best_found:.2f}/{D['qerr'].max():.2f}")

    print(f"saved: {out_dir}")


# --------------------------------------------------------- root driver
def run_root(gt_root):
    gt_root = Path(gt_root)
    method_csvs = sorted(gt_root.glob("*/*/ground_truth.csv"))
    if not method_csvs:
        print(f"No qt*/m*/ground_truth.csv under {gt_root}")
        return
    print(f"BO interpolation over {len(method_csvs)} method dirs in {gt_root}")
    for csv in method_csvs:
        run(csv.parent)
    print(f"\nDONE — {gt_root}")


def _default_root():
    res = config_gt.get_query_resolution(config_gt.QUERIES[0], config_gt.RUN_METHODS[0])
    return config_gt.get_main_dir(res)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg:
        t = Path(arg)
        if (t / "ground_truth.csv").exists():
            run(t)
        else:
            run_root(t)
    else:
        run_root(_default_root())
