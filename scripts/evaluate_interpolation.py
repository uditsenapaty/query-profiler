#!/usr/bin/env python3
# =========================================================
# scripts/evaluate_interpolation.py
# =========================================================
#
# Evaluates all method sub-directories under ROOT_DIR.
#
# y_true = true pair q-error  (≥ 1)
# y_pred = predicted pair q-error
#
# Two evaluation splits:
#   ALL    — all pair instances (sampled + unseen)
#   UNSEEN — only pairs NOT sampled by the method
#            → primary signal: actual interpolation accuracy
#
# Extra metrics beyond prediction accuracy:
#   max_qerr_found  — highest true q-error among sampled pairs
#                     (did the method find the worst pairs?)
#   coverage_2x     — % of pairs with true qerr > 2 that were sampled
#   coverage_5x     — % of pairs with true qerr > 5 that were sampled
# =========================================================

import os
import json
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# =========================================================
# CONFIG
# =========================================================

ROOT_DIR      = "gt_results_sf1_10x10_s1q0/qt5/m2/interpolation_results"
SORT_BY       = "QERR_MEDIAN_UNSEEN"   # primary ranking column
TOP_K_PERCENT = 0.10                   # fraction for S_topk

# =========================================================
# METRIC FUNCTIONS
# =========================================================

def pred_qerror(y_true, y_pred):
    """Q-error of prediction: how far off is our qerr estimate."""
    yt = np.maximum(np.asarray(y_true, float), 1e-9)
    yp = np.maximum(np.asarray(y_pred, float), 1e-9)
    return np.maximum(yt / yp, yp / yt)


def compute_metrics(y_true, y_pred, prefix=""):
    yt = np.asarray(y_true, float)
    yp = np.maximum(np.asarray(y_pred, float), 1e-9)
    nan = float("nan")
    if len(yt) == 0:
        keys = ["MAE", "RMSE", "R2", "MAPE",
                "QERR_MEAN", "QERR_MEDIAN", "QERR_P90", "QERR_P95", "QERR_MAX",
                "WITHIN_2X", "WITHIN_5X"]
        return {f"{k}{prefix}": nan for k in keys}

    pq = pred_qerror(yt, yp)
    try:
        r2 = float(r2_score(yt, yp))
    except Exception:
        r2 = nan

    return {
        f"MAE{prefix}"        : float(mean_absolute_error(yt, yp)),
        f"RMSE{prefix}"       : float(np.sqrt(mean_squared_error(yt, yp))),
        f"R2{prefix}"         : r2,
        f"MAPE{prefix}"       : float(np.mean(np.abs((yt - yp)
                                                      / np.maximum(yt, 1e-9))) * 100),
        f"QERR_MEAN{prefix}"  : float(np.mean(pq)),
        f"QERR_MEDIAN{prefix}": float(np.median(pq)),
        f"QERR_P90{prefix}"   : float(np.percentile(pq, 90)),
        f"QERR_P95{prefix}"   : float(np.percentile(pq, 95)),
        f"QERR_MAX{prefix}"   : float(np.max(pq)),
        f"WITHIN_2X{prefix}"  : float(np.mean(pq <= 2.0) * 100),
        f"WITHIN_5X{prefix}"  : float(np.mean(pq <= 5.0) * 100),
    }


# =========================================================
# RUN
# =========================================================

print("\n================================================")
print("PAIR Q-ERROR INTERPOLATION EVALUATION")
print("================================================\n")

all_results = []

for method in sorted(os.listdir(ROOT_DIR)):
    method_dir = os.path.join(ROOT_DIR, method)
    pred_file  = os.path.join(method_dir, "predictions.csv")
    meta_file  = os.path.join(method_dir, "metadata.json")

    if not os.path.isdir(method_dir) or not os.path.exists(pred_file):
        continue

    df = pd.read_csv(pred_file)
    if "y_true" not in df.columns or "y_pred" not in df.columns:
        print(f"[SKIP] {method}: missing y_true / y_pred")
        continue

    has_flag    = "is_sampled" in df.columns
    unseen_mask = (df["is_sampled"] == 0) if has_flag else pd.Series(True, index=df.index)

    yt_all    = df["y_true"].values
    yp_all    = df["y_pred"].values
    yt_unseen = df.loc[unseen_mask, "y_true"].values
    yp_unseen = df.loc[unseen_mask, "y_pred"].values

    meta = {}
    if os.path.exists(meta_file):
        with open(meta_file) as f:
            meta = json.load(f)

    # sampling discovery metrics
    sampled_mask   = (df["is_sampled"] == 1) if has_flag else pd.Series(False, index=df.index)
    yt_sampled     = df.loc[sampled_mask, "y_true"].values
    max_qerr_true  = float(yt_all.max()) if len(yt_all) else float("nan")
    max_qerr_found = float(yt_sampled.max()) if len(yt_sampled) else float("nan")
    n_above_2  = int((yt_all > 2.0).sum())
    n_above_5  = int((yt_all > 5.0).sum())
    found_2    = int((yt_sampled > 2.0).sum()) if len(yt_sampled) else 0
    found_5    = int((yt_sampled > 5.0).sum()) if len(yt_sampled) else 0
    coverage_2 = 100.0 * found_2 / n_above_2 if n_above_2 else float("nan")
    coverage_5 = 100.0 * found_5 / n_above_5 if n_above_5 else float("nan")

    # S-estimation metrics (on full pair universe using y_pred vs y_true)
    k_topk = max(1, int(TOP_K_PERCENT * len(yt_all)))
    s_max_true  = float(np.max(yt_all))             if len(yt_all) else float("nan")
    s_avg_true  = float(np.mean(yt_all))            if len(yt_all) else float("nan")
    s_topk_true = float(np.mean(np.sort(yt_all)[-k_topk:])) if len(yt_all) else float("nan")
    s_max_est   = float(np.max(yp_all))             if len(yp_all) else float("nan")
    s_avg_est   = float(np.mean(yp_all))            if len(yp_all) else float("nan")
    s_topk_est  = float(np.mean(np.sort(yp_all)[-k_topk:])) if len(yp_all) else float("nan")
    def _rel_err(est, true):
        if true == 0 or np.isnan(true) or np.isnan(est):
            return float("nan")
        return abs(est - true) / true * 100.0
    s_max_relerr  = _rel_err(s_max_est,  s_max_true)
    s_avg_relerr  = _rel_err(s_avg_est,  s_avg_true)
    s_topk_relerr = _rel_err(s_topk_est, s_topk_true)

    row = {"method": method}
    row.update(compute_metrics(yt_all,    yp_all,    prefix="_ALL"))
    row.update(compute_metrics(yt_unseen, yp_unseen, prefix="_UNSEEN"))
    row["budget"]          = int(meta.get("budget_pairs", meta.get("budget", -1)))
    row["budget_percent"]  = float(meta.get("budget_percent", float("nan")))
    row["sample_fraction"] = float(meta.get("sample_fraction", float("nan")))
    row["num_all"]         = int(len(yt_all))
    row["num_unseen"]      = int(len(yt_unseen))
    row["dimension"]       = int(meta.get("dimension", -1))
    row["max_qerr_true"]   = max_qerr_true
    row["max_qerr_found"]  = max_qerr_found
    row["coverage_2x_pct"] = coverage_2
    row["coverage_5x_pct"] = coverage_5
    row["S_max_true"]      = s_max_true
    row["S_avg_true"]      = s_avg_true
    row["S_topk_true"]     = s_topk_true
    row["S_max_est"]       = s_max_est
    row["S_avg_est"]       = s_avg_est
    row["S_topk_est"]      = s_topk_est
    row["S_max_relerr"]    = s_max_relerr
    row["S_avg_relerr"]    = s_avg_relerr
    row["S_topk_relerr"]   = s_topk_relerr

    all_results.append(row)

    print(f"{'='*54}")
    print(f"Method : {method}")
    print(f"  budget         : {row['budget']}  "
          f"({row['sample_fraction']*100:.1f}% of {row['num_all']} pairs)")
    print(f"  unseen pairs   : {row['num_unseen']}")
    print()
    print(f"  {'Metric':<24}  {'ALL':>10}  {'UNSEEN':>10}")
    print(f"  {'-'*48}")
    metric_pairs = [
        ("MAE",          "MAE"),
        ("RMSE",         "RMSE"),
        ("R2",           "R2"),
        ("MAPE (%)",     "MAPE"),
        ("QERR_MEAN",    "QERR_MEAN"),
        ("QERR_MEDIAN",  "QERR_MEDIAN"),
        ("QERR_P90",     "QERR_P90"),
        ("QERR_P95",     "QERR_P95"),
        ("QERR_MAX",     "QERR_MAX"),
        ("WITHIN_2X (%)", "WITHIN_2X"),
        ("WITHIN_5X (%)", "WITHIN_5X"),
    ]
    for label, key in metric_pairs:
        v_all    = row.get(f"{key}_ALL",    float("nan"))
        v_unseen = row.get(f"{key}_UNSEEN", float("nan"))
        print(f"  {label:<24}  {v_all:>10.4f}  {v_unseen:>10.4f}")
    print()
    print(f"  Max true qerr  : {max_qerr_true:.3f}")
    print(f"  Max qerr found : {max_qerr_found:.3f}  "
          f"({100*max_qerr_found/max(max_qerr_true,1e-9):.1f}% of true max)")
    print(f"  Coverage >2x   : {found_2}/{n_above_2}  ({coverage_2:.1f}%)")
    print(f"  Coverage >5x   : {found_5}/{n_above_5}  ({coverage_5:.1f}%)")
    print()
    print(f"  {'Smoothness':<24}  {'True':>10}  {'Est':>10}  {'RelErr%':>10}")
    print(f"  {'-'*58}")
    print(f"  {'S_max':<24}  {s_max_true:>10.4f}  {s_max_est:>10.4f}  {s_max_relerr:>10.2f}")
    print(f"  {'S_avg':<24}  {s_avg_true:>10.4f}  {s_avg_est:>10.4f}  {s_avg_relerr:>10.2f}")
    topk_label = f"S_topk(top {TOP_K_PERCENT*100:.0f}%)"
    print(f"  {topk_label:<24}  {s_topk_true:>10.4f}  {s_topk_est:>10.4f}  {s_topk_relerr:>10.2f}")
    print()

    with open(os.path.join(method_dir, "metrics.json"), "w") as f:
        json.dump(row, f, indent=2)


# =========================================================
# SUMMARY TABLE
# =========================================================

if not all_results:
    print("No results found — run interpolation.py first.")
else:
    summary = pd.DataFrame(all_results)
    if SORT_BY in summary.columns:
        summary = summary.sort_values(SORT_BY).reset_index(drop=True)
        summary.insert(0, "rank", summary.index + 1)

    summary_csv = os.path.join(ROOT_DIR, "summary.csv")
    summary.to_csv(summary_csv, index=False)

    print("\n================================================")
    print(f"RANKED SUMMARY  (sorted by {SORT_BY})")
    print("================================================\n")

    show_cols = [
        "rank", "method", "budget", "sample_fraction",
        "QERR_MEDIAN_UNSEEN", "QERR_P90_UNSEEN", "QERR_MAX_UNSEEN",
        "WITHIN_2X_UNSEEN", "WITHIN_5X_UNSEEN",
        "RMSE_UNSEEN", "R2_UNSEEN",
        "max_qerr_found", "coverage_2x_pct", "coverage_5x_pct",
        "S_max_relerr", "S_avg_relerr", "S_topk_relerr",
    ]
    show_cols = [c for c in show_cols if c in summary.columns]

    with pd.option_context("display.max_columns", None,
                           "display.width",       220,
                           "display.float_format", "{:.4f}".format):
        print(summary[show_cols].to_string(index=False))

    print(f"\nSaved: {summary_csv}")

    gpr_names  = {m for m in summary["method"]
                  if any(k in m for k in ("gpr", "bo_generic", "ottertune"))}
    base_names = set(summary["method"]) - gpr_names - {"ground_truth"}

    if gpr_names and SORT_BY in summary.columns:
        best_gpr  = summary.loc[summary["method"].isin(gpr_names),  SORT_BY].min()
        best_base = summary.loc[summary["method"].isin(base_names),  SORT_BY].min()
        print(f"\n  Best GPR/BO  {SORT_BY}: {best_gpr:.4f}")
        print(f"  Best baseline {SORT_BY}: {best_base:.4f}")
