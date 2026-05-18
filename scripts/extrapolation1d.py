import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from scipy.interpolate import interp1d
from skopt import Optimizer
from tabpfn import TabPFNRegressor

df = pd.read_csv("results/tpch_truth_1d.csv")

xs = df["x"].values
ys = df["smooth_runtime"].values
raw = df["runtime"].values

n = len(xs)

# --------------------------------------
# Use first 30% points only
# --------------------------------------
CUT = int(0.30 * n)

x_train = xs[:CUT]
y_train = ys[:CUT]

# ======================================
# 1 Adaptive (slope-aware)
# ======================================
sample_idx = [0, CUT//2, CUT-1]

while len(sample_idx) < 30:
    best_gap = -1
    best_mid = None

    sample_idx = sorted(sample_idx)

    for i in range(len(sample_idx)-1):
        a = sample_idx[i]
        b = sample_idx[i+1]

        gap = b - a
        if gap > best_gap:
            best_gap = gap
            best_mid = (a+b)//2

    sample_idx.append(best_mid)

sample_idx = sorted(list(set(sample_idx)))[:30]

ax = x_train[sample_idx]
ay = y_train[sample_idx]

fa = interp1d(ax, ay, fill_value="extrapolate")
pred_a = fa(xs)

pd.DataFrame({
    "x": xs,
    "true": ys,
    "pred": pred_a
}).to_csv("results/adaptive_pred_1.csv", index=False)

# ======================================
# 2 Bayesian Optimization
# ======================================
opt = Optimizer([(1, int(x_train[-1]))])

obsx = []
obsy = []

for _ in range(30):
    xq = int(opt.ask()[0])
    idx = xq - 1
    yq = ys[idx]

    opt.tell([xq], yq)

    obsx.append(xq)
    obsy.append(yq)

obsx = np.array(obsx)
obsy = np.array(obsy)

order = np.argsort(obsx)
obsx = obsx[order]
obsy = obsy[order]

fb = interp1d(obsx, obsy, fill_value="extrapolate")
pred_b = fb(xs)

pd.DataFrame({
    "x": xs,
    "true": ys,
    "pred": pred_b
}).to_csv("results/bo_pred_1.csv", index=False)

# ======================================
# 3 TabPFN
# ======================================
idx = np.linspace(0, CUT-1, 30, dtype=int)

X_train = xs[idx].reshape(-1,1)
y_train2 = np.log1p(ys[idx])

X_all = xs.reshape(-1,1)

model = TabPFNRegressor()
model.fit(X_train, y_train2)

pred_t = np.expm1(model.predict(X_all))

pd.DataFrame({
    "x": xs,
    "true": ys,
    "pred": pred_t
}).to_csv("results/tabpfn_pred_1.csv", index=False)

# ======================================
# Plot
# ======================================
plt.figure(figsize=(12,6))

plt.plot(xs, raw, alpha=0.30, label="Raw Runtime")
plt.plot(xs, ys, lw=2, label="Smoothed Truth")

plt.plot(xs, pred_a, "--", label="Adaptive")
plt.plot(xs, pred_b, "--", label="BayesOpt")
plt.plot(xs, pred_t, "--", label="TabPFN")

plt.axvline(xs[CUT], linestyle=":", label="Observed Boundary")

plt.xlabel("x")
plt.ylabel("runtime")
plt.title("Extrapolation 1D (30% observed)")
plt.grid(True)
plt.legend()

plt.savefig("results/extrapolation1d.png", dpi=200)
plt.show()