import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ==========================================
# Load file
# ==========================================

df = pd.read_csv(
    "merged_qerr_instances.csv"
)

# ==========================================
# Clean values
# ==========================================

qerr = (
    df["qerr"]
    .replace([np.inf, -np.inf], np.nan)
    .dropna()
)

sel_diff = (
    df["selectivity_difference"]
    .replace([np.inf, -np.inf], np.nan)
    .dropna()
)

# ==========================================
# Build empirical CDF
# ==========================================

def make_cdf(x):

    x = np.sort(x)

    y = np.arange(
        1,
        len(x)+1
    ) / len(x)

    return x, y


qx, qy = make_cdf(qerr)
sx, sy = make_cdf(sel_diff)

# ==========================================
# Plot
# ==========================================

plt.figure(figsize=(10,6))

plt.plot(
    qx,
    qy,
    label="Q-error CDF"
)

plt.plot(
    sx,
    sy,
    label="Selectivity Difference CDF"
)

plt.xlabel("Value")
plt.ylabel("CDF")

plt.title(
    "CDF: Q-error vs Selectivity Difference"
)

plt.grid(True)

plt.legend()

plt.tight_layout()

plt.show()