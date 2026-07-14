#!/usr/bin/env python3
# =========================================================
# scripts/interp_ppt_data.py
# ---------------------------------------------------------
# Reproducible 5x5 toy grid that mirrors the EXACT math of
# scripts/interpolation.py, instrumented to expose the
# intermediate numbers (features, q-errors, GP mu/sigma,
# acquisition values, sampling picks) used to build the
# explanatory PowerPoint.
#
# The grid is synthetic (so it can be 5x5 = 40 pairs as the
# slides require); every formula is copied verbatim from
# interpolation.py so the worked numbers are faithful.
# =========================================================

import numpy as np
from math import erf, sqrt, pi, exp as _mexp

SEED = 42
np.random.seed(SEED)
_rng = np.random.default_rng(SEED)

# ---------------------------------------------------------
# math copied verbatim from interpolation.py
# ---------------------------------------------------------
def symmetric_ratio(a, b):
    a = max(float(a), 1e-9); b = max(float(b), 1e-9)
    return max(a / b, b / a)

def _norm_pdf(z): return _mexp(-0.5 * z * z) / sqrt(2 * pi)
def _norm_cdf(z): return 0.5 * (1.0 + erf(z / sqrt(2.0)))

def _get_beta_td(t, ndim, bound=1.0):
    bt = 2.0 * np.log(float(ndim) * t ** 2 * np.pi ** 2 / (6.0 * bound))
    return sqrt(bt) if bt > 0.0 else 0.0


class OtterTuneGP:
    """K = mag*exp(-||dx||/ls) + ridge*I  (fixed HPs, no MLE)."""
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
    """Matern 5/2 GPR, (ls, noise) by MLE grid search, log-qerr space."""
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


# =========================================================
# 5x5 synthetic grid  (x1, x2 in {1..5})
# runtimes: smooth gradient + a "plan-flip" cliff at x1>=4,
# x2>=3 -> a cluster of high q-error pairs, plus one bump.
# =========================================================
x1_vals = np.array([1., 2., 3., 4., 5.])
x2_vals = np.array([1., 2., 3., 4., 5.])

# R[i][j] : i indexes x1, j indexes x2  (runtime in seconds)
R = np.array([
    [10.0, 10.8, 11.6, 12.4, 13.2],
    [11.2, 12.1, 13.0, 13.9, 22.0],   # one secondary bump at (x1=2,x2=5)
    [12.5, 13.5, 14.5, 15.5, 16.5],
    [13.8, 14.9, 110.0, 118.0, 126.0],  # cliff: plan flip for x1=4, x2>=3
    [15.1, 16.3, 120.0, 128.0, 136.0],  # cliff continues for x1=5
])

# grid points sorted (x1 outer, x2 inner) -> mirrors groupby([x1,x2])
Xgrid = np.array([[x1_vals[i], x2_vals[j]] for i in range(5) for j in range(5)], float)
ygrid = np.array([R[i, j] for i in range(5) for j in range(5)], float)
xcols = ["x1", "x2"]
dim   = 2
n_grid = len(Xgrid)
axes_vals = [x1_vals, x2_vals]
index_of  = {tuple(r): k for k, r in enumerate(Xgrid)}

# pairs: per point, axis0 (+x1) then axis1 (+x2)  -> mirrors interpolation.py
pairs = []
for i, row in enumerate(Xgrid):
    for ax in range(dim):
        pos = np.searchsorted(axes_vals[ax], row[ax])
        if pos + 1 >= len(axes_vals[ax]):
            continue
        nb = row.copy(); nb[ax] = axes_vals[ax][pos + 1]
        j  = index_of.get(tuple(nb))
        if j is not None:
            pairs.append((ax, i, j))

axis_arr = np.array([p[0] for p in pairs])
ia       = np.array([p[1] for p in pairs])
ib       = np.array([p[2] for p in pairs])
mid      = (Xgrid[ia] + Xgrid[ib]) / 2.0
qerr_all = np.array([symmetric_ratio(ygrid[a], ygrid[b]) for a, b in zip(ia, ib)])

onehot = np.zeros((len(pairs), dim)); onehot[np.arange(len(pairs)), axis_arr] = 1.0
F      = np.hstack([mid, onehot])
P      = len(pairs)
fdim   = F.shape[1]

# ---- budget (toy uses a slightly larger budget than 10% so the
#      active loop is visible; production interpolation.py uses 10%).
BUDGET = 10
N_SEED = min(max(fdim + 2, 5), BUDGET)   # = 6 (same formula as code)

def _std_F():
    m = F.mean(0); s = F.std(0) + 1e-12
    return (F - m) / s

def _lhs_seed_pairs(budget):
    H  = _maximin_lhs(budget, fdim)
    lo = F.min(0); hi = F.max(0)
    ids = []
    for s_pt in (lo + H * (hi - lo)):
        d = ((F - s_pt) ** 2).sum(1)
        if ids:
            d[ids] = np.inf
        ids.append(int(np.argmin(d)))
    return list(dict.fromkeys(ids))


def pair_label(pid):
    """Human label like  x1:3->4 @ x2=2  (axis 0)  or  x2:1->2 @ x1=4."""
    ax = axis_arr[pid]; a = ia[pid]; b = ib[pid]
    if ax == 0:
        return f"x1:{Xgrid[a,0]:.0f}->{Xgrid[b,0]:.0f} @ x2={Xgrid[a,1]:.0f}"
    return f"x2:{Xgrid[a,1]:.0f}->{Xgrid[b,1]:.0f} @ x1={Xgrid[a,0]:.0f}"


# =========================================================
# instrumented runners (capture first-active-iteration snapshot
# + full pick order)
# =========================================================
log_q = np.log(np.maximum(qerr_all, 1e-9))

def run_bo(acq="sigma", kappa=2.0):
    Fs   = _std_F()
    ids  = _lhs_seed_pairs(N_SEED)
    seed = list(ids)
    snap = None
    picks = []
    gp = MaternGP()
    while len(ids) < BUDGET:
        gp.fit(Fs[ids], log_q[ids])
        mu, sd = gp.predict(Fs, return_std=True)
        if acq == "sigma":
            score = sd.copy(); extra = {}
        elif acq == "ucb":
            score = mu + kappa * sd; extra = {"kappa": kappa}
        else:
            best = log_q[ids].max()
            z    = (mu - best) / np.maximum(sd, 1e-12)
            Phi  = np.vectorize(_norm_cdf)(z); phi = np.vectorize(_norm_pdf)(z)
            score = (mu - best) * Phi + sd * phi
            extra = {"best": best, "z": z, "Phi": Phi, "phi": phi}
        sc = score.copy(); sc[ids] = -np.inf
        pick = int(np.argmax(sc))
        if snap is None:
            snap = dict(ls=gp.ls, noise=gp.noise, mu=mu.copy(), sd=sd.copy(),
                        score=score.copy(), masked=set(ids), pick=pick, extra=extra)
        picks.append(pick)
        ids.append(pick)
    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return dict(seed=seed, ids=ids, picks=picks, snap=snap, pred=pred)


def run_smoothness_max():
    Fs  = _std_F()
    ids = _lhs_seed_pairs(N_SEED); seed = list(ids)
    t   = len(ids); snap = None; picks = []
    gp  = MaternGP()
    while len(ids) < BUDGET:
        t += 1
        gp.fit(Fs[ids], log_q[ids])
        mu, sd = gp.predict(Fs, return_std=True)
        beta_t = sqrt(2.0 * np.log(P * t * t * pi * pi / 6.0))
        score  = mu + beta_t * sd
        sc = score.copy(); sc[ids] = -np.inf
        pick = int(np.argmax(sc))
        if snap is None:
            snap = dict(ls=gp.ls, noise=gp.noise, mu=mu.copy(), sd=sd.copy(),
                        beta=beta_t, score=score.copy(), masked=set(ids), pick=pick, t=t)
        picks.append(pick); ids.append(pick)
    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return dict(seed=seed, ids=ids, picks=picks, snap=snap, pred=pred)


def run_smoothness_avg():
    Fs   = _std_F()
    ids  = _lhs_seed_pairs(N_SEED); seed = list(ids)
    ids_set = set(ids); snap = None; picks = []
    gp = MaternGP()
    while len(ids) < BUDGET:
        gp.fit(Fs[ids], log_q[ids])
        candidates = [i for i in range(P) if i not in ids_set]
        Fs_cand = Fs[candidates]
        K_cand_all = gp._k52(OtterTuneGP._dist(Fs_cand, Fs), gp.ls)
        sum_k_prior = K_cand_all.sum(1)
        Ks_cand = gp._k52(OtterTuneGP._dist(gp.Xt, Fs_cand), gp.ls)
        Ks_all  = gp._k52(OtterTuneGP._dist(gp.Xt, Fs), gp.ls)
        sum_k_all_s = Ks_all.sum(1)
        correction  = (sum_k_all_s @ gp.Kinv) @ Ks_cand
        sum_post_cov = sum_k_prior - correction
        KinvKs_cand = gp.Kinv @ Ks_cand
        sigma2_star = np.maximum(
            1.0 - np.einsum("ij,ij->j", Ks_cand, KinvKs_cand), 1e-12)
        scores = (sum_post_cov ** 2) / sigma2_star
        best = int(np.argmax(scores))
        pick = candidates[best]
        if snap is None:
            snap = dict(ls=gp.ls, candidates=list(candidates),
                        sum_post_cov=sum_post_cov.copy(),
                        sigma2_star=sigma2_star.copy(),
                        scores=scores.copy(), pick=pick)
        picks.append(pick); ids.append(pick); ids_set.add(pick)
    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return dict(seed=seed, ids=ids, picks=picks, snap=snap, pred=pred)


def run_smoothness_topk(topk_pct=0.10):
    Fs   = _std_F()
    ids  = _lhs_seed_pairs(N_SEED); seed = list(ids)
    k    = max(1, int(topk_pct * P)); snap = None; picks = []
    gp = MaternGP()
    while len(ids) < BUDGET:
        gp.fit(Fs[ids], log_q[ids])
        mu, sd = gp.predict(Fs, return_std=True)
        obs = log_q[ids]
        tau = float(np.sort(obs)[-k]) if len(obs) >= k else float(obs.min())
        z   = (mu - tau) / np.maximum(sd, 1e-12)
        Phi = np.vectorize(_norm_cdf)(z); phi = np.vectorize(_norm_pdf)(z)
        score = (mu - tau) * Phi + sd * phi
        sc = score.copy(); sc[ids] = -np.inf
        pick = int(np.argmax(sc))
        if snap is None:
            snap = dict(ls=gp.ls, noise=gp.noise, mu=mu.copy(), sd=sd.copy(),
                        tau=tau, k=k, z=z, Phi=Phi, phi=phi,
                        score=score.copy(), masked=set(ids), pick=pick)
        picks.append(pick); ids.append(pick)
    gp.fit(Fs[ids], log_q[ids])
    pred = np.maximum(np.exp(gp.predict(Fs)), 1.0)
    return dict(seed=seed, ids=ids, picks=picks, snap=snap, pred=pred)


def run_gpr_fixed(seed_ids):
    Fs   = _std_F()
    gp   = MaternGP().fit(Fs[seed_ids], log_q[seed_ids])
    mu, sd = gp.predict(Fs, return_std=True)
    pred = np.maximum(np.exp(mu), 1.0)
    return dict(seed=list(seed_ids), ids=list(seed_ids),
                ls=gp.ls, noise=gp.noise, mu=mu, sd=sd, pred=pred)


OTTERTUNE_HP = {"GPR_LENGTH_SCALE":2.0,"GPR_MAGNITUDE":1.0,"GPR_RIDGE":1.0,
                "GPR_EPS":0.001,"GPR_LEARNING_RATE":0.01,"GPR_MAX_ITER":100,
                "GPR_UCB_SCALE":0.2,"NUM_SAMPLES":30,"TOP_NUM_CONFIG":10,
                "LHS_BOOTSTRAP":6}   # toy LHS_BOOTSTRAP reduced from 10 so loop is visible

def run_ottertune(target="max"):
    hp = OTTERTUNE_HP
    find_max = (target == "max"); mu_mult = 1.0 if find_max else 0.0
    ids = _lhs_seed_pairs(min(hp["LHS_BOOTSTRAP"], BUDGET)); seed = list(ids)
    picks = []; snap = None; t = 0
    while len(ids) < BUDGET:
        t += 1
        Fm = F[ids].mean(0); Fsd = F[ids].std(0) + 1e-12
        Fs = (F - Fm) / Fsd
        lq_s = log_q[ids]; ym, ys = lq_s.mean(), lq_s.std() + 1e-12
        ysc = (lq_s - ym) / ys
        if find_max: ysc = -ysc
        X_lo, X_hi = Fs.min(0), Fs.max(0)
        gp = OtterTuneGP(hp["GPR_LENGTH_SCALE"], hp["GPR_MAGNITUDE"],
                         hp["GPR_RIDGE"]).fit(Fs[ids], ysc)
        starts = _rng.random((hp["NUM_SAMPLES"], fdim)) * (X_hi - X_lo) + X_lo
        top = []
        for j in np.argsort(ysc)[:hp["TOP_NUM_CONFIG"]]:
            xj = Fs[ids[j]].copy()
            eps = (-hp["GPR_EPS"] if np.sum((X_hi - xj) ** 2) < 1e-3 else hp["GPR_EPS"])
            top.append(xj + eps)
        if top: starts = np.vstack([starts] + top)
        beta = hp["GPR_UCB_SCALE"] * _get_beta_td(t, fdim)
        Xb = starts.copy(); m_t = np.zeros_like(Xb); v_t = np.zeros_like(Xb)
        lr, eps_a = hp["GPR_LEARNING_RATE"], 1e-8
        loss0, _ = gp.grad_loss_batch(Xb, beta, mu_mult)
        best_l = loss0.copy(); best_X = Xb.copy()
        for it in range(1, hp["GPR_MAX_ITER"] + 1):
            loss, g = gp.grad_loss_batch(Xb, beta, mu_mult)
            improved = loss < best_l
            best_l[improved] = loss[improved]; best_X[improved] = Xb[improved]
            m_t = 0.9 * m_t + 0.1 * g; v_t = 0.999 * v_t + 0.001 * g * g
            mh = m_t / (1 - 0.9 ** it); vh = v_t / (1 - 0.999 ** it)
            Xb = np.clip(Xb - lr * mh / (np.sqrt(vh) + eps_a), X_lo, X_hi)
        best_x = best_X[int(np.argmin(best_l))]
        dist = ((Fs - best_x) ** 2).sum(1); dist[ids] = np.inf
        pick = int(np.argmin(dist))
        if snap is None:
            mu_p, sig_p = gp.predict(Fs)            # OtterTune posterior (in scaled space)
            if find_max: mu_disp = -mu_p
            else:        mu_disp = mu_p
            snap = dict(beta=beta, mu=mu_disp.copy(), sig=sig_p.copy(),
                        masked=set(ids), pick=pick, ym=ym, ys=ys, mu_mult=mu_mult)
        picks.append(pick); ids.append(pick)
    return dict(seed=seed, ids=ids, picks=picks, snap=snap)


# =========================================================
# Shared ILLUSTRATIVE acquisition demo (real formulas, on a
# representative posterior so the 5 acquisitions pick DIFFERENT
# pairs — the GP on only 6 toy seeds is data-starved and ties).
# log-qerr space.  best/tau/beta are stated incumbents.
# =========================================================
ACQ_CAND = [  # (tag, pid, label, true_qerr)
    ("A", 22, pair_label(22), float(qerr_all[22])),
    ("B", 26, pair_label(26), float(qerr_all[26])),
    ("C",  8, pair_label(8),  float(qerr_all[8])),
    ("D",  0, pair_label(0),  float(qerr_all[0])),
    ("E", 39, pair_label(39), float(qerr_all[39])),
]
_acq_mu  = np.array([1.60, 1.20, 0.45, 0.10, 0.06])
_acq_sd  = np.array([0.40, 0.85, 0.40, 0.08, 0.95])
ACQ_BEST = 1.25   # EI incumbent  = max observed log-qerr in seed
ACQ_TAU  = 1.40   # top-k threshold = k-th largest observed log-qerr
ACQ_BETA = 4.0    # smoothness_max adaptive beta at this iteration
ACQ_KAPPA= 2.0

def _acq_table():
    mu, sd = _acq_mu, _acq_sd
    sigma = sd.copy()
    ucb   = mu + ACQ_KAPPA * sd
    z_ei  = (mu - ACQ_BEST) / np.maximum(sd, 1e-12)
    ei    = (mu - ACQ_BEST) * np.vectorize(_norm_cdf)(z_ei) + sd * np.vectorize(_norm_pdf)(z_ei)
    bucb  = mu + ACQ_BETA * sd
    z_tk  = (mu - ACQ_TAU) / np.maximum(sd, 1e-12)
    eitk  = (mu - ACQ_TAU) * np.vectorize(_norm_cdf)(z_tk) + sd * np.vectorize(_norm_pdf)(z_tk)
    return dict(mu=mu, sd=sd, qhat=np.exp(mu), sigma=sigma, ucb=ucb,
                z_ei=z_ei, ei=ei, bucb=bucb, z_tk=z_tk, eitk=eitk)

ACQ = _acq_table()


# seeds shared by passive methods
stride_ids = sorted(set(int(v) for v in np.linspace(0, P - 1, BUDGET, dtype=int)))
import random as _random
_random.seed(SEED)
random_ids = sorted(_random.sample(range(P), BUDGET))


def interp_pairs(sample_ids):
    """Linear interp in log-qerr over pair features; nearest fallback."""
    from scipy.interpolate import LinearNDInterpolator, griddata
    sf = F[sample_ids]; sq = qerr_all[sample_ids]
    try:
        interp = LinearNDInterpolator(sf, np.log(np.maximum(sq, 1e-9)),
                                      fill_value=np.nan, rescale=True)
        log_pred = interp(F)
        if np.any(np.isnan(log_pred)):
            nm = np.isnan(log_pred)
            log_pred[nm] = griddata(sf, np.log(np.maximum(sq, 1e-9)),
                                    F[nm], method="nearest")
        return np.maximum(np.exp(log_pred), 1.0)
    except Exception:
        log_pred = griddata(sf, np.log(np.maximum(sq, 1e-9)), F, method="nearest")
        return np.maximum(np.exp(log_pred), 1.0)


# precompute everything once
RES = {
    "bo_sigma":   run_bo("sigma"),
    "bo_ucb":     run_bo("ucb", kappa=2.0),
    "bo_ei":      run_bo("ei"),
    "sm_max":     run_smoothness_max(),
    "sm_avg":     run_smoothness_avg(),
    "sm_topk":    run_smoothness_topk(),
    "gpr_fixed":  run_gpr_fixed(stride_ids),
    "ot_max":     run_ottertune("max"),
    "ot_rec":     run_ottertune("reconstruct"),
    "random_pred":  interp_pairs(random_ids),
    "stride_pred":  interp_pairs(stride_ids),
}


if __name__ == "__main__":
    np.set_printoptions(suppress=True, precision=3)
    print(f"P={P} pairs  fdim={fdim}  BUDGET={BUDGET}  N_SEED={N_SEED}")
    print(f"axis0 (x1) pairs: {(axis_arr==0).sum()}   axis1 (x2) pairs: {(axis_arr==1).sum()}")
    print("\nq-error distribution:")
    print("  min %.3f  median %.3f  mean %.3f  max %.3f"
          % (qerr_all.min(), np.median(qerr_all), qerr_all.mean(), qerr_all.max()))
    order = np.argsort(-qerr_all)
    print("\nTop-8 q-error pairs:")
    for pid in order[:8]:
        print(f"  pid {pid:2d}  {pair_label(pid):24s}  qerr={qerr_all[pid]:.3f}"
              f"  rt {ygrid[ia[pid]]:.1f}/{ygrid[ib[pid]]:.1f}")
    print("\nFirst 6 pairs (catalog order):")
    for pid in range(6):
        print(f"  pid {pid:2d}  ax{axis_arr[pid]}  mid={mid[pid]}  "
              f"{pair_label(pid):24s} qerr={qerr_all[pid]:.3f}")

    print("\nLHS seed (active methods):", RES["bo_sigma"]["seed"])
    print("stride seed:", stride_ids)
    print("random seed:", random_ids)

    s = RES["bo_sigma"]["snap"]
    print(f"\nBO-sigma snapshot: ls={s['ls']:.3f} noise={s['noise']:.1e} "
          f"pick=pid{s['pick']} ({pair_label(s['pick'])})")
    un = [i for i in range(P) if i not in s["masked"]]
    un_sorted = sorted(un, key=lambda i: -s["sd"][i])[:5]
    for pid in un_sorted:
        print(f"   pid{pid:2d} {pair_label(pid):24s} mu={s['mu'][pid]:.3f} "
              f"sd={s['sd'][pid]:.3f}")
    print("BO-sigma picks:", RES["bo_sigma"]["picks"])
    print("BO-ucb   picks:", RES["bo_ucb"]["picks"])
    print("BO-ei    picks:", RES["bo_ei"]["picks"])
    print("sm_max   picks:", RES["sm_max"]["picks"], " beta=%.3f"%RES["sm_max"]["snap"]["beta"])
    print("sm_avg   picks:", RES["sm_avg"]["picks"])
    print("sm_topk  picks:", RES["sm_topk"]["picks"], " tau=%.3f"%RES["sm_topk"]["snap"]["tau"])
