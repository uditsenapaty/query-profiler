# =========================================================
# scripts/evaluate_interpolation.py
# =========================================================

import os
import json
import numpy as np
import pandas as pd

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

# =========================================================
# CONFIG
# =========================================================

ROOT_DIR = "interpolation_results"

# =========================================================
# QERR
# =========================================================

def qerror(y_true, y_pred):

    y_true = np.maximum(y_true, 1e-9)
    y_pred = np.maximum(y_pred, 1e-9)

    q = np.maximum(
        y_true / y_pred,
        y_pred / y_true
    )

    return q

# =========================================================
# METRICS
# =========================================================

def compute_metrics(
    y_true,
    y_pred
):

    mae = mean_absolute_error(
        y_true,
        y_pred
    )

    rmse = np.sqrt(
        mean_squared_error(
            y_true,
            y_pred
        )
    )

    r2 = r2_score(
        y_true,
        y_pred
    )

    mape = np.mean(
        np.abs(
            (y_true - y_pred)
            / np.maximum(y_true, 1e-9)
        )
    ) * 100

    q = qerror(
        y_true,
        y_pred
    )

    metrics = {

        "MAE": float(mae),

        "RMSE": float(rmse),

        "R2": float(r2),

        "MAPE": float(mape),

        "QERR_MEAN": float(np.mean(q)),

        "QERR_MEDIAN": float(np.median(q)),

        "QERR_P90": float(
            np.percentile(q, 90)
        ),

        "QERR_P95": float(
            np.percentile(q, 95)
        ),

        "QERR_MAX": float(np.max(q)),
    }

    return metrics

# =========================================================
# RUN
# =========================================================

all_results = []

methods = sorted(os.listdir(ROOT_DIR))

print("\n================================================")
print("INTERPOLATION EVALUATION")
print("================================================")

for method in methods:

    method_dir = os.path.join(
        ROOT_DIR,
        method
    )

    if not os.path.isdir(method_dir):
        continue

    pred_file = os.path.join(
        method_dir,
        "predictions.csv"
    )

    if not os.path.exists(pred_file):
        continue

    df = pd.read_csv(pred_file)

    y_true = df["y_true"].values
    y_pred = df["y_pred"].values

    metrics = compute_metrics(
        y_true,
        y_pred
    )

    metrics["method"] = method

    all_results.append(metrics)

    print(f"\n{method}")

    for k, v in metrics.items():

        if k == "method":
            continue

        print(f"  {k:15s}: {v:.6f}")

    with open(
        os.path.join(
            method_dir,
            "metrics.json"
        ),
        "w"
    ) as f:

        json.dump(
            metrics,
            f,
            indent=2
        )

# =========================================================
# SAVE SUMMARY
# =========================================================

summary = pd.DataFrame(
    all_results
)

summary = summary.sort_values(
    "RMSE"
)

summary_csv = os.path.join(
    ROOT_DIR,
    "summary.csv"
)

summary.to_csv(
    summary_csv,
    index=False
)

print("\n================================================")
print("SUMMARY")
print("================================================")

print(summary)

print(f"\nSaved summary: {summary_csv}")