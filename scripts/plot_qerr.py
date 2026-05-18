# scripts/plot_qerr.py

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
    df["x1"],
    df["adjacent_qerr"]
)

plt.xlabel("x")
plt.ylabel("adjacent_qerr")

plt.title("Adjacent QERR")

plt.grid(True)

plt.show()

#save also