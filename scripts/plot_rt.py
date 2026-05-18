# scripts/plot_rt.py

# =========================================================
from pathlib import Path

from config_gt import RESULTS_DIR
from config_gt import RESULTS_FILENAME
CSV_PATH = Path(RESULTS_DIR) / Path(RESULTS_FILENAME)
# =========================================================

import pandas as pd
import matplotlib.pyplot as plt

plt.figure(figsize=(12,6))

plt.plot(
    df["x"],
    df["runtime"],
    label="Avg Runtime"
)

plt.xlabel("x")
plt.ylabel("runtime")
plt.title("TPC-H Runtime Surface")

plt.grid(True)
#plt.legend()

plt.show()


#save also