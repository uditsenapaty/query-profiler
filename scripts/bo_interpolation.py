#!/usr/bin/env python3
# =========================================================
# scripts/bo_interpolation.py
# =========================================================
#
# Sample ~10% of the NEIGHBOR-PAIR Q-ERRORS of a 1D..ND
# runtime grid, then predict (interpolate) the full qerr
# field — using three clearly separated strategies:
#
#   1. gpr_fixed   "normal" Gaussian Process Regression
#                  -> YOU choose the 10% of pairs up front
#                     (file, or even stride default).
#                  -> one-shot fit, Matern kernel, hyper-
#                     parameters learned by MLE. No
#                     acquisition, no sequential choice.
#
#   2. bo_generic  textbook Bayesian-Optimization-style
#                  ACTIVE sampling
#                  -> the model itself picks each next pair
#                     (argmax acquisition over the discrete
#                     set of unsampled pairs), refits, loops.
#                  -> acquisition: sigma (default, best for
#                     reconstruction) | ucb | ei.
#
#   3. ottertune   EXACT OtterTune (cmu-db/ottertune) logic,
#                  ported from the official repo and adapted
#                  to a discrete pair-grid:
#                  - LHS (maximin) bootstrap of the first 10
#                    samples                  [async_tasks.gen_lhs_samples]
#                  - StandardScaler on X and y; maximization
#                    handled by negating y    [process_training_data]
#                  - GP with OtterTune's exact kernel
#                       K = mag * exp(-||x-x'|| / ls) + ridge*I
#                    fixed hyperparameters (NO MLE):
#                       GPR_LENGTH_SCALE = 2.0
#                       GPR_MAGNITUDE    = 1.0
#                       GPR_RIDGE        = 1.0     [gp_tf.GPR / models.Session]
#                  - candidate starts: NUM_SAMPLES=30 random
#                    + TOP_NUM_CONFIG=10 best seen, each
#                    nudged by GPR_EPS=0.001
#                                              [configuration_recommendation]
#                  - acquisition: minimize mu - beta*sigma,
#                    beta = UCB_SCALE * sqrt(2*ln(d*t^2*pi^2/6))
#                    (get_beta_td — beta GROWS with t)
#                                              [analysis/gpr/ucb.py]
#                  - Adam gradient descent on the GP surface,
#                    projected into bounds     [gp_tf.GPRGD.predict]
#                  - winner snapped to nearest unsampled grid
#                    pair (qerr only exists on grid pairs),
#                    measured, appended, loop.
#
# HOW THE THREE DIFFER (what you asked):
#
#   who picks samples : gpr_fixed = the user (passive design)
#                       bo_generic / ottertune = the algorithm
#   fitting           : gpr_fixed = one fit; others = refit
#                       after every new sample
#   kernel            : gpr_fixed/bo_generic = Matern 5/2,
#                       hyperparams MLE-optimized
#                       ottertune = exponential kernel with
#                       FIXED ls=2.0, mag=1.0, ridge=1.0
#   acquisition       : gpr_fixed = none
#                       bo_generic = sigma / EI / fixed-kappa
#                       UCB, argmax over discrete pairs
#                       ottertune = mu - beta(t)*sigma with
#                       growing beta, optimized by gradient
#                       descent from 30 random + 10 best
#                       starts, then snapped to the grid
#   objective         : gpr_fixed/bo_generic(sigma) = best
#                       reconstruction of the whole field
#                       ottertune (and bo_generic ucb/ei) =
#                       also hunts the WORST (max) qerr —
#                       OtterTune is an optimizer, its UCB
#                       loop concentrates samples near optima
#
# QERR DEFINITION (matches scripts/interpolation.py):
#   qerr(a, b) = max(ra/rb, rb/ra) of the two runtimes,
#   computed ONLY for axis-neighbor pairs: for every grid
#   point and every axis, the pair (point, next point along
#   that axis). NOTE: unlike interpolation.py, neighbors are
#   true per-axis grid neighbors, not "adjacent row index".
#
#   A pair is featurized as [midpoint coords (+ axis one-hot
#   when dim > 1)]; the qerr field is predicted at every
#   pair of the grid.
#
# INPUT  : ground_truth.csv with x* columns + runtime_mean
#          (or runtime) — same file your other scripts use.
# OUTPUT : <out>/pairs_catalog.csv          (pair_id list you
#          can pick from for --pairs-file)
#          <out>/<method>/predictions.csv   (all pairs)
#          <out>/<method>/samples.csv       (sampled pairs)
#          <out>/<method>/metadata.json
#          <out>/summary.csv                (method metrics)
#          1D/2D plots per method, >2D skipped.
#
# USAGE:
#   python scripts/bo_interpolation.py \
#       --csv gt_results_mqt8_500/ground_truth.csv \
#       --percent 0.10 --methods gpr_fixed,bo_generic,ottertune
#   # user-chosen pairs for plain GPR:
#   python scripts/bo_interpolation.py --pairs-file my_pairs.txt
#   (my_pairs.txt = one pair_id per line, ids from pairs_catalog.csv)
#
# =========================================================

import os
import json
import argparse
import warnings

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

from math import erf, sqrt, pi, exp as _exp

# ------------------ OtterTune exact session defaults ------------------
# (website/models.py :: Session.hyperparameters, cmu-db/ottertune@master)
OTTERTUNE = {
    "GPR_LENGTH_SCALE": 2.0,
    "GPR_MAGNITUDE": 1.0,
    "GPR_RIDGE": 1.0,
    "GPR_EPS": 0.001,
    "GPR_LEARNING_RATE": 0.01,
    # GPRGD constructor default = 100; the web session default is 500.
    # Raise with --gpr-max-iter if you want the session value.
    "GPR_MAX_ITER": 100,
    "GPR_UCB_SCALE": 0.2,
    "NUM_SAMPLES": 30,        # random candidate starts
    "TOP_NUM_CONFIG": 10,     # best-seen candidate starts
    "LHS_BOOTSTRAP": 10,      # initial LHS samples (gen_lhs_samples)
    "GPR_MU_MULTIPLIER": 1.0,
}


def symmetric_ratio(a, b):
    a = max(float(a), 1e-9)
    b = max(float(b), 1e-9)
    return max(a / b, b / a)


# =========================================================
# Pair-grid construction
# =========================================================

def build_pair_grid(df, xcols, ycol):
    """qerr lives on axis-neighbor PAIRS. Build every such pair."""
    # collapse duplicate coordinates (repeated measurements)
    g = df.groupby(xcols, as_index=False)[ycol].mean()
    X = g[xcols].values.astype(float)
    y = g[ycol].values.astype(float)

    axes_vals = [np.array(sorted(g[c].unique())) for c in xcols]
    index_of = {tuple(row): i for i, row in enumerate(X)}
    dim = len(xcols)

    pairs = []   # (axis, idx_a, idx_b)
    for i, row in enumerate(X):
        for ax in range(dim):
            vals = axes_vals[ax]
            pos = np.searchsorted(vals, row[ax])
            if pos + 1 >= len(vals):
                continue
            nb = row.copy()
            nb[ax] = vals[pos + 1]
            j = index_of.get(tuple(nb))
            if j is not None:
                pairs.append((ax, i, j))

    if not pairs:
        raise RuntimeError("No axis-neighbor pairs found — is this a grid?")

    axis_arr = np.array([p[0] for p in pairs])
    ia = np.array([p[1] for p in pairs])
    ib = np.array([p[2] for p in pairs])
    mid = (X[ia] + X[ib]) / 2.0
    qerr = np.array([symmetric_ratio(y[a], y[b]) for a, b in zip(ia, ib)])

    # features: midpoint (+ axis one-hot when dim > 1)
    if dim > 1:
        onehot = np.zeros((len(pairs), dim))
        onehot[np.arange(len(pairs)), axis_arr] = 1.0
        F = np.hstack([mid, onehot])
    else:
        F = mid.copy()

    return dict(X=X, y=y, axis=axis_arr, ia=ia, ib=ib, mid=mid,
                qerr=qerr, F=F, dim=dim, xcols=xcols)


# =========================================================
# OtterTune GP — exact numpy port of analysis/gp_tf.py
# =========================================================

class OtterTuneGP:
    """GPR with OtterTune's kernel: K = mag*exp(-||dx||/ls) + ridge*I.
    Mirrors GPR/GPRNP fit-predict math (K_inv, xy_ = K^-1 y)."""

    def __init__(self, length_scale=2.0, magnitude=1.0, ridge=1.0):
        self.ls = length_scale
        self.mag = magnitude
        self.ridge = ridge
        self.Xt = None
        self.K_inv = None
        self.xy_ = None

    @staticmethod
    def _dists(A, B):
        return np.sqrt(np.maximum(
            ((A[:, None, :] - B[None, :, :]) ** 2).sum(-1), 0.0))

    def fit(self, Xtrain, ytrain):
        self.Xt = np.asarray(Xtrain, float)
        yt = np.asarray(ytrain, float).reshape(-1, 1)
        D = self._dists(self.Xt, self.Xt)
        K = self.mag * np.exp(-D / self.ls) + self.ridge * np.eye(len(self.Xt))
        self.K_inv = np.linalg.inv(K)
        self.xy_ = self.K_inv @ yt
        return self

    def predict(self, Xtest):
        """mu and sigma exactly as GPRGD: sigma^2 = mag + ridge - k2' K^-1 k2."""
        Xtest = np.atleast_2d(np.asarray(Xtest, float))
        D2 = self._dists(self.Xt, Xtest)              # (n_train, n_test)
        K2 = self.mag * np.exp(-D2 / self.ls)
        mu = (K2.T @ self.xy_).ravel()
        v = np.einsum('ij,ik,kj->j', K2, self.K_inv, K2)
        sig = np.sqrt(np.maximum(self.mag + self.ridge - v, 1e-12))
        return mu, sig

    def grad_loss_batch(self, Xb, beta, mu_mult=1.0):
        """analytic loss = mu - beta*sigma and its gradient for a BATCH
        of points Xb (m, d) — vectorized GPRGD descent step."""
        Xb = np.atleast_2d(np.asarray(Xb, float))
        diff = Xb[:, None, :] - self.Xt[None, :, :]          # (m, n, d)
        r = np.sqrt(np.maximum((diff ** 2).sum(-1), 1e-12))  # (m, n)
        k2 = self.mag * np.exp(-r / self.ls)                 # (m, n)
        dk2 = (-(k2 / self.ls) / r)[..., None] * diff        # (m, n, d)
        a = self.xy_.ravel()                                 # (n,)
        mu = k2 @ a                                          # (m,)
        Kik = k2 @ self.K_inv                                # (m, n)
        var = np.maximum(self.mag + self.ridge
                         - np.einsum('mn,mn->m', Kik, k2), 1e-12)
        sig = np.sqrt(var)
        dmu = np.einsum('mnd,n->md', dk2, a)                 # (m, d)
        dvar = -2.0 * np.einsum('mn,mnd->md', Kik, dk2)
        dsig = dvar / (2.0 * sig)[:, None]
        loss = mu_mult * mu - beta * sig
        grad = mu_mult * dmu - beta * dsig
        return loss, grad


def get_beta_td(t, ndim, bound=1.0):
    """exact port of analysis/gpr/ucb.py::get_beta_td"""
    bt = 2.0 * np.log(float(ndim) * t ** 2 * np.pi ** 2 / (6.0 * bound))
    return np.sqrt(bt) if bt > 0.0 else 0.0


def maximin_lhs(nsamples, nfeats, rng, n_restarts=20):
    """LHS with maximin criterion (stand-in for pyDOE lhs(criterion='maximin'),
    as used by async_tasks.gen_lhs_samples)."""
    best, best_score = None, -1.0
    for _ in range(n_restarts):
        H = np.empty((nsamples, nfeats))
        for j in range(nfeats):
            perm = rng.permutation(nsamples)
            H[:, j] = (perm + rng.random(nsamples)) / nsamples
        d = OtterTuneGP._dists(H, H)
        np.fill_diagonal(d, np.inf)
        score = d.min()
        if score > best_score:
            best, best_score = H, score
    return best


# =========================================================
# "Normal" GPR: Matern 5/2, hyperparams by MLE (grid-searched
# log-marginal likelihood). This is what distinguishes it from
# OtterTune's GP, whose ls/mag/ridge are FIXED constants.
# =========================================================

class MaternGP:
    def __init__(self):
        self.ls = 1.0; self.noise = 1e-4; self.s2 = 1.0
        self.Xt = None; self.alpha = None; self.Kinv = None
        self.ymean = 0.0; self.ystd = 1.0

    @staticmethod
    def _k(r, ls, s2):
        a = np.sqrt(5.0) * r / ls
        return s2 * (1.0 + a + a * a / 3.0) * np.exp(-a)

    def _lml(self, D, y, ls, noise):
        K = self._k(D, ls, 1.0) + noise * np.eye(len(y))
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return -np.inf
        a = np.linalg.solve(L.T, np.linalg.solve(L, y))
        return float(-0.5 * y @ a - np.log(np.diag(L)).sum()
                     - 0.5 * len(y) * np.log(2 * np.pi))

    def fit(self, X, y):
        self.Xt = np.asarray(X, float)
        y = np.asarray(y, float).ravel()
        self.ymean, self.ystd = y.mean(), y.std() + 1e-12
        yn = (y - self.ymean) / self.ystd
        D = OtterTuneGP._dists(self.Xt, self.Xt)
        best = (-np.inf, 1.0, 1e-4)
        for ls in np.logspace(-1, 1.3, 12):          # MLE grid search
            for noise in (1e-6, 1e-4, 1e-3, 1e-2, 1e-1):
                lml = self._lml(D, yn, ls, noise)
                if lml > best[0]:
                    best = (lml, ls, noise)
        _, self.ls, self.noise = best
        K = self._k(D, self.ls, 1.0) + self.noise * np.eye(len(yn))
        self.Kinv = np.linalg.inv(K)
        self.alpha = self.Kinv @ yn
        return self

    def predict(self, X, return_std=False):
        X = np.atleast_2d(np.asarray(X, float))
        Ks = self._k(OtterTuneGP._dists(self.Xt, X), self.ls, 1.0)
        mu = Ks.T @ self.alpha * self.ystd + self.ymean
        if not return_std:
            return mu
        v = np.einsum('ij,ik,kj->j', Ks, self.Kinv, Ks)
        sd = np.sqrt(np.maximum(1.0 + self.noise - v, 1e-12)) * self.ystd
        return mu, sd

    def kernel_str(self):
        return (f"Matern 5/2, ls={self.ls:.3f}, noise={self.noise:.1e} "
                f"(MLE grid search)")


def _norm_pdf(z): return _exp(-0.5 * z * z) / sqrt(2 * pi)
def _norm_cdf(z): return 0.5 * (1.0 + erf(z / sqrt(2.0)))


# =========================================================
# Strategy 1: gpr_fixed (passive — user-specified design)
# =========================================================

def run_gpr_fixed(pg, budget, rng, pairs_file=None):
    n = len(pg["qerr"])
    if pairs_file:
        ids = sorted({int(v) for v in
                      open(pairs_file).read().split() if v.strip() != ""})
        ids = [i for i in ids if 0 <= i < n][:budget]
        if not ids:
            raise RuntimeError(f"--pairs-file {pairs_file}: no valid pair ids")
        print(f"[gpr_fixed] using {len(ids)} user-specified pairs")
    else:
        # deterministic even stride per axis (a sensible default the
        # user can override with --pairs-file)
        ids = []
        for ax in np.unique(pg["axis"]):
            ax_ids = np.where(pg["axis"] == ax)[0]
            order = ax_ids[np.lexsort(pg["mid"][ax_ids].T[::-1])]
            k = max(2, int(round(budget * len(ax_ids) / n)))
            take = np.linspace(0, len(order) - 1, min(k, len(order))).astype(int)
            ids.extend(order[take].tolist())
        ids = sorted(set(ids))[:budget]

    pred, info = _fit_plain_gp(pg, ids)
    return ids, pred, info


def _standardize(F):
    m, s = F.mean(0), F.std(0) + 1e-12
    return (F - m) / s


def _fit_plain_gp(pg, ids):
    F, q = pg["F"], pg["qerr"]
    Fs = _standardize(F)
    # log-space: qerr is a ratio >= 1, multiplicative by nature
    gp = MaternGP().fit(Fs[ids], np.log(q[ids]))
    mu = gp.predict(Fs)
    info = {"kernel": gp.kernel_str(), "hyperparams": "MLE (grid search)",
            "model": "plain GPR (Matern 5/2), log-qerr target, one-shot fit"}
    return np.maximum(np.exp(mu), 1.0), info


# =========================================================
# Strategy 2: bo_generic (active — discrete acquisition argmax)
# =========================================================

def run_bo_generic(pg, budget, rng, acq="sigma", kappa=2.0):
    F, q = pg["F"], pg["qerr"]
    Fs = _standardize(F)

    n_seed = min(max(2 * F.shape[1] + 2, 5), budget)
    # seed via maximin LHS snapped to nearest pairs (space-filling seed)
    H = maximin_lhs(n_seed, F.shape[1], rng)
    lo, hi = Fs.min(0), Fs.max(0)
    ids = []
    for s_pt in (lo + H * (hi - lo)):
        d = ((Fs - s_pt) ** 2).sum(1)
        d[ids] = np.inf
        ids.append(int(np.argmin(d)))
    ids = list(dict.fromkeys(ids))

    gp = MaternGP()
    while len(ids) < budget:
        yl = np.log(q[ids])
        gp.fit(Fs[ids], yl)
        mu, sd = gp.predict(Fs, return_std=True)
        if acq == "sigma":          # pure uncertainty -> reconstruction
            score = sd.copy()
        elif acq == "ucb":          # hunt large qerr
            score = mu + kappa * sd
        elif acq == "ei":
            best = yl.max()
            z = (mu - best) / np.maximum(sd, 1e-12)
            score = ((mu - best) * np.vectorize(_norm_cdf)(z)
                     + sd * np.vectorize(_norm_pdf)(z))
        else:
            raise ValueError(f"unknown acq: {acq}")
        score[ids] = -np.inf
        ids.append(int(np.argmax(score)))

    gp.fit(Fs[ids], np.log(q[ids]))
    mu = gp.predict(Fs)
    info = {"kernel": gp.kernel_str(), "acquisition": acq,
            "model": "GPR (Matern 5/2, MLE), sequential active sampling "
                     "(argmax acquisition over discrete unsampled pairs)"}
    return ids, np.maximum(np.exp(mu), 1.0), info


# =========================================================
# Strategy 3: ottertune (exact OtterTune logic on the pair grid)
# =========================================================

def run_ottertune(pg, budget, rng, hp=OTTERTUNE, target="max"):
    """
    Faithful adaptation of configuration_recommendation():
      knobs  -> pair features (midpoint + axis one-hot)
      target -> qerr of the pair ('throughput' analog: more-is-better,
                hence y is NEGATED, exactly like lesser_is_better=False
                in process_training_data)
    target="max"         exact OtterTune objective: UCB loop hunts the
                         WORST (max) qerr region
    target="reconstruct" same machinery with mu_multiplier=0 -> pure
                         -beta*sigma descent = uncertainty sampling
                         (use when you only care about field accuracy)
    """
    F, q = pg["F"], pg["qerr"]
    n, d = F.shape
    find_max_qerr = (target == "max")
    mu_mult = hp["GPR_MU_MULTIPLIER"] if find_max_qerr else 0.0

    # ---- LHS bootstrap (gen_lhs_samples: 10 samples, maximin) ----
    n_lhs = min(hp["LHS_BOOTSTRAP"], budget)
    H = maximin_lhs(n_lhs, d, rng)
    lo_raw, hi_raw = F.min(0), F.max(0)
    ids = []
    for s_pt in (lo_raw + H * (hi_raw - lo_raw)):
        dist = ((F - s_pt) ** 2).sum(1)
        dist[ids] = np.inf
        ids.append(int(np.argmin(dist)))
    ids = list(dict.fromkeys(ids))

    t = 0
    while len(ids) < budget:
        t += 1
        # ---- process_training_data: scale X, y to N(0,1) ----
        Xs_scaler_mean = F[ids].mean(0)
        Xs_scaler_std = F[ids].std(0) + 1e-12
        Xs = (F - Xs_scaler_mean) / Xs_scaler_std
        ys = q[ids].astype(float)
        y_mean, y_std = ys.mean(), ys.std() + 1e-12
        ysc = (ys - y_mean) / y_std
        if find_max_qerr:
            ysc = -ysc                      # maximize -> minimize(-y)

        X_min, X_max = Xs.min(0), Xs.max(0)

        gp = OtterTuneGP(hp["GPR_LENGTH_SCALE"], hp["GPR_MAGNITUDE"],
                         hp["GPR_RIDGE"]).fit(Xs[ids], ysc)

        # ---- candidate starts: 30 random + 10 best (+/- GPR_EPS) ----
        starts = rng.random((hp["NUM_SAMPLES"], d)) * (X_max - X_min) + X_min
        order = np.argsort(ysc)             # smallest scaled loss = best
        top = []
        for j in order[:hp["TOP_NUM_CONFIG"]]:
            xj = Xs[ids[j]].copy()
            nudge = -hp["GPR_EPS"] if np.sum((X_max - xj) ** 2) < 1e-3 \
                else hp["GPR_EPS"]
            top.append(xj + nudge)
        starts = np.vstack([starts] + top) if top else starts

        # ---- UCB beta (ucb.get_ucb_beta with get_beta_td) ----
        beta = hp["GPR_UCB_SCALE"] * get_beta_td(t, d)

        # ---- GPRGD: Adam descent on mu - beta*sigma, projected ----
        # (vectorized over all 40 starts; same math as gp_tf.GPRGD.predict)
        Xb = starts.copy()
        m_t = np.zeros_like(Xb); v_t = np.zeros_like(Xb)
        lr, eps = hp["GPR_LEARNING_RATE"], 1e-8
        loss, _ = gp.grad_loss_batch(Xb, beta, mu_mult)
        best_l = loss.copy(); best_X = Xb.copy()
        for it in range(1, hp["GPR_MAX_ITER"] + 1):
            loss, g = gp.grad_loss_batch(Xb, beta, mu_mult)
            improved = loss < best_l
            best_l[improved] = loss[improved]
            best_X[improved] = Xb[improved]
            m_t = 0.9 * m_t + 0.1 * g
            v_t = 0.999 * v_t + 0.001 * g * g
            mh = m_t / (1 - 0.9 ** it)
            vh = v_t / (1 - 0.999 ** it)
            Xb = Xb - lr * mh / (np.sqrt(vh) + eps)
            Xb = np.minimum(np.maximum(Xb, X_min), X_max)   # projected GD
        best_x = best_X[int(np.argmin(best_l))]

        # ---- snap winner to nearest UNSAMPLED grid pair & measure ----
        dist = ((Xs - best_x) ** 2).sum(1)
        dist[ids] = np.inf
        new_id = int(np.argmin(dist))
        ids.append(new_id)

    # ---- final surface from the final OtterTune GP ----
    Xs_scaler_mean = F[ids].mean(0)
    Xs_scaler_std = F[ids].std(0) + 1e-12
    Xs = (F - Xs_scaler_mean) / Xs_scaler_std
    ys = q[ids].astype(float)
    y_mean, y_std = ys.mean(), ys.std() + 1e-12
    ysc = (ys - y_mean) / y_std
    if find_max_qerr:
        ysc = -ysc
    gp = OtterTuneGP(hp["GPR_LENGTH_SCALE"], hp["GPR_MAGNITUDE"],
                     hp["GPR_RIDGE"]).fit(Xs[ids], ysc)
    mu, _ = gp.predict(Xs)
    if find_max_qerr:
        mu = -mu
    pred = mu * y_std + y_mean
    info = {"kernel": "mag*exp(-||dx||/ls) + ridge*I  (OtterTune gp_tf.py)",
            "hyperparams": {k: hp[k] for k in
                            ("GPR_LENGTH_SCALE", "GPR_MAGNITUDE", "GPR_RIDGE",
                             "GPR_UCB_SCALE", "GPR_LEARNING_RATE",
                             "GPR_MAX_ITER", "NUM_SAMPLES", "TOP_NUM_CONFIG")},
            "target": target,
            "acquisition": "minimize mu_mult*mu - beta(t)*sigma, "
                           "beta = UCB_SCALE*get_beta_td(t, d), "
                           f"mu_mult={mu_mult}",
            "model": "exact OtterTune GPR/GPRGD logic, winner snapped "
                     "to nearest unsampled pair"}
    return ids, np.maximum(pred, 1.0), info


# =========================================================
# Saving & plots (mirrors interpolation.py conventions)
# =========================================================

def save_method(outdir, name, pg, ids, pred, info, runtime_y=True):
    mdir = os.path.join(outdir, name)
    os.makedirs(mdir, exist_ok=True)
    xcols = pg["xcols"]
    dfp = pd.DataFrame()
    for k, c in enumerate(xcols):
        dfp[f"mid_{c}"] = pg["mid"][:, k]
        dfp[f"a_{c}"] = pg["X"][pg["ia"], k]
        dfp[f"b_{c}"] = pg["X"][pg["ib"], k]
    dfp["axis"] = [xcols[a] for a in pg["axis"]]
    dfp["pair_id"] = np.arange(len(pg["qerr"]))
    dfp["qerr_true"] = pg["qerr"]
    dfp["qerr_pred"] = pred
    dfp["abs_error"] = np.abs(dfp.qerr_true - dfp.qerr_pred)
    dfp["q_error_of_pred"] = np.maximum(
        dfp.qerr_true / np.maximum(dfp.qerr_pred, 1e-9),
        dfp.qerr_pred / np.maximum(dfp.qerr_true, 1e-9))
    dfp["is_sampled"] = 0
    dfp["sample_order"] = -1
    for order, i in enumerate(ids):
        dfp.loc[i, "is_sampled"] = 1
        dfp.loc[i, "sample_order"] = order
    dfp = dfp.sort_values(["axis"] + [f"mid_{c}" for c in xcols]).reset_index(drop=True)
    dfp.to_csv(os.path.join(mdir, "predictions.csv"), index=False)
    dfp[dfp.is_sampled == 1].to_csv(os.path.join(mdir, "samples.csv"), index=False)

    touched = np.unique(np.concatenate([pg["ia"][ids], pg["ib"][ids]]))
    meta = {
        "method": name,
        "budget_pairs": int(len(ids)),
        "total_pairs": int(len(pg["qerr"])),
        "sample_fraction": float(len(ids) / len(pg["qerr"])),
        "unique_endpoints_executed": int(len(touched)),
        "total_grid_points": int(len(pg["y"])),
        "dimension": int(pg["dim"]),
        "metrics": {
            "mae": float(dfp.abs_error.mean()),
            "rmse": float(np.sqrt((dfp.abs_error ** 2).mean())),
            "mean_q_error_of_pred": float(dfp.q_error_of_pred.mean()),
            "p95_q_error_of_pred": float(dfp.q_error_of_pred.quantile(0.95)),
            "max_qerr_true": float(dfp.qerr_true.max()),
            "max_qerr_found_by_sampling": float(pg["qerr"][ids].max()),
        },
        "model": info,
    }
    with open(os.path.join(mdir, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved: {name:12s} mae={meta['metrics']['mae']:.4f} "
          f"meanQ={meta['metrics']['mean_q_error_of_pred']:.4f} "
          f"maxqerr found={meta['metrics']['max_qerr_found_by_sampling']:.3f}"
          f"/{meta['metrics']['max_qerr_true']:.3f}")
    return meta


def plot_method(outdir, name, pg, ids, pred):
    dim = pg["dim"]
    if dim > 2:
        return
    if dim == 1:
        order = np.argsort(pg["mid"][:, 0])
        xm = pg["mid"][order, 0]
        plt.figure(figsize=(14, 7))
        plt.plot(xm, pg["qerr"][order], lw=3, label="qerr ground truth")
        plt.plot(xm, pred[order], "--", lw=2, label=f"{name} prediction")
        so = np.argsort([pg["mid"][i, 0] for i in ids])
        sc = plt.scatter(pg["mid"][ids, 0][so], pg["qerr"][ids][so],
                         c=np.arange(len(ids))[so], s=100, cmap="viridis",
                         edgecolors="black", label="sampled pairs", zorder=5)
        plt.colorbar(sc, label="Sample Order")
        plt.xlabel(f"midpoint {pg['xcols'][0]} (pair of axis neighbors)")
        plt.ylabel("qerr")
        plt.title(f"qerr interpolation — {name}")
        plt.grid(True); plt.legend(); plt.tight_layout()
        plt.savefig(os.path.join(outdir, f"{name}_1d.png")); plt.close()
    else:
        fig, axs = plt.subplots(1, dim, figsize=(9 * dim, 7))
        for ax_i in range(dim):
            m = pg["axis"] == ax_i
            a = axs[ax_i]
            tc = a.tricontourf(pg["mid"][m, 0], pg["mid"][m, 1], pred[m], levels=20)
            fig.colorbar(tc, ax=a)
            sids = [i for i in ids if pg["axis"][i] == ax_i]
            if sids:
                a.scatter(pg["mid"][sids, 0], pg["mid"][sids, 1],
                          c=[ids.index(i) for i in sids], cmap="viridis",
                          s=80, edgecolors="black")
            a.set_xlabel(pg["xcols"][0]); a.set_ylabel(pg["xcols"][1])
            a.set_title(f"{name} — qerr along {pg['xcols'][ax_i]}")
        plt.tight_layout()
        plt.savefig(os.path.join(outdir, f"{name}_2d.png")); plt.close()


# =========================================================
# main
# =========================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="gt_results_mqt8_500/ground_truth.csv")
    ap.add_argument("--out", default="bo_interpolation_results")
    ap.add_argument("--percent", type=float, default=0.10,
                    help="fraction of total qerr PAIRS to sample (default 0.10)")
    ap.add_argument("--methods", default="gpr_fixed,bo_generic,ottertune")
    ap.add_argument("--acq", default="sigma", choices=["sigma", "ucb", "ei"],
                    help="acquisition for bo_generic")
    ap.add_argument("--pairs-file", default=None,
                    help="gpr_fixed only: file with one pair_id per line "
                         "(ids from <out>/pairs_catalog.csv) — this is how YOU "
                         "specify the 10%% of qerr pairs yourself")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--gpr-max-iter", type=int, default=None,
                    help="override OtterTune GPRGD descent iterations "
                         "(default 100 = GPRGD constructor; web session uses 500)")
    ap.add_argument("--ottertune-target", default="max",
                    choices=["max", "reconstruct"],
                    help="'max' = exact OtterTune behavior (UCB hunts the worst "
                         "qerr); 'reconstruct' = same machinery with "
                         "mu_multiplier=0 (pure uncertainty sampling)")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    np.random.seed(args.seed)

    df = pd.read_csv(args.csv)
    xcols = sorted([c for c in df.columns if c.startswith("x")])
    if not xcols:
        raise RuntimeError("No x-columns found")
    ycol = "runtime_mean" if "runtime_mean" in df.columns else "runtime"
    if ycol not in df.columns:
        raise RuntimeError("No runtime column found")

    pg = build_pair_grid(df, xcols, ycol)
    n_pairs = len(pg["qerr"])
    dim = pg["dim"]
    budget = min(n_pairs, max(5, 2 * pg["F"].shape[1] + 1,
                              int(args.percent * n_pairs)))

    print("=" * 56)
    print(f"grid points : {len(pg['y'])}   dims: {dim} ({', '.join(xcols)})")
    print(f"qerr pairs  : {n_pairs}  (axis-neighbor pairs, all axes)")
    print(f"budget      : {budget} pairs  ({args.percent:.0%} of pairs)")
    print("=" * 56)
    print("gpr_fixed  = passive GPR, YOU pick the pairs (--pairs-file)")
    print("bo_generic = active BO, model picks pairs (acq=%s)" % args.acq)
    print("ottertune  = exact OtterTune LHS + fixed-kernel GP + "
          "beta(t)-UCB + Adam descent")
    print("=" * 56)

    os.makedirs(args.out, exist_ok=True)
    # catalog so the user can hand-pick pair ids for --pairs-file
    cat = pd.DataFrame({"pair_id": np.arange(n_pairs),
                        "axis": [xcols[a] for a in pg["axis"]],
                        "qerr_true": pg["qerr"]})
    for k, c in enumerate(xcols):
        cat[f"a_{c}"] = pg["X"][pg["ia"], k]
        cat[f"b_{c}"] = pg["X"][pg["ib"], k]
    cat.to_csv(os.path.join(args.out, "pairs_catalog.csv"), index=False)

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    summary = []

    for m in methods:
        if m == "gpr_fixed":
            ids, pred, (info, _, _) = run_gpr_fixed(pg, budget, rng,
                                                    args.pairs_file)
        elif m == "bo_generic":
            ids, pred, info = run_bo_generic(pg, budget, rng, acq=args.acq)
        elif m == "ottertune":
            hp = dict(OTTERTUNE)
            if args.gpr_max_iter:
                hp["GPR_MAX_ITER"] = args.gpr_max_iter
            ids, pred, info = run_ottertune(pg, budget, rng, hp=hp,
                                            target=args.ottertune_target)
        else:
            print(f"[skip] unknown method {m}")
            continue
        meta = save_method(args.out, m, pg, list(ids), pred, info)
        plot_method(args.out, m, pg, list(ids), pred)
        summary.append({"method": m, **meta["metrics"],
                        "budget_pairs": meta["budget_pairs"],
                        "unique_endpoints": meta["unique_endpoints_executed"]})

    if summary:
        pd.DataFrame(summary).to_csv(os.path.join(args.out, "summary.csv"),
                                     index=False)
    print("\nDONE ->", args.out)


if __name__ == "__main__":
    main()