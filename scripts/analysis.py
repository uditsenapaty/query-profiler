# =========================================================
# scripts/analysis.py
# =========================================================

from pathlib import Path
import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scipy.stats import entropy, ks_2samp, mannwhitneyu, ttest_rel, pearsonr, spearmanr

# =========================================================
# CONFIG
# =========================================================

ROOT1 = "gt_results_sf1_qt8_10x10_m0"
ROOT2 = "gt_results_sf1_qt8_10x10_m1"
LABELS = {
    ROOT1: "data-space sampling",
    ROOT2: "selectivity-space sampling",
}

OUT = Path("Analysis")
PLOTS = OUT / "plots"
TABLES = OUT / "tables"
OUT.mkdir(parents=True, exist_ok=True)
PLOTS.mkdir(parents=True, exist_ok=True)
TABLES.mkdir(parents=True, exist_ok=True)

# =========================================================
# HELPERS
# =========================================================

def load_gt(root):
    path = Path(root) / "merged_qerr_instances" / "all_qerr_instances_desc.csv"
    df = pd.read_csv(path)
    df["source_root"] = root
    df["source_label"] = LABELS.get(root, root)
    if "plan_change" in df.columns:
        df["plan_change"] = df["plan_change"].astype(bool)
    if "axis" in df.columns:
        df["axis"] = df["axis"].astype(int)
    return df

# =========================================================
# STATS
# =========================================================

def compute_stats(df):
    q = df["qerr"].astype(float)
    if q.empty:
        return {}
    stats = {
        "count": int(len(q)),
        "min": float(np.min(q)),
        "p5": float(np.percentile(q, 5)),
        "p10": float(np.percentile(q, 10)),
        "p25": float(np.percentile(q, 25)),
        "median": float(np.median(q)),
        "p75": float(np.percentile(q, 75)),
        "p90": float(np.percentile(q, 90)),
        "p95": float(np.percentile(q, 95)),
        "p99": float(np.percentile(q, 99)),
        "max": float(np.max(q)),
        "mean": float(np.mean(q)),
        "std": float(np.std(q, ddof=0)),
        "iqr": float(np.percentile(q, 75) - np.percentile(q, 25)),
        "skew": float(pd.Series(q).skew()),
        "kurtosis": float(pd.Series(q).kurtosis()),
        "plan_change_rate": float(df["plan_change"].mean()) if "plan_change" in df.columns else np.nan,
    }
    if "plan_hash" in df.columns:
        counts = df["plan_hash"].value_counts()
        stats["unique_plans"] = int(len(counts))
        stats["plan_entropy"] = float(entropy(counts.values))
    if "axis" in df.columns:
        stats["axis_count"] = int(df["axis"].nunique())
    return stats


def compute_group_stats(df, group_by):
    rows = []
    for key, group in df.groupby(group_by):
        stats = compute_stats(group)
        stats[group_by] = key
        rows.append(stats)
    return pd.DataFrame(rows).set_index(group_by)


def compare_pairwise(df1, df2):
    merged = pd.merge(
        df1,
        df2,
        on=["instance_id", "axis"],
        suffixes=("_data", "_selectivity"),
        how="inner",
    )
    merged["qerr_delta"] = merged["qerr_data"] - merged["qerr_selectivity"]
    merged["qerr_ratio"] = merged["qerr_data"] / merged["qerr_selectivity"].replace(0, np.nan)
    merged["prefer"] = np.where(
        merged["qerr_data"] < merged["qerr_selectivity"],
        LABELS[ROOT1],
        np.where(merged["qerr_data"] > merged["qerr_selectivity"], LABELS[ROOT2], "tie"),
    )
    merged["absolute_improvement"] = np.abs(merged["qerr_delta"])
    merged["relative_improvement"] = merged["absolute_improvement"] / np.maximum(
        merged[["qerr_data", "qerr_selectivity"]].min(axis=1), 1e-9
    )
    if {"plan_change_data", "plan_change_selectivity"}.issubset(merged.columns):
        merged["plan_change_agreement"] = merged["plan_change_data"] == merged["plan_change_selectivity"]
    return merged


def distribution_tests(df1, df2, matched=None):
    q1 = df1["qerr"].astype(float)
    q2 = df2["qerr"].astype(float)
    ks = ks_2samp(q1, q2)
    mw = mannwhitneyu(q1, q2, alternative="two-sided")
    tests = {
        "ks_statistic": float(ks.statistic),
        "ks_p_value": float(ks.pvalue),
        "mannwhitney_u": float(mw.statistic),
        "mannwhitney_p_value": float(mw.pvalue),
    }
    if matched is not None and len(matched) > 1:
        matched_q1 = matched["qerr_data"].astype(float)
        matched_q2 = matched["qerr_selectivity"].astype(float)
        ttest = ttest_rel(matched_q1, matched_q2)
        tests.update({
            "paired_t_statistic": float(ttest.statistic),
            "paired_t_p_value": float(ttest.pvalue),
            "paired_mean_delta": float(np.mean(matched_q1 - matched_q2)),
            "paired_median_delta": float(np.median(matched_q1 - matched_q2)),
            "paired_positive_delta_rate": float(np.mean((matched_q1 - matched_q2) > 0)),
            "paired_negative_delta_rate": float(np.mean((matched_q1 - matched_q2) < 0)),
        })
    return tests


def correlation_report(df):
    report = {}
    q = df["qerr"].astype(float)
    if {"x1", "x2"}.issubset(df.columns):
        for axis_name in ["x1", "x2"]:
            values = df[axis_name].astype(float)
            if values.nunique() > 1:
                report[f"pearson_{axis_name}"] = float(pearsonr(values, q)[0])
                report[f"spearman_{axis_name}"] = float(spearmanr(values, q)[0])
    return report


def save_json(data, path):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def save_text(lines, path):
    with open(path, "w") as f:
        f.write("\n".join(lines))


def save_plot(fig, name):
    target = PLOTS / name
    fig.tight_layout()
    fig.savefig(target, dpi=300)
    plt.close(fig)


def plot_ecdf(series, label, ax, color=None):
    q = np.sort(series.astype(float))
    y = np.arange(1, len(q) + 1) / len(q)
    ax.plot(q, y, label=label, color=color, linewidth=1.8)
    ax.set_xscale("log")
    ax.set_xlabel("QERR")
    ax.set_ylabel("CDF")
    ax.grid(True, alpha=0.35)


def plot_histogram(df, label, ax, color=None):
    ax.hist(df["qerr"].astype(float), bins=80, alpha=0.5, label=label, color=color)
    ax.set_xscale("log")
    ax.set_xlabel("QERR")
    ax.set_ylabel("Count")
    ax.grid(True, alpha=0.35)


def plot_boxplot(groups, labels, title, name):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.boxplot(groups, labels=labels, showfliers=False, patch_artist=True)
    ax.set_yscale("log")
    ax.set_ylabel("QERR")
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    save_plot(fig, name)


def plot_scatter(x, y, title, xlabel, ylabel, name, log_scale=True):
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(x, y, s=12, alpha=0.35)
    diagonal = [min(x.min(), y.min()), max(x.max(), y.max())]
    ax.plot(diagonal, diagonal, color="red", linewidth=1)
    if log_scale:
        ax.set_xscale("log")
        ax.set_yscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    save_plot(fig, name)


def plot_scatter_color(x, y, c, title, xlabel, ylabel, name, log_x=False, log_y=False):
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(x, y, c=c, cmap="viridis", s=15, alpha=0.75)
    fig.colorbar(scatter, ax=ax, label="QERR")
    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    save_plot(fig, name)


def plot_topk_comparison(df1, df2, label1, label2, name, k=50):
    df1_sorted = df1.sort_values("qerr", ascending=False).head(k).reset_index(drop=True)
    df2_sorted = df2.sort_values("qerr", ascending=False).head(k).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(df1_sorted["qerr"].values, label=label1, marker="o")
    ax.plot(df2_sorted["qerr"].values, label=label2, marker="o")
    ax.set_yscale("log")
    ax.set_xlabel("Rank")
    ax.set_ylabel("QERR")
    ax.set_title(f"Top {k} QERR values")
    ax.legend()
    ax.grid(True, alpha=0.35)
    save_plot(fig, name)


def plot_diff_histogram(series, title, name):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(series, bins=80, alpha=0.75, color="tab:purple")
    ax.set_xlabel("QERR difference")
    ax.set_ylabel("Count")
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    save_plot(fig, name)


def plot_ratio_histogram(series, title, name):
    series = series.replace([np.inf, -np.inf], np.nan).dropna()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(series, bins=80, alpha=0.75, color="tab:orange")
    ax.set_xlabel("QERR ratio")
    ax.set_ylabel("Count")
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    save_plot(fig, name)


def plot_grouped_by_axis(df1, df2, label1, label2, name):
    axes = sorted(df1["axis"].unique())
    fig, ax = plt.subplots(figsize=(10, 6))
    groups = []
    positions = []
    labels = []
    for offset, (df, label) in enumerate([(df1, label1), (df2, label2)]):
        for axis in axes:
            groups.append(df[df["axis"] == axis]["qerr"].astype(float))
            positions.append(axis + offset * 0.25)
            labels.append(f"{label}, axis={axis}")
    ax.boxplot(groups, positions=positions, labels=labels, showfliers=False, patch_artist=True)
    ax.set_yscale("log")
    ax.set_ylabel("QERR")
    ax.set_title("QERR by sampling method and axis")
    ax.grid(True, alpha=0.35)
    fig.autofmt_xdate(rotation=20)
    save_plot(fig, name)


def write_research_report(overall_stats, axis_stats, plan_stats, pairwise_stats, tests, correlations, path):
    lines = [
        "RESEARCH SUMMARY: DATA-SPACE VS SELECTIVITY-SPACE SAMPLING",
        "",
        f"Data-space sampling root: {ROOT1}",
        f"Selectivity-space sampling root: {ROOT2}",
        "",
        "Global dataset sizes:",
        f"  {LABELS[ROOT1]}: {overall_stats[ROOT1]['count']}",
        f"  {LABELS[ROOT2]}: {overall_stats[ROOT2]['count']}",
        "",
        "Core distribution metrics (median / p95 / max):",
        f"  {LABELS[ROOT1]}: median={overall_stats[ROOT1]['median']:.3f}, p95={overall_stats[ROOT1]['p95']:.3f}, max={overall_stats[ROOT1]['max']:.3f}",
        f"  {LABELS[ROOT2]}: median={overall_stats[ROOT2]['median']:.3f}, p95={overall_stats[ROOT2]['p95']:.3f}, max={overall_stats[ROOT2]['max']:.3f}",
        "",
        "Plan change rate:",
        f"  {LABELS[ROOT1]}: {overall_stats[ROOT1]['plan_change_rate']:.4f}",
        f"  {LABELS[ROOT2]}: {overall_stats[ROOT2]['plan_change_rate']:.4f}",
        "",
        "Matched analysis on same instance_id + axis pairs:",
        f"  matched samples: {pairwise_stats['matched_count']}",
        f"  {LABELS[ROOT1]} lower QERR: {pairwise_stats['prefer_data_percent']:.2f}%",
        f"  {LABELS[ROOT2]} lower QERR: {pairwise_stats['prefer_selectivity_percent']:.2f}%",
        f"  ties: {pairwise_stats['ties_percent']:.2f}%",
        "",
        "Pairwise average performance:",
        f"  mean delta (data - selectivity): {pairwise_stats['mean_delta']:.4f}",
        f"  median delta (data - selectivity): {pairwise_stats['median_delta']:.4f}",
        "",
        "Distribution comparison tests:",
        f"  KS statistic: {tests['ks_statistic']:.6f}, p-value: {tests['ks_p_value']:.6e}",
        f"  Mann-Whitney U: {tests['mannwhitney_u']:.6f}, p-value: {tests['mannwhitney_p_value']:.6e}",
    ]
    if "paired_t_statistic" in tests:
        lines += [
            f"  Paired t-test statistic: {tests['paired_t_statistic']:.6f}, p-value: {tests['paired_t_p_value']:.6e}",
            f"  Paired mean delta: {tests['paired_mean_delta']:.4f}",
            f"  Paired median delta: {tests['paired_median_delta']:.4f}",
        ]
    lines += [
        "",
        "Correlations between QERR and selectivity dimensions:",
    ]
    for method, corr in correlations.items():
        lines.append(f"  {method}:")
        if corr:
            for key, value in corr.items():
                lines.append(f"    {key}: {value:.6f}")
        else:
            lines.append("    no selectivity correlations available")
    lines += [
        "",
        "Axis-level median comparisons:",
    ]
    for axis, row in axis_stats.items():
        lines.append(
            f"  axis={axis}: {LABELS[ROOT1]} median={row[f'{ROOT1}_median']:.3f}, {LABELS[ROOT2]} median={row[f'{ROOT2}_median']:.3f}"
        )
    save_text(lines, path)


def build_axis_comparison_table(df1, df2):
    results = []
    all_axes = sorted(set(df1["axis"].unique()) | set(df2["axis"].unique()))
    for axis in all_axes:
        row = {"axis": axis}
        g1 = df1[df1["axis"] == axis]
        g2 = df2[df2["axis"] == axis]
        row.update({f"{ROOT1}_{k}": v for k, v in compute_stats(g1).items()})
        row.update({f"{ROOT2}_{k}": v for k, v in compute_stats(g2).items()})
        results.append(row)
    return pd.DataFrame(results).set_index("axis")


def build_plan_change_table(df1, df2):
    rows = []
    for value in [False, True]:
        row = {"plan_change": value}
        g1 = df1[df1["plan_change"] == value]
        g2 = df2[df2["plan_change"] == value]
        row.update({f"{ROOT1}_{k}": v for k, v in compute_stats(g1).items()})
        row.update({f"{ROOT2}_{k}": v for k, v in compute_stats(g2).items()})
        rows.append(row)
    return pd.DataFrame(rows).set_index("plan_change")


def main():
    gt1 = load_gt(ROOT1)
    gt2 = load_gt(ROOT2)

    overall = {ROOT1: compute_stats(gt1), ROOT2: compute_stats(gt2)}
    axis_comparison = build_axis_comparison_table(gt1, gt2)
    planchange_comparison = build_plan_change_table(gt1, gt2)
    matched = compare_pairwise(gt1, gt2)
    matched.to_csv(TABLES / "matched_instance_comparison.csv", index=False, float_format="%.6f")
    tests = distribution_tests(gt1, gt2, matched)
    correlations = {
        LABELS[ROOT1]: correlation_report(gt1),
        LABELS[ROOT2]: correlation_report(gt2),
    }

    axis_stats = {}
    for axis in sorted(set(gt1["axis"].unique()) | set(gt2["axis"].unique())):
        axis_stats[axis] = {f"{ROOT1}_{k}": v for k, v in compute_stats(gt1[gt1["axis"] == axis]).items()}
        axis_stats[axis].update({f"{ROOT2}_{k}": v for k, v in compute_stats(gt2[gt2["axis"] == axis]).items()})

    pairwise_stats = {
        "matched_count": int(len(matched)),
        "prefer_data_count": int((matched["prefer"] == LABELS[ROOT1]).sum()),
        "prefer_selectivity_count": int((matched["prefer"] == LABELS[ROOT2]).sum()),
        "ties_count": int((matched["prefer"] == "tie").sum()),
    }
    pairwise_stats["prefer_data_percent"] = 100 * pairwise_stats["prefer_data_count"] / pairwise_stats["matched_count"]
    pairwise_stats["prefer_selectivity_percent"] = 100 * pairwise_stats["prefer_selectivity_count"] / pairwise_stats["matched_count"]
    pairwise_stats["ties_percent"] = 100 * pairwise_stats["ties_count"] / pairwise_stats["matched_count"]
    pairwise_stats["mean_delta"] = float(matched["qerr_delta"].mean())
    pairwise_stats["median_delta"] = float(matched["qerr_delta"].median())

    summary_df = pd.DataFrame(overall).T
    summary_df.to_csv(OUT / "summary.csv", float_format="%.6f")
    save_json(overall, OUT / "summary.json")
    axis_comparison.to_csv(OUT / "axis_summary.csv", float_format="%.6f")
    planchange_comparison.to_csv(OUT / "planchange_summary.csv", float_format="%.6f")

    comparison_summary = {
        "matched_count": pairwise_stats["matched_count"],
        "mean_delta": pairwise_stats["mean_delta"],
        "median_delta": pairwise_stats["median_delta"],
        "data_better_count": pairwise_stats["prefer_data_count"],
        "selectivity_better_count": pairwise_stats["prefer_selectivity_count"],
        "tie_count": pairwise_stats["ties_count"],
    }
    save_json(comparison_summary, OUT / "matched_summary.json")

    write_research_report(
        overall,
        axis_stats,
        planchange_comparison.to_dict("index"),
        pairwise_stats,
        tests,
        {"data-space": correlations[LABELS[ROOT1]], "selectivity-space": correlations[LABELS[ROOT2]]},
        OUT / "research_summary.txt",
    )

    fig, ax = plt.subplots(figsize=(8, 5))
    plot_ecdf(gt1["qerr"], LABELS[ROOT1], ax, color="tab:blue")
    plot_ecdf(gt2["qerr"], LABELS[ROOT2], ax, color="tab:orange")
    ax.legend()
    save_plot(fig, "cdf_qerr_comparison.png")

    fig, ax = plt.subplots(figsize=(8, 5))
    plot_histogram(gt1, LABELS[ROOT1], ax, color="tab:blue")
    plot_histogram(gt2, LABELS[ROOT2], ax, color="tab:orange")
    ax.legend()
    save_plot(fig, "histogram_qerr_comparison.png")

    plot_boxplot([gt1["qerr"], gt2["qerr"]], [LABELS[ROOT1], LABELS[ROOT2]], "QERR distribution comparison", "boxplot_overview.png")
    plot_topk_comparison(gt1, gt2, LABELS[ROOT1], LABELS[ROOT2], "topk_qerr_comparison.png", k=50)
    plot_scatter(
        matched["qerr_data"],
        matched["qerr_selectivity"],
        "Matched QERR: data-space vs selectivity-space",
        f"{LABELS[ROOT1]} QERR",
        f"{LABELS[ROOT2]} QERR",
        "paired_qerr_scatter.png",
    )
    plot_diff_histogram(matched["qerr_delta"], "Histogram of QERR differences (data-space minus selectivity-space)", "qerr_difference_histogram.png")
    plot_ratio_histogram(matched["qerr_ratio"], "Histogram of QERR ratios (data-space / selectivity-space)", "qerr_ratio_histogram.png")
    plot_grouped_by_axis(gt1, gt2, LABELS[ROOT1], LABELS[ROOT2], "boxplot_axis_comparison.png")

    if {"x1", "x2"}.issubset(gt1.columns):
        plot_scatter_color(
            gt1["x1"],
            gt1["x2"],
            gt1["qerr"],
            f"{LABELS[ROOT1]} QERR by (x1, x2)",
            "x1",
            "x2",
            "data_space_x1_x2_scatter.png",
            log_x=False,
            log_y=False,
        )
    if {"x1", "x2"}.issubset(gt2.columns):
        plot_scatter_color(
            gt2["x1"],
            gt2["x2"],
            gt2["qerr"],
            f"{LABELS[ROOT2]} QERR by (x1, x2)",
            "x1",
            "x2",
            "selectivity_space_x1_x2_scatter.png",
            log_x=False,
            log_y=False,
        )

    if "plan_change" in gt1.columns and "plan_change" in gt2.columns:
        for mask, label in [(False, "no_plan_change"), (True, "plan_change")]:
            fig, ax = plt.subplots(figsize=(8, 5))
            plot_ecdf(gt1[gt1["plan_change"] == mask]["qerr"], f"{LABELS[ROOT1]} {label}", ax, color="tab:blue")
            plot_ecdf(gt2[gt2["plan_change"] == mask]["qerr"], f"{LABELS[ROOT2]} {label}", ax, color="tab:orange")
            ax.legend()
            save_plot(fig, f"cdf_plan_change_{label}.png")

    print("Analysis complete.")
    print(f"Saved outputs to {OUT.resolve()}")


if __name__ == "__main__":
    main()





