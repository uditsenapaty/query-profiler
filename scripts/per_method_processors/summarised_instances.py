# ==========================================================
# scripts/per_method_processors/summarised_instances.py
# ==========================================================

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config_gt


# =========================================================
# Processor entry
# =========================================================

def run(results_dir):

    results_dir = Path(results_dir)

    csv_path = results_dir / config_gt.RESULTS_FILENAME

    output_dir = results_dir / "summaries"
    output_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 60)
    print("QERR SINGLE MAX SUMMARY")
    print("=" * 60)

    # =====================================================
    # LOAD
    # =====================================================

    if not csv_path.exists():
        print(f"Missing:\n{csv_path}")
        return

    df = pd.read_csv(csv_path)

    # =====================================================
    # MERGE AXES (MAX QERR PER INSTANCE)
    # =====================================================

    rows = []

    qcols = sorted([
        c for c in df.columns
        if c.startswith("adjacent_qerr_x")
    ])

    instance_rank = 0

    for _, base_row in df.iterrows():

        instance_rank += 1

        max_qerr = -np.inf
        max_axis = None

        for qcol in qcols:

            axis = int(qcol.split("_x")[-1])

            pcol = f"plan_change_x{axis}"

            if pcol not in df.columns:
                continue

            q = base_row.get(qcol, np.nan)

            if not np.isfinite(q):
                continue

            if q <= 0:
                continue

            if q > max_qerr:

                max_qerr = q
                max_axis = axis
                max_plan_change = bool(base_row[pcol])

        if max_axis is None:
            continue

        rows.append({
            "rank": instance_rank,
            "instance_id": base_row.get("instance_id", instance_rank),
            "x1": base_row.get("x1"),
            "x2": base_row.get("x2"),
            "max_qerr": max_qerr,
            "plan_change": max_plan_change
        })

    merged = pd.DataFrame(rows)

    if merged.empty:
        print("No valid rows.")
        return

    merged = merged[np.isfinite(merged["max_qerr"])]
    merged = merged[merged["max_qerr"] > 0]

    # =====================================================
    # TOP 1 GLOBAL MAX-QERR INSTANCE
    # =====================================================

    top1 = merged.sort_values(
        "max_qerr",
        ascending=False
    ).head(1).reset_index(drop=True)

    row = top1.iloc[0]

    # =====================================================
    # TOP 1000 STATS
    # =====================================================

    top1000 = merged.sort_values(
        "max_qerr",
        ascending=False
    ).head(1000)

    plan_yes = (top1000["plan_change"] == True).sum()
    plan_no = (top1000["plan_change"] == False).sum()

    # =====================================================
    # FINAL OUTPUT
    # =====================================================

    final_df = pd.DataFrame([{
        "rank": int(row["rank"]),
        "instance_id": row["instance_id"],
        "x1": row["x1"],
        "x2": row["x2"],
        "max_qerr": row["max_qerr"],
        "top1000_planchange_yes": int(plan_yes),
        "top1000_planchange_no": int(plan_no)
    }])

    print()
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(final_df)

    # =====================================================
    # SAVE
    # =====================================================

    out_csv = output_dir / "summary.csv"
    final_df.to_csv(out_csv, index=False)

    print(f"Saved:\n{out_csv}")
    print()
    print("DONE")


if __name__ == "__main__":

    run(
        "gt_results_sf10_qt8/100x100/m1"
    )