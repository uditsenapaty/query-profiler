#!/usr/bin/env python3
# =========================================================
# scripts/interpolation.py — Unified pair-q-error framework
# =========================================================
#
# Instance = axis-neighbor pair of grid points.
# Feature  = midpoint coordinates + axis one-hot (dim > 1).
# Label    = qerr(runtime_a, runtime_b)  ≥ 1.
#
# Budget: BUDGET_PERCENT * total_pairs  (default 10 %).
#
# All methods observe ONLY the q-errors of pairs they
# explicitly sample.  No peeking at unsampled true values.
#
# Methods
# ───────
#  Passive (given pre-computed uniform stride seed):
#   1  ground_truth          all pairs — baseline
#   2  random                iid random pairs → linear interp
#   3  uniform_stride        stride pairs → linear interp
#   4  gpr_fixed             uniform seed → Matern 5/2 GPR (one-shot)
#
#  Active (model picks its own budget pairs):
#   5  bo_generic_sigma      Matern 5/2, σ  acquisition
#   6  bo_generic_ucb        Matern 5/2, UCB acquisition
#   7  bo_generic_ei         Matern 5/2, EI  acquisition
#   8  ottertune_max         OtterTune exact kernel, hunts max qerr
#   9  ottertune_reconstruct OtterTune exact kernel, uncertainty sampling
#
# Removed (cheat or meaningless):
#   error_estimation     — uses true y at unsampled points
#   budget_adaptive      — uses true y at nearest sampled point as proxy
#   adaptive_midpoint    — index-bisection = uniform on sorted pairs
#   curvature_sampling   — 1-D only, undefined on pair feature space
#   adaptive_adjacent_qerr — meaningful only in 1-D row order
# =========================================================

import os
import re
import json
import random
import warnings
from math import erf, sqrt, pi, exp as _mexp

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scipy.interpolate import LinearNDInterpolator, griddata

warnings.filterwarnings("ignore")

# =========================================================
# CONFIG
# =========================================================

GROUND_TRUTH_CSV = "gt_results_sf1_10x10_s1q2/qt5/m0/ground_truth.csv"
OUTPUT_DIR       = "gt_results_sf1_10x10_s1q2/qt5/m0/interpolation_results"

BUDGET_PERCENT   = 0.10   # 10 % of total pair instances
TOP_K_PERCENT    = 0.10   # top-k fraction for smoothness_topk

SEED  = 42
DEBUG = True

OTTERTUNE_HP = {
    "GPR_LENGTH_SCALE" : 2.0,
    "GPR_MAGNITUDE"    : 1.0,
    "GPR_RIDGE"        : 1.0,
    "GPR_EPS"          : 0.001,
    "GPR_LEARNING_RATE": 0.01,
    "GPR_MAX_ITER"     : 100,
    "GPR_UCB_SCALE"    : 0.2,
    "NUM_SAMPLES"      : 30,
    "TOP_NUM_CONFIG"   : 10,
    "LHS_BOOTSTRAP"    : 10,
}

random.seed(SEED)
np.random.seed(SEED)
_rng = np.random.default_rng(SEED)

# =========================================================
# HELPERS
# =========================================================

def dbg(msg):
    if DEBUG:
        print(msg, flush=True)

def symmetric_ratio(a, b):
    a = max(float(a), 1e-9); b = max(float(b), 1e-9)
    return max(a / b, b / a)

def _norm_pdf(z): return _mexp(-0.5 * z * z) / sqrt(2 * pi)
def _norm_cdf(z): return 0.5 * (1.0 + erf(z / sqrt(2.0)))

def _get_beta_td(t, ndim, bound=1.0):
    bt = 2.0 * np.log(float(ndim) * t ** 2 * np.pi ** 2 / (6.0 * bound))
    return sqrt(bt) if bt > 0.0 else 0.0


# =========================================================
# LOAD DATA & BUILD PAIR GRID
# =========================================================

df = pd.read_csv(GROUND_TRUTH_CSV)

xcols = sorted([c for c in df.columns if re.fullmatch(r'x\d+', c)])
if not xcols:
    raise RuntimeError("No x-columns found (expected x1, x2, …)")

if "runtime_mean" in df.columns:
    ycol = "runtime_mean"
elif "runtime" in df.columns:
    ycol = "runtime"
else:
    raise RuntimeError("No runtime column found")

print("\n================================================")
print("Detected dimensions:", xcols)
print("================================================")

# collapse duplicate coordinates
g = df.groupby(xcols, as_index=False)[ycol].mean()
Xgrid  = g[xcols].values.astype(float)
ygrid  = g[ycol].values.astype(float)
dim    = len(xcols)
n_grid = len(Xgrid)

axes_vals = [np.array(sorted(g[c].unique())) for c in xcols]
index_of  = {tuple(row): i for i, row in enumerate(Xgrid)}

pairs = []          # (axis, idx_a, idx_b)
for i, row in enumerate(Xgrid):
    for ax in range(dim):
        pos = np.searchsorted(axes_vals[ax], row[ax])
        if pos + 1 >= len(axes_vals[ax]):
            continue
        nb    = row.copy(); nb[ax] = axes_vals[ax][pos + 1]
        j     = index_of.get(tuple(nb))
        if j is not None:
            pairs.append((ax, i, j))

if not pairs:
    raise RuntimeError("No axis-neighbor pairs found — is the CSV a grid?")

axis_arr = np.array([p[0] for p in pairs])
ia       = np.array([p[1] for p in pairs])
ib       = np.array([p[2] for p in pairs])
mid      = (Xgrid[ia] + Xgrid[ib]) / 2.0
qerr_all = np.array([symmetric_ratio(ygrid[a], ygrid[b]) for a, b in zip(ia, ib)])

# features: midpoint + axis one-hot when dim > 1
if dim > 1:
    onehot = np.zeros((len(pairs), dim))
    onehot[np.arange(len(pairs)), axis_arr] = 1.0
    F = np.hstack([mid, onehot])
else:
    F = mid.copy()

P     = len(pairs)   # total pair instances
fdim  = F.shape[1]   # feature dimension

print(f"Grid points  : {n_grid}")
print(f"Pair instances: {P}")
print(f"Feature dim  : {fdim}")

# =========================================================
# BUDGET
# =========================================================

MIN_BUDGET = max(5, fdim + 2)
BUDGET     = max(MIN_BUDGET, int(BUDGET_PERCENT * P))
BUDGET     = min(BUDGET, P)

print(f"Budget       : {BUDGET}  ({100 * BUDGET / P:.1f}% of {P} pairs)")
print()

os.makedirs(OUTPUT_DIR, exist_ok=True)

# save pairs catalog (so users can specify custom seeds)
catalog = pd.DataFrame({"pair_id": np.arange(P), "axis": axis_arr})
for k, c in enumerate(xcols):
    catalog[f"mid_{c}"] = mid[:, k]
    catalog[f"a_{c}"]   = Xgrid[ia, k]
    catalog[f"b_{c}"]   = Xgrid[ib, k]
catalog["qerr_true"] = qerr_all
catalog.to_csv(os.path.join(OUTPUT_DIR, "pairs_catalog.csv"), index=False)


# =========================================================
# Linear interpolation on pair features
# =========================================================

def interp_pairs(sample_ids, pred_all=None):
    """
    Fit LinearNDInterpolator on sampled pairs, predict at all P pairs.
    Falls back to griddata nearest for out-of-hull points.
    If fdim == 1 uses scipy interp1d.
    """
    sf  = F[sample_ids]
    sq  = qerr_all[sample_ids]

    if fdim == 1:
        from scipy.interpolate import interp1d
        order  = np.argsort(sf[:, 0])
        xu, ui = np.unique(sf[order, 0], return_index=True)
        yu     = np.log(sq[order][ui])
        f1     = interp1d(xu, yu, kind="linear",
                          fill_value="extrapolate", assume_sorted=True)
        return np.maximum(np.exp(f1(F[:, 0])), 1.0)

    try:
        interp = LinearNDInterpolator(sf, np.log(np.maximum(sq, 1e-9)),
                                      fill_value=np.nan, rescale=True)
        log_pred = interp(F)
        if np.any(np.isnan(log_pred)):
            nm = np.isnan(log_pred)
            log_pred[nm] = griddata(sf, np.log(np.maximum(sq, 1e-9)),
                                    F[nm], method="nearest")
        return np.maximum(np.exp(log_pred), 1.0)
    except Exception as e:
        dbg(f"[WARN] LinearNDInterpolator failed ({e}); using nearest")
        log_pred = griddata(sf, np.log(np.maximum(sq, 1e-9)), F, method="nearest")
        return np.maximum(np.exp(log_pred), 1.0)


# =========================================================
# GP classes
# =========================================================

class OtterTuneGP:
    """
    OtterTune exact kernel: K = mag*exp(-||dx||/ls) + ridge*I
    Ported from cmu-db/ottertune  analysis/gp_tf.py.
    Fixed hyperparameters — NO MLE.
    """
    def __init__(self, ls=2.0, mag=1.0, ridge=1.0):
        self.ls = ls; self.mag = mag; self.ridge = ridge
        self.Xt = self.K_inv = self.xy_ = None

    @staticmethod
    def _dist(A, B):
        return np.sqrt(np.maximum(
            ((A[:, None, :] - B[None, :, :]) ** 2).sum(-1), 0.0))

    def fit(self, Xt, yt):
        self.Xt  = np.asarray(Xt, float)
        yt       = np.asarray(yt, float).reshape(-1, 1)
        D        = self._dist(self.Xt, self.Xt)
        K        = self.mag * np.exp(-D / self.ls) + self.ridge * np.eye(len(self.Xt))
        self.K_inv = np.linalg.inv(K)
        self.xy_   = self.K_inv @ yt
        return self

    def predict(self, Xtest):
        Xtest = np.atleast_2d(np.asarray(Xtest, float))
        D2    = self._dist(self.Xt, Xtest)
        K2    = self.mag * np.exp(-D2 / self.ls)
        mu    = (K2.T @ self.xy_).ravel()
        v     = np.einsum("ij,ik,kj->j", K2, self.K_inv, K2)
        sig   = np.sqrt(np.maximum(self.mag + self.ridge - v, 1e-12))
        return mu, sig

    def grad_loss_batch(self, Xb, beta, mu_mult=1.0):
        Xb   = np.atleast_2d(np.asarray(Xb, float))
        diff = Xb[:, None, :] - self.Xt[None, :, :]
        r    = np.sqrt(np.maximum((diff ** 2).sum(-1), 1e-12))
        k2   = self.mag * np.exp(-r / self.ls)
        dk2  = (-(k2 / self.ls) / r)[..., None] * diff
        a    = self.xy_.ravel()
        mu   = k2 @ a
        Kik  = k2 @ self.K_inv
        var  = np.maximum(self.mag + self.ridge - np.einsum("mn,mn->m", Kik, k2), 1e-12)
        sig  = np.sqrt(var)
        dmu  = np.einsum("mnd,n->md", dk2, a)
        dvar = -2.0 * np.einsum("mn,mnd->md", Kik, dk2)
        dsig = dvar / (2.0 * sig)[:, None]
        return mu_mult * mu - beta * sig, mu_mult * dmu - beta * dsig


class MaternGP:
    """
    Matern 5/2 GPR, hyperparams (ls, noise) by MLE grid search.
    Operates in log-qerr space.
    """
    def __init__(self):
        self.ls = self.noise = None
        self.Xt = self.alpha = self.Kinv = None
        self.ymean = self.ystd = None

    @staticmethod
    def _k52(r, ls):
        a = sqrt(5.0) * r / ls
        return (1.0 + a + a * a / 3.0) * np.exp(-a)

    def _lml(self, D, yn, ls, noise):
        K = self._k52(D, ls) + noise * np.eye(len(yn))
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return -np.inf
        a = np.linalg.solve(L.T, np.linalg.solve(L, yn))
        return float(-0.5 * yn @ a - np.log(np.diag(L)).sum()
                     - 0.5 * len(yn) * np.log(2 * pi))

    def fit(self, Xt, yt):
        self.Xt  = np.asarray(Xt, float)
        yt       = np.asarray(yt, float).ravel()
        self.ymean, self.ystd = yt.mean(), yt.std() + 1e-12
        yn   = (yt - self.ymean) / self.ystd
        D    = OtterTuneGP._dist(self.Xt, self.Xt)
        best = (-np.inf, 1.0, 1e-4)
        for ls in np.logspace(-1, 1.3, 12):
            for noise in (1e-6, 1e-4, 1e-3, 1e-2, 1e-1):
                lml = self._lml(D, yn, ls, noise)
                if lml > best[0]:
                    best = (lml, ls, noise)
        _, self.ls, self.noise = best
        K = self._k52(D, self.ls) + self.noise * np.eye(len(yn))
        self.Kinv  = np.linalg.inv(K)
        self.alpha = self.Kinv @ yn
        return self

    def predict(self, Xtest, return_std=False):
        Xtest = np.atleast_2d(np.asarray(Xtest, float))
        Ks    = self._k52(OtterTuneGP._dist(self.Xt, Xtest), self.ls)
        mu    = Ks.T @ self.alpha * self.ystd + self.ymean
        if not return_std:
            return mu
        v  = np.einsum("ij,ik,kj->j", Ks, self.Kinv, Ks)
        sd = np.sqrt(np.maximum(1.0 + self.noise - v, 1e-12)) * self.ystd
        return mu, sd


# =========================================================
# LHS maximin seed
# =========================================================

def _maximin_lhs(nsamples, nfeats, n_restarts=10):
    best, best_score = None, -1.0
    for _ in range(n_restarts):
        H = np.empty((nsamples, nfeats))
        for j in range(nfeats):
            perm    = _rng.permutation(nsamples)
            H[:, j] = (perm + _rng.random(nsamples)) / nsamples
        d = OtterTuneGP._dist(H, H)
        np.fill_diagonal(d, np.inf)
        score = d.min()
        if score > best_score:
            best, best_score = H.copy(), score
    return best


def _lhs_seed_pairs(budget):
    """Map LHS unit-cube to nearest distinct pair indices."""
    H  = _maximin_lhs(budget, fdim)
    lo = F.min(0); hi = F.max(0)
    ids = []
    for s_pt in (lo + H * (hi - lo)):
        d = ((F - s_pt) ** 2).sum(1)
        if ids:
            d[ids] = np.inf
        ids.append(int(np.argmin(d)))
    return list(dict.fromkeys(ids))


def _std_F():
    m = F.mean(0); s = F.std(0) + 1e-12
    return (F - m) / s


# =========================================================
# GPR / BO runners  (operate on log-qerr)
# =========================================================

def run_gpr_fixed(seed_ids):
    """Passive: one-shot Matern 5/2 fit on the given uniform seed."""
    Fs    = _std_F()
    log_q = np.log(np.maximum(qerr_all, 1e-9))
    gp    = MaternGP().fit(Fs[seed_ids], log_q[seed_ids])
    pred  = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return list(seed_ids), pred


def run_bo_generic(acq="sigma", kappa=2.0):
    """Active BO with Matern 5/2; acq ∈ {sigma, ucb, ei}."""
    Fs    = _std_F()
    log_q = np.log(np.maximum(qerr_all, 1e-9))
    n_seed = min(max(fdim + 2, 5), BUDGET)
    ids    = _lhs_seed_pairs(n_seed)

    gp = MaternGP()
    while len(ids) < BUDGET:
        gp.fit(Fs[ids], log_q[ids])
        mu, sd = gp.predict(Fs, return_std=True)
        if acq == "sigma":
            score = sd.copy()
        elif acq == "ucb":
            score = mu + kappa * sd
        else:                              # ei
            best  = log_q[ids].max()
            z     = (mu - best) / np.maximum(sd, 1e-12)
            score = ((mu - best) * np.vectorize(_norm_cdf)(z)
                     + sd * np.vectorize(_norm_pdf)(z))
        score[ids] = -np.inf
        ids.append(int(np.argmax(score)))

    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return ids, pred


def run_ottertune(target="max"):
    """
    Exact OtterTune sequential loop on pair instances.

    Mirrors cmu-db/ottertune async_tasks / gp_tf.py:
      - LHS maximin bootstrap                   [gen_lhs_samples]
      - per-iteration StandardScaler on F, log(q) [process_training_data]
      - OtterTune kernel (fixed HPs)
      - candidate starts: NUM_SAMPLES random + TOP_NUM_CONFIG best seen
      - UCB beta grows with t                   [get_beta_td]
      - Adam / GPRGD descent, projected to bounds
      - winner snapped to nearest unsampled pair

    target="max"         hunts the highest-qerr pair (mu_mult=1)
    target="reconstruct" pure uncertainty sampling   (mu_mult=0)
    """
    hp       = OTTERTUNE_HP
    find_max = (target == "max")
    mu_mult  = 1.0 if find_max else 0.0

    ids = _lhs_seed_pairs(min(hp["LHS_BOOTSTRAP"], BUDGET))
    log_q = np.log(np.maximum(qerr_all, 1e-9))

    t = 0
    while len(ids) < BUDGET:
        t += 1

        Fm  = F[ids].mean(0); Fs_std = F[ids].std(0) + 1e-12
        Fs  = (F - Fm) / Fs_std

        lq_s     = log_q[ids]
        ym, ys   = lq_s.mean(), lq_s.std() + 1e-12
        ysc      = (lq_s - ym) / ys
        if find_max:
            ysc = -ysc

        X_lo, X_hi = Fs.min(0), Fs.max(0)
        gp = OtterTuneGP(hp["GPR_LENGTH_SCALE"],
                         hp["GPR_MAGNITUDE"],
                         hp["GPR_RIDGE"]).fit(Fs[ids], ysc)

        starts = _rng.random((hp["NUM_SAMPLES"], fdim)) * (X_hi - X_lo) + X_lo
        top    = []
        for j in np.argsort(ysc)[:hp["TOP_NUM_CONFIG"]]:
            xj  = Fs[ids[j]].copy()
            eps = (-hp["GPR_EPS"] if np.sum((X_hi - xj) ** 2) < 1e-3
                   else hp["GPR_EPS"])
            top.append(xj + eps)
        if top:
            starts = np.vstack([starts] + top)

        beta = hp["GPR_UCB_SCALE"] * _get_beta_td(t, fdim)

        Xb  = starts.copy()
        m_t = np.zeros_like(Xb); v_t = np.zeros_like(Xb)
        lr, eps_a = hp["GPR_LEARNING_RATE"], 1e-8
        loss0, _  = gp.grad_loss_batch(Xb, beta, mu_mult)
        best_l = loss0.copy(); best_X = Xb.copy()
        for it in range(1, hp["GPR_MAX_ITER"] + 1):
            loss, g  = gp.grad_loss_batch(Xb, beta, mu_mult)
            improved = loss < best_l
            best_l[improved] = loss[improved]
            best_X[improved] = Xb[improved]
            m_t = 0.9   * m_t + 0.1   * g
            v_t = 0.999 * v_t + 0.001 * g * g
            mh  = m_t / (1 - 0.9  ** it)
            vh  = v_t / (1 - 0.999 ** it)
            Xb  = np.clip(Xb - lr * mh / (np.sqrt(vh) + eps_a), X_lo, X_hi)
        best_x = best_X[int(np.argmin(best_l))]

        dist = ((Fs - best_x) ** 2).sum(1)
        dist[ids] = np.inf
        ids.append(int(np.argmin(dist)))

    # final prediction
    Fm  = F[ids].mean(0); Fs_std = F[ids].std(0) + 1e-12
    Fs  = (F - Fm) / Fs_std
    lq_s     = log_q[ids]
    ym, ys   = lq_s.mean(), lq_s.std() + 1e-12
    ysc      = (lq_s - ym) / ys
    if find_max:
        ysc = -ysc
    gp = OtterTuneGP(hp["GPR_LENGTH_SCALE"],
                     hp["GPR_MAGNITUDE"],
                     hp["GPR_RIDGE"]).fit(Fs[ids], ysc)
    mu, _ = gp.predict(Fs)
    if find_max:
        mu = -mu
    pred = np.exp(mu * ys + ym)
    return ids, np.maximum(pred, 1.0)


# =========================================================
# Smoothness-objective runners
# =========================================================

def run_smoothness_max():
    """
    Estimate  S_max = max_{(i,j) in N} q(i,j).

    Uses GP-UCB with the theoretically grounded adaptive beta:
      beta_t = sqrt(2 * log(P * t^2 * pi^2 / 6))   [Srinivas et al. 2010]
    Beta grows with t, concentrating samples near the maximum,
    unlike bo_generic_ucb whose kappa is fixed.
    Final estimate: max of posterior means over all pairs.
    """
    Fs    = _std_F()
    log_q = np.log(np.maximum(qerr_all, 1e-9))
    n_seed = min(max(fdim + 2, 5), BUDGET)
    ids    = _lhs_seed_pairs(n_seed)
    t      = len(ids)

    gp = MaternGP()
    while len(ids) < BUDGET:
        t += 1
        gp.fit(Fs[ids], log_q[ids])
        mu, sd   = gp.predict(Fs, return_std=True)
        beta_t   = sqrt(2.0 * np.log(P * t * t * pi * pi / 6.0))
        score    = mu + beta_t * sd
        score[ids] = -np.inf
        ids.append(int(np.argmax(score)))

    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return ids, pred


def run_smoothness_avg():
    """
    Estimate  S_avg = (1/|N|) * sum_{(i,j) in N} q(i,j).

    Uses Bayesian Quadrature (BQ) acquisition [MacKay 1992]:
      acq(p) = (sum_q k*(q,p))^2 / sigma*^2(p)

    where k*(q,p) is the posterior cross-covariance between pair q and
    candidate p.  This minimises the posterior variance of the mean
    estimate E[S_avg], directing samples to the most 'central' regions.

    Differs from bo_generic_sigma (which targets max single-point sigma):
    sigma picks the locally most uncertain pair; BQ picks the pair most
    correlated with the whole space.

    Final estimate: mean of posterior means over all pairs.
    """
    Fs    = _std_F()
    log_q = np.log(np.maximum(qerr_all, 1e-9))
    n_seed = min(max(fdim + 2, 5), BUDGET)
    ids    = _lhs_seed_pairs(n_seed)
    ids_set = set(ids)

    gp = MaternGP()
    while len(ids) < BUDGET:
        gp.fit(Fs[ids], log_q[ids])

        candidates = [i for i in range(P) if i not in ids_set]
        if not candidates:
            break
        Fs_cand = Fs[candidates]                              # (n_c, fdim)

        # k(candidates, all): prior kernel from each candidate to every pair
        K_cand_all = gp._k52(OtterTuneGP._dist(Fs_cand, Fs), gp.ls)  # (n_c, P)
        sum_k_prior = K_cand_all.sum(1)                      # (n_c,) = sum_q k(q,p)

        # k(sampled, candidates): shape (n_s, n_c)
        Ks_cand = gp._k52(OtterTuneGP._dist(gp.Xt, Fs_cand), gp.ls)

        # k(sampled, all): shape (n_s, P)
        Ks_all  = gp._k52(OtterTuneGP._dist(gp.Xt, Fs), gp.ls)

        # Correction: sum_q [k(q, Xs) Kinv k(Xs, p)] for each candidate p
        # = (sum_k_all_s @ Kinv) @ Ks_cand
        sum_k_all_s = Ks_all.sum(1)                          # (n_s,)
        correction  = (sum_k_all_s @ gp.Kinv) @ Ks_cand     # (n_c,)

        # Posterior cross-covariance sum: sum_q k*(q, p)
        sum_post_cov = sum_k_prior - correction              # (n_c,)

        # Posterior variance at each candidate: 1 - k(Xs,p)^T Kinv k(Xs,p)
        KinvKs_cand = gp.Kinv @ Ks_cand                     # (n_s, n_c)
        sigma2_star = np.maximum(
            1.0 - np.einsum("ij,ij->j", Ks_cand, KinvKs_cand), 1e-12)  # (n_c,)

        scores = (sum_post_cov ** 2) / sigma2_star
        best   = int(np.argmax(scores))
        ids.append(candidates[best])
        ids_set.add(candidates[best])

    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return ids, pred


def run_smoothness_topk():
    """
    Estimate  S_topk = (1/k) * sum of top-k q-errors  where k = TOP_K_PERCENT * P.

    Uses EI over an adaptive threshold tau_t = k-th largest observed log-qerr.
    As more pairs are measured, tau_t rises toward the true k-th-largest, and
    sampling concentrates on the upper tail.

    acq(p) = (mu(p) - tau_t) * Phi(z) + sigma(p) * phi(z),  z = (mu-tau)/sigma
    (standard EI formula with a dynamic, data-driven threshold)

    Final estimate: mean of the k largest posterior means over all pairs.
    """
    Fs    = _std_F()
    log_q = np.log(np.maximum(qerr_all, 1e-9))
    n_seed = min(max(fdim + 2, 5), BUDGET)
    ids    = _lhs_seed_pairs(n_seed)
    k      = max(1, int(TOP_K_PERCENT * P))

    gp = MaternGP()
    while len(ids) < BUDGET:
        gp.fit(Fs[ids], log_q[ids])
        mu, sd = gp.predict(Fs, return_std=True)

        # Adaptive threshold: k-th largest observed log-qerr
        obs = log_q[ids]
        tau = float(np.sort(obs)[-k]) if len(obs) >= k else float(obs.min())

        z     = (mu - tau) / np.maximum(sd, 1e-12)
        score = ((mu - tau) * np.vectorize(_norm_cdf)(z)
                 + sd * np.vectorize(_norm_pdf)(z))
        score[ids] = -np.inf
        ids.append(int(np.argmax(score)))

    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return ids, pred


# =========================================================
# Shared save
# =========================================================

def save_method(name, ids, pred):
    mdir = os.path.join(OUTPUT_DIR, name)
    os.makedirs(mdir, exist_ok=True)

    df_out = pd.DataFrame({"pair_id": np.arange(P), "axis": axis_arr})
    for k, c in enumerate(xcols):
        df_out[f"mid_{c}"] = mid[:, k]
        df_out[f"a_{c}"]   = Xgrid[ia, k]
        df_out[f"b_{c}"]   = Xgrid[ib, k]

    df_out["y_true"]       = qerr_all
    df_out["y_pred"]       = np.maximum(pred, 1.0)
    df_out["abs_error"]    = np.abs(df_out["y_true"] - df_out["y_pred"])
    # q-error of the prediction itself (how far off our estimate)
    df_out["q_error"]      = np.maximum(
        df_out["y_true"] / np.maximum(df_out["y_pred"], 1e-9),
        df_out["y_pred"] / np.maximum(df_out["y_true"], 1e-9))
    df_out["is_sampled"]   = 0
    df_out["sample_order"] = -1
    for order, i in enumerate(ids):
        df_out.loc[i, "is_sampled"]   = 1
        df_out.loc[i, "sample_order"] = order

    df_out.to_csv(os.path.join(mdir, "predictions.csv"), index=False)
    df_out[df_out.is_sampled == 1].to_csv(
        os.path.join(mdir, "samples.csv"), index=False)

    touched = np.unique(np.concatenate([ia[ids], ib[ids]]))
    meta = {
        "method"                    : name,
        "budget_pairs"              : int(len(ids)),
        "total_pairs"               : int(P),
        "budget_percent"            : float(BUDGET_PERCENT),
        "sample_fraction"           : float(len(ids) / P),
        "unique_endpoints_executed" : int(len(touched)),
        "total_grid_points"         : int(n_grid),
        "dimension"                 : int(dim),
        "max_qerr_true"             : float(qerr_all.max()),
        "max_qerr_found"            : float(qerr_all[ids].max()),
    }
    with open(os.path.join(mdir, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    unseen  = df_out[df_out.is_sampled == 0]
    n_u     = len(unseen)
    med_u   = unseen["q_error"].median() if n_u else float("nan")
    p90_u   = unseen["q_error"].quantile(0.9) if n_u else float("nan")
    max_f   = qerr_all[ids].max()
    max_t   = qerr_all.max()
    print(
        f"  {name:28s}  budget={len(ids):4d}"
        f"  pred_qerr_median(unseen)={med_u:.3f}"
        f"  pred_qerr_p90(unseen)={p90_u:.3f}"
        f"  max_found={max_f:.2f}/{max_t:.2f}"
    )


# =========================================================
# 1. GROUND TRUTH
# =========================================================

print("Running methods...")
print()

save_method("ground_truth", list(range(P)), qerr_all.copy())

# =========================================================
# Uniform stride seed  (shared by methods 3 and 4)
# =========================================================

stride_ids = list(np.linspace(0, P - 1, BUDGET, dtype=int))
stride_ids = sorted(set(stride_ids))

# =========================================================
# 2. RANDOM
# =========================================================

random_ids  = sorted(random.sample(range(P), BUDGET))
pred_random = interp_pairs(random_ids)
save_method("random", random_ids, pred_random)

# =========================================================
# 3. UNIFORM STRIDE
# =========================================================

pred_stride = interp_pairs(stride_ids)
save_method("uniform_stride", stride_ids, pred_stride)

# =========================================================
# 4. GPR FIXED  (passive, Matern 5/2, uniform stride seed)
# =========================================================

gpr_fixed_ids, pred_gpr_fixed = run_gpr_fixed(stride_ids)
save_method("gpr_fixed", gpr_fixed_ids, pred_gpr_fixed)

# =========================================================
# 5. BO GENERIC — σ
# =========================================================

bo_sigma_ids, pred_bo_sigma = run_bo_generic(acq="sigma")
save_method("bo_generic_sigma", bo_sigma_ids, pred_bo_sigma)

# =========================================================
# 6. BO GENERIC — UCB
# =========================================================

bo_ucb_ids, pred_bo_ucb = run_bo_generic(acq="ucb")
save_method("bo_generic_ucb", bo_ucb_ids, pred_bo_ucb)

# =========================================================
# 7. BO GENERIC — EI
# =========================================================

bo_ei_ids, pred_bo_ei = run_bo_generic(acq="ei")
save_method("bo_generic_ei", bo_ei_ids, pred_bo_ei)

# =========================================================
# 8. OTTERTUNE MAX
# =========================================================

ot_max_ids, pred_ot_max = run_ottertune(target="max")
save_method("ottertune_max", ot_max_ids, pred_ot_max)

# =========================================================
# 9. OTTERTUNE RECONSTRUCT
# =========================================================

ot_rec_ids, pred_ot_rec = run_ottertune(target="reconstruct")
save_method("ottertune_reconstruct", ot_rec_ids, pred_ot_rec)

# =========================================================
# 10. SMOOTHNESS MAX
# =========================================================

sm_max_ids, pred_sm_max = run_smoothness_max()
save_method("smoothness_max", sm_max_ids, pred_sm_max)

# =========================================================
# 11. SMOOTHNESS AVG
# =========================================================

sm_avg_ids, pred_sm_avg = run_smoothness_avg()
save_method("smoothness_avg", sm_avg_ids, pred_sm_avg)

# =========================================================
# 12. SMOOTHNESS TOPK
# =========================================================

sm_topk_ids, pred_sm_topk = run_smoothness_topk()
save_method("smoothness_topk", sm_topk_ids, pred_sm_topk)


# =========================================================
# PLOTTING  (1D / 2D pair midpoints)
# =========================================================

all_methods = [
    ("ground_truth",          qerr_all.copy(), list(range(P))),
    ("random",                pred_random,     random_ids),
    ("uniform_stride",        pred_stride,     stride_ids),
    ("gpr_fixed",             pred_gpr_fixed,  gpr_fixed_ids),
    ("bo_generic_sigma",      pred_bo_sigma,   bo_sigma_ids),
    ("bo_generic_ucb",        pred_bo_ucb,     bo_ucb_ids),
    ("bo_generic_ei",         pred_bo_ei,      bo_ei_ids),
    ("ottertune_max",         pred_ot_max,     ot_max_ids),
    ("ottertune_reconstruct", pred_ot_rec,     ot_rec_ids),
    ("smoothness_max",        pred_sm_max,     sm_max_ids),
    ("smoothness_avg",        pred_sm_avg,     sm_avg_ids),
    ("smoothness_topk",       pred_sm_topk,    sm_topk_ids),
]

if dim == 1:
    order  = np.argsort(mid[:, 0])
    xm     = mid[order, 0]
    qt     = qerr_all[order]

    for name, pred, ids in all_methods:
        fig, axes = plt.subplots(1, 2, figsize=(18, 6))

        ax = axes[0]
        ax.plot(xm, qt, lw=3, label="true qerr")
        ax.plot(xm, pred[order], "--", lw=2, label=f"{name}")
        sids_sorted = sorted(ids, key=lambda i: mid[i, 0])
        sc = ax.scatter(mid[ids, 0], qerr_all[ids],
                        c=np.arange(len(ids)), cmap="viridis",
                        s=80, edgecolors="black", zorder=5, label="sampled")
        fig.colorbar(sc, ax=ax, label="Sample Order")
        ax.set_xlabel(f"mid {xcols[0]}"); ax.set_ylabel("qerr")
        ax.set_title(f"Q-error surface — {name}"); ax.grid(True); ax.legend()

        ax2 = axes[1]
        pred_err = np.maximum(qt / np.maximum(pred[order], 1e-9),
                               pred[order] / np.maximum(qt, 1e-9))
        ax2.plot(xm, pred_err, lw=2, color="tab:orange")
        ax2.axhline(1, ls="--", color="gray")
        ax2.set_xlabel(f"mid {xcols[0]}"); ax2.set_ylabel("prediction q-error")
        ax2.set_title(f"Prediction accuracy — {name}"); ax2.grid(True)

        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, f"{name}_1d.png"), dpi=120)
        plt.close()
    print("Saved 1D plots")

elif dim == 2:
    for name, pred, ids in all_methods:
        n_axes = dim
        fig, axs = plt.subplots(1, n_axes, figsize=(9 * n_axes, 7))
        if n_axes == 1:
            axs = [axs]
        for ax_i in range(n_axes):
            m = axis_arr == ax_i
            a = axs[ax_i]
            tc = a.tricontourf(mid[m, 0], mid[m, 1], pred[m], levels=20)
            fig.colorbar(tc, ax=a, label="qerr pred")
            sids = [i for i in ids if axis_arr[i] == ax_i]
            if sids:
                a.scatter(mid[sids, 0], mid[sids, 1],
                          c=np.arange(len(sids)), cmap="viridis",
                          s=80, edgecolors="black")
            a.set_xlabel(xcols[0]); a.set_ylabel(xcols[1])
            a.set_title(f"{name} — axis {xcols[ax_i]}")
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, f"{name}_2d.png"), dpi=120)
        plt.close()
    print("Saved 2D plots")

else:
    print("Skipping plots (dim > 2)")

print("\n================================================")
print("DONE")
print("================================================")
