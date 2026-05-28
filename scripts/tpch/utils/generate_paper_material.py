"""
generate_paper_material.py

Reads results/<qt>/analysis_results.json and sweep_results.json.
Produces:
    results/paper/stats.txt              — all numbers needed for the paper
    results/paper/fig_instability_scatter.png  — hero plot: gap vs time ratio
    results/paper/fig_max_gap.png              — max selectivity gap per query
    results/paper/fig_time_ratio.png           — min/avg/max time ratio per query
    results/paper/fig_stability_score.png      — per-query stability score
    results/paper/fig_penalty_cdf.png          — CDF of wrong-plan penalty

Usage:
    python generate_paper_material.py
    python generate_paper_material.py --results results/
"""

import json, os, argparse, math
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

Q_ORDER = ["qt1","qt2","qt3","qt4","qt5","qt6","qt7","qt8",
           "qt10","qt11","qt12","qt13","qt14","qt16","qt17","qt18","qt21"]

PAL = ["#2563eb","#dc2626","#16a34a","#ea580c","#9333ea","#0891b2",
       "#d97706","#4f46e5","#059669","#e11d48","#7c3aed","#0d9488",
       "#ca8a04","#6366f1","#15803d","#be123c","#7c2d12"]


def load_all(base):
    data = {}
    for qn in Q_ORDER:
        af = os.path.join(base, qn, "analysis_results.json")
        sf = os.path.join(base, qn, "sweep_results.json")
        swf = os.path.join(base, qn, "switches.json")
        if not os.path.exists(af) and not os.path.exists(swf):
            continue
        analysis = json.load(open(af)) if os.path.exists(af) else {}
        sweep = json.load(open(sf)) if os.path.exists(sf) else {}
        total_sw = 0
        if sweep:
            total_sw = sweep.get("num_switches", len(sweep.get("switches", [])))
        elif os.path.exists(swf):
            total_sw = len(json.load(open(swf)))
        results = analysis.get("results", [])
        data[qn] = {"results": results, "total_switches": total_sw, "analysis": analysis}
    return data


def compute_switch_metrics(results):
    """For each analyzed switch, compute time_ratio, abs_gap, penalty."""
    metrics = []
    for r in results:
        af = r.get("after_switch", {})
        bf = r.get("before_switch", {})
        p1_after = af.get("forced_p1_time", 0)
        p2_after = af.get("forced_p2_time", 0)
        p1_before = bf.get("forced_p1_time", 0)
        p2_before = bf.get("forced_p2_time", 0)

        # Time ratio at after-switch point
        if p1_after > 0 and p2_after > 0:
            tr_after = max(p1_after, p2_after) / min(p1_after, p2_after)
        else:
            tr_after = 1.0

        # Time ratio at before-switch point
        if p1_before > 0 and p2_before > 0:
            tr_before = max(p1_before, p2_before) / min(p1_before, p2_before)
        else:
            tr_before = 1.0

        tr = max(tr_after, tr_before)

        abs_gap = abs(r.get("selectivity_gap_pct", 0))
        signed_gap = r.get("selectivity_gap_pct", 0)
        direction = r.get("direction", "?")
        sel = r.get("planner_selectivity_pct", 0)

        # q-error at switch = max(T_P1, T_P2) / min(T_P1, T_P2)
        # This IS the time ratio. q-error of 1.0 = plans identical = perfect switch.
        qerror = tr

        metrics.append({
            "abs_gap": abs_gap,
            "signed_gap": signed_gap,
            "time_ratio": tr,
            "qerror": qerror,
            "tr_after": tr_after,
            "tr_before": tr_before,
            "direction": direction,
            "selectivity": sel,
            "p1_after": p1_after,
            "p2_after": p2_after,
        })
    return metrics


def write_stats(data, outfile):
    """Write comprehensive stats to text file for paper writing."""
    f = open(outfile, "w")
    w = lambda s: f.write(s + "\n")

    w("=" * 70)
    w("  PAPER STATISTICS — Plan Switch Point Stability Analysis")
    w("=" * 70)

    # Global counts
    all_metrics = []
    q_stats = {}

    for qn in Q_ORDER:
        if qn not in data: continue
        d = data[qn]
        res = d["results"]
        m = compute_switch_metrics(res)
        all_metrics.extend([(qn, x) for x in m])

        nt = d["total_switches"]
        na = len(res)
        nd = sum(1 for x in res if x.get("direction") == "DELAYED")
        np_ = sum(1 for x in res if x.get("direction") == "PREMATURE")
        nc = sum(1 for x in res if x.get("direction") == "CORRECT")
        nA = sum(1 for x in res if x.get("direction") == "ANOMALY")

        abs_gaps = [x["abs_gap"] for x in m]
        time_ratios = [x["time_ratio"] for x in m if x["time_ratio"] > 0]
        qerrors = [x["qerror"] for x in m if x["qerror"] > 0]

        # Geometric mean of q-errors: exp(mean(log(qerror_i)))
        if qerrors:
            gmean_qerror = math.exp(sum(math.log(q) for q in qerrors) / len(qerrors))
        else:
            gmean_qerror = 1.0

        q_stats[qn] = {
            "total": nt, "analyzed": na, "skipped": nt - na,
            "delayed": nd, "premature": np_, "correct": nc, "anomaly": nA,
            "incorrect": nd + np_,
            "max_gap": max(abs_gaps) if abs_gaps else 0,
            "avg_gap": sum(abs_gaps) / len(abs_gaps) if abs_gaps else 0,
            "min_tr": min(time_ratios) if time_ratios else 1,
            "avg_tr": sum(time_ratios) / len(time_ratios) if time_ratios else 1,
            "max_tr": max(time_ratios) if time_ratios else 1,
            "gmean_qerror": gmean_qerror,
            "median_qerror": sorted(qerrors)[len(qerrors)//2] if qerrors else 1.0,
            "max_qerror": max(qerrors) if qerrors else 1.0,
            "p90_qerror": sorted(qerrors)[int(len(qerrors)*0.9)] if qerrors else 1.0,
        }

    # Global aggregates
    total_sw = sum(v["total"] for v in q_stats.values())
    total_analyzed = sum(v["analyzed"] for v in q_stats.values())
    total_skipped = sum(v["skipped"] for v in q_stats.values())
    total_delayed = sum(v["delayed"] for v in q_stats.values())
    total_premature = sum(v["premature"] for v in q_stats.values())
    total_correct = sum(v["correct"] for v in q_stats.values())
    total_anomaly = sum(v["anomaly"] for v in q_stats.values())
    total_incorrect = total_delayed + total_premature

    all_gaps = [x["abs_gap"] for _, x in all_metrics]
    all_tr = [x["time_ratio"] for _, x in all_metrics if x["time_ratio"] > 0]
    all_qe = [x["qerror"] for _, x in all_metrics if x["qerror"] > 0]
    nonzero_gaps = [g for g in all_gaps if g > 0.05]

    w("")
    w("GLOBAL SUMMARY")
    w(f"  Queries evaluated: {len(q_stats)}")
    w(f"  Total switch points detected: {total_sw}")
    w(f"  Successfully analyzed: {total_analyzed} ({total_analyzed*100//total_sw}%)")
    w(f"  Skipped (plan forcing failed): {total_skipped} ({total_skipped*100//total_sw}%)")
    w("")
    w(f"  CLASSIFICATION OF {total_analyzed} ANALYZED SWITCHES:")
    w(f"    Delayed (too late):    {total_delayed} ({total_delayed*100//total_analyzed}%)")
    w(f"    Premature (too early): {total_premature} ({total_premature*100//total_analyzed}%)")
    w(f"    Correct:               {total_correct} ({total_correct*100//total_analyzed}%)")
    w(f"    Indeterminate (noise): {total_anomaly} ({total_anomaly*100//total_analyzed}%)")
    w(f"    ---")
    w(f"    INCORRECT TOTAL:       {total_incorrect} ({total_incorrect*100//total_analyzed}%)")
    w(f"    CORRECT+INDET TOTAL:   {total_correct+total_anomaly} ({(total_correct+total_anomaly)*100//total_analyzed}%)")
    w("")
    w("SELECTIVITY GAP STATISTICS")
    w(f"  Mean |gap| (all analyzed): {sum(all_gaps)/len(all_gaps):.2f}%")
    w(f"  Mean |gap| (nonzero only): {sum(nonzero_gaps)/len(nonzero_gaps):.2f}%" if nonzero_gaps else "  Mean |gap| (nonzero): N/A")
    w(f"  Median |gap|: {sorted(all_gaps)[len(all_gaps)//2]:.2f}%")
    w(f"  Max |gap|: {max(all_gaps):.2f}%")
    w(f"  Switches with |gap| > 1%: {sum(1 for g in all_gaps if g > 1)}/{len(all_gaps)}")
    w(f"  Switches with |gap| > 5%: {sum(1 for g in all_gaps if g > 5)}/{len(all_gaps)}")
    w(f"  Switches with |gap| > 10%: {sum(1 for g in all_gaps if g > 10)}/{len(all_gaps)}")
    w(f"  Queries with max |gap| > 10%: {sum(1 for v in q_stats.values() if v['max_gap'] > 10)}/{len(q_stats)}")
    w(f"  Queries with max |gap| > 5%: {sum(1 for v in q_stats.values() if v['max_gap'] > 5)}/{len(q_stats)}")
    w("")
    w("Q-ERROR AT SWITCH POINTS (q-error = max(T_P1,T_P2)/min(T_P1,T_P2))")
    gmean_all = math.exp(sum(math.log(q) for q in all_qe) / len(all_qe)) if all_qe else 1.0
    w(f"  Geometric mean (all): {gmean_all:.2f}x")
    w(f"  Arithmetic mean: {sum(all_qe)/len(all_qe):.2f}x")
    w(f"  Median: {sorted(all_qe)[len(all_qe)//2]:.2f}x")
    w(f"  Max: {max(all_qe):.2f}x")
    w(f"  90th percentile: {sorted(all_qe)[int(len(all_qe)*0.9)]:.2f}x")
    w(f"  Switches with q-error > 2x: {sum(1 for q in all_qe if q > 2)}/{len(all_qe)}")
    w(f"  Switches with q-error > 5x: {sum(1 for q in all_qe if q > 5)}/{len(all_qe)}")
    w(f"  Switches with q-error > 10x: {sum(1 for q in all_qe if q > 10)}/{len(all_qe)}")
    w("")
    w("PER-QUERY Q-ERROR (geometric mean, 1.0 = perfectly stable)")
    for qn in Q_ORDER:
        if qn not in q_stats: continue
        s = q_stats[qn]
        w(f"  {qn.upper():>5s}: gmean={s['gmean_qerror']:.2f}x  median={s['median_qerror']:.2f}x  "
          f"max={s['max_qerror']:.1f}x  p90={s['p90_qerror']:.2f}x  "
          f"(analyzed={s['analyzed']}, gap_max={s['max_gap']:.1f}%)")
    gmeans = [v["gmean_qerror"] for v in q_stats.values()]
    w(f"  ---")
    w(f"  Across queries: min_gmean={min(gmeans):.2f}x  avg_gmean={sum(gmeans)/len(gmeans):.2f}x  max_gmean={max(gmeans):.2f}x")
    w("")

    w("PER-QUERY TABLE (for LaTeX)")
    w(f"{'Query':>6s} {'Total':>6s} {'Anlzd':>6s} {'Skip':>5s} {'D':>4s} {'P':>4s} {'C+I':>4s} "
      f"{'MaxGap':>7s} {'GMeanQE':>8s} {'MaxQE':>7s}")
    for qn in Q_ORDER:
        if qn not in q_stats: continue
        s = q_stats[qn]
        w(f"{qn.upper():>6s} {s['total']:>6d} {s['analyzed']:>6d} {s['skipped']:>5d} "
          f"{s['delayed']:>4d} {s['premature']:>4d} {s['correct']+s['anomaly']:>4d} "
          f"{s['max_gap']:>6.1f}% {s['gmean_qerror']:>7.2f}x {s['max_qerror']:>6.1f}x")

    w("")
    w("=" * 70)
    f.close()
    return q_stats, all_metrics


# ═══════════════════════════════════════════════════════════
#  PLOTS
# ═══════════════════════════════════════════════════════════

plt.rcParams.update({"font.family": "sans-serif", "font.size": 9})

def _ax(ax, title="", xl="", yl=""):
    ax.set_facecolor("#fafbfe")
    ax.set_title(title, fontweight="bold", color="#1e293b", pad=14, fontsize=11, loc="left")
    if xl: ax.set_xlabel(xl, color="#475569", fontsize=10)
    if yl: ax.set_ylabel(yl, color="#475569", fontsize=10)
    ax.tick_params(colors="#475569", labelsize=9)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("bottom", "left"): ax.spines[s].set_color("#e2e8f0")
    ax.grid(axis="both", color="#f1f5f9", lw=0.8)
    ax.set_axisbelow(True)

def _sv(fig, path):
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white", pad_inches=0.2)
    plt.close(fig)
    print(f"    {os.path.basename(path)}")


def plot_instability_scatter(all_metrics, outdir):
    """Hero plot: |Selectivity Gap| vs q-error, colored by query."""
    fig, ax = plt.subplots(figsize=(8, 6))
    _ax(ax, "Plan Switch Instability Map",
        "|Selectivity Gap| (%)", "q-error at Switch Point")

    qnames = list(dict.fromkeys(qn for qn, _ in all_metrics))
    qcolor = {qn: PAL[i % len(PAL)] for i, qn in enumerate(qnames)}

    for qn, m in all_metrics:
        gap = m["abs_gap"]
        qe = m["qerror"]
        if gap < 0.01 and qe < 1.01: continue
        ax.scatter(gap, qe, color=qcolor[qn], s=20, alpha=0.55,
                   edgecolors="white", lw=0.3, zorder=3)

    # Quadrant labels
    ax.axhline(2, color="#94a3b8", lw=0.6, ls=":")
    ax.axvline(5, color="#94a3b8", lw=0.6, ls=":")
    ax.text(40, 50, "HIGH IMPACT\nwide gap + steep cliff", fontsize=7,
            ha="center", color="#ef4444", alpha=0.6, fontweight="bold")
    ax.text(1, 50, "SHARP CLIFF\nnarrow but steep", fontsize=7,
            ha="center", color="#f59e0b", alpha=0.6, fontweight="bold")
    ax.text(40, 1.3, "BENIGN DRIFT\nwide but flat", fontsize=7,
            ha="center", color="#3b82f6", alpha=0.6, fontweight="bold")
    ax.text(1, 1.3, "STABLE", fontsize=7,
            ha="center", color="#22c55e", alpha=0.6, fontweight="bold")

    ax.set_yscale("log")
    ax.set_xlim(-1, 80)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}x" if y >= 2 else f"{y:.1f}x"))

    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=qcolor[q],
               markersize=5, label=q.upper()) for q in qnames]
    ax.legend(handles=handles, loc="upper right", fontsize=6, ncol=3, framealpha=0.9)

    ax.text(0.02, 0.02,
            r"$q\text{-error} = \frac{\max(T_{P1}, T_{P2})}{\min(T_{P1}, T_{P2})}$"
            "\n" + r"Gap $= |sel_{planner} - sel_{true}|$",
            transform=ax.transAxes, fontsize=7, ha="left", va="bottom",
            color="#64748b", style="italic",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#e2e8f0"))
    _sv(fig, os.path.join(outdir, "fig_instability_scatter.png"))


def plot_stability_score(q_stats, outdir):
    """Bar chart of per-query geometric mean q-error."""
    qs = [q for q in Q_ORDER if q in q_stats]
    gmeans = [q_stats[q]["gmean_qerror"] for q in qs]
    n = len(qs)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    _ax(ax, "Plan Stability: Geometric Mean q-error per Query", "", "Geometric Mean q-error")

    bars = ax.bar(range(n), gmeans, color=[PAL[i % len(PAL)] for i in range(n)],
                  edgecolor="white", lw=0.5, width=0.7)
    ax.set_xticks(range(n))
    ax.set_xticklabels([q.upper() for q in qs], rotation=45, ha="right")
    ax.axhline(1.0, color="#22c55e", lw=1, ls="--", alpha=0.6)
    ax.text(n - 0.5, 1.02, "1.0 (perfectly stable)", fontsize=7, color="#22c55e", ha="right")
    ax.axhline(2.0, color="#f59e0b", lw=0.8, ls="--", alpha=0.5)
    ax.text(n - 0.5, 2.05, "2.0x (moderate instability)", fontsize=7, color="#f59e0b", ha="right")

    for b, g in zip(bars, gmeans):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.03,
                f"{g:.2f}x", ha="center", fontsize=7, fontweight="bold", color="#1e293b")

    ax.set_ylim(0, max(gmeans) * 1.15)

    ax.text(0.98, 0.98,
            r"$\mathrm{q\text{-}error}_i = \frac{\max(T_{P1}, T_{P2})}{\min(T_{P1}, T_{P2})}$"
            "\n\n" + r"$\overline{q} = \exp\left(\frac{1}{N}\sum_{i=1}^{N}\ln(q_i)\right)$",
            transform=ax.transAxes, fontsize=8, ha="left", va="top",
            color="#64748b", style="italic",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#e2e8f0"))
    _sv(fig, os.path.join(outdir, "fig_qerror_per_query.png"))


def plot_qerror_cdf(all_metrics, outdir):
    """CDF of q-error across all switches."""
    qerrors = sorted([m["qerror"] for _, m in all_metrics])
    n = len(qerrors)
    y = np.arange(1, n + 1) / n

    fig, ax = plt.subplots(figsize=(8, 5))
    _ax(ax, "Cumulative Distribution of q-error at Switch Points",
        "q-error", "Fraction of Switch Points")

    ax.plot(qerrors, y, color="#2563eb", lw=2)
    ax.fill_between(qerrors, y, alpha=0.1, color="#2563eb")

    # Mark key percentiles
    for pct, label in [(0.5, "50th"), (0.75, "75th"), (0.9, "90th"), (0.95, "95th")]:
        idx = int(pct * n)
        val = qerrors[min(idx, n - 1)]
        ax.axhline(pct, color="#94a3b8", lw=0.5, ls=":")
        ax.plot(val, pct, "o", color="#ef4444", markersize=4, zorder=5)
        ax.text(val * 1.05, pct - 0.03, f"{label}: {val:.2f}x", fontsize=7, color="#475569")

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}x" if x >= 2 else f"{x:.1f}x"))
    ax.axvline(1.0, color="#22c55e", lw=0.8, ls="--", alpha=0.5)

    ax.text(0.98, 0.15,
            r"$q\text{-error} = \frac{\max(T_{P1}, T_{P2})}{\min(T_{P1}, T_{P2})}$"
            "\n1.0x = plans identical at switch",
            transform=ax.transAxes, fontsize=8, ha="right", va="bottom",
            color="#64748b", style="italic",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#e2e8f0"))
    _sv(fig, os.path.join(outdir, "fig_qerror_cdf.png"))


def plot_max_gap(q_stats, outdir):
    """Max selectivity gap per query (horizontal bar)."""
    qs = [q for q in Q_ORDER if q in q_stats]
    n = len(qs)
    mg = [q_stats[q]["max_gap"] for q in qs]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    _ax(ax, "Maximum Selectivity Gap per Query", "Max |Selectivity Gap| (%)", "")

    bars = ax.barh(range(n), mg, color=[PAL[i % len(PAL)] for i in range(n)],
                   edgecolor="white", lw=0.5, height=0.6)
    ax.set_yticks(range(n)); ax.set_yticklabels([q.upper() for q in qs])
    ax.invert_yaxis()
    for b, v in zip(bars, mg):
        if v > 0.05:
            ax.text(b.get_width() + 0.5, b.get_y() + b.get_height() / 2,
                    f"{v:.1f}%", va="center", fontsize=8, fontweight="bold", color="#1e293b")
    ax.axvline(5, color="#f59e0b", lw=1, ls="--", alpha=0.6)
    ax.text(5.5, -0.7, "5% threshold", fontsize=7, color="#f59e0b")

    ax.text(0.98, 0.02, r"Gap $= |sel_{planner} - sel_{true}|$",
            transform=ax.transAxes, fontsize=8, ha="right", va="bottom",
            color="#64748b", style="italic",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#e2e8f0"))
    _sv(fig, os.path.join(outdir, "fig_max_gap.png"))


def plot_time_ratio(q_stats, outdir):
    """Min/avg/max time ratio per query."""
    qs = [q for q in Q_ORDER if q in q_stats]
    n = len(qs)

    fig, ax = plt.subplots(figsize=(10, 5))
    _ax(ax, "Execution Time Ratio at Switch Points",
        "", "Time Ratio (max/min)")

    x = np.arange(n)
    mins = [q_stats[q]["min_tr"] for q in qs]
    avgs = [q_stats[q]["avg_tr"] for q in qs]
    maxs = [q_stats[q]["max_tr"] for q in qs]

    w = 0.25
    ax.bar(x - w, mins, w, label="Min", color="#93c5fd", edgecolor="white", lw=0.5)
    ax.bar(x, avgs, w, label="Avg", color="#3b82f6", edgecolor="white", lw=0.5)
    ax.bar(x + w, maxs, w, label="Max", color="#1e40af", edgecolor="white", lw=0.5)

    ax.set_xticks(x); ax.set_xticklabels([q.upper() for q in qs], rotation=45, ha="right")
    ax.axhline(1, color="#94a3b8", lw=0.8, ls="--")
    ax.legend(fontsize=8, framealpha=0.9)
    if max(maxs) > 20:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}x" if y >= 2 else f"{y:.1f}x"))

    ax.text(0.98, 0.98, r"Ratio $= \frac{\max(T_{P1}, T_{P2})}{\min(T_{P1}, T_{P2})}$",
            transform=ax.transAxes, fontsize=8, ha="right", va="top",
            color="#64748b", style="italic",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#e2e8f0"))
    _sv(fig, os.path.join(outdir, "fig_time_ratio.png"))


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", default="results")
    args = p.parse_args()
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.results)

    outdir = os.path.join(base, "paper")
    os.makedirs(outdir, exist_ok=True)

    print(f"\n  Loading data from {base}/")
    data = load_all(base)
    print(f"  {len(data)} queries loaded\n")

    print("  Writing stats...")
    q_stats, all_metrics = write_stats(data, os.path.join(outdir, "stats.txt"))
    print(f"    stats.txt")

    print("  Generating plots...")
    plot_instability_scatter(all_metrics, outdir)
    plot_stability_score(q_stats, outdir)
    plot_qerror_cdf(all_metrics, outdir)
    plot_max_gap(q_stats, outdir)
    plot_time_ratio(q_stats, outdir)

    print(f"\n  All outputs in {outdir}/\n")


if __name__ == "__main__":
    main()