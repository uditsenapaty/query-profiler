"""
analyze.py — Phase 2: True Switch Point Analysis (Bidirectional).

For each planner switch point found by sweep.py:

  1. Generate hints (pg_hint_plan + GUC fallback), verify via comparator
  2. CROSS-FORCE at the boundary:
     - Force P2 where planner chose P1 (before switch)
     - Force P1 where planner chose P2 (after switch)
  3. Determine direction:
     - P2 faster before switch → DELAYED  → binary search backward
     - P1 faster after switch  → PREMATURE → binary search forward
     - Neither                 → CORRECT
     - Both                    → ANOMALY
  4. Binary search in the determined direction for true crossover
  5. Measure everything at true switch point

Exports per query (results/<qt>/):
    analysis_results.json  — complete data with before/after cross-forcing
    analysis_report.txt    — human-readable detailed report

Usage:
    python analyze.py qt1
    python analyze.py --all
    python analyze.py --all --runs 5
"""

import psycopg2
import json
import os
import sys
import argparse
from datetime import datetime

from comparator import structural_hash, short_label, plan_tree_str
from query_registry import QUERIES, QUERY_ORDER

# ═══════════════════════════════════════════════════════════════
DB_CONFIG = {
    "host": "localhost", "port": 5432,
    "database": "tpchdb_sf10",
    "user": "postgres", "password": "postgres",
}
DEFAULT_RUNS = 3
SKIP_QUERIES = {"qt9", "qt20"}
# ═══════════════════════════════════════════════════════════════


# ─── HINT GENERATION ──────────────────────────────────────────

def _alias(node):
    return node.get("Alias", node.get("Relation Name", ""))

def _is_scan(nt):
    return nt in ("Seq Scan","Index Scan","Index Only Scan","Bitmap Heap Scan","Tid Scan")

def _bitmap_idx(node):
    for c in node.get("Plans", []):
        if c.get("Node Type") == "Bitmap Index Scan": return c.get("Index Name","")
        if c.get("Node Type") in ("BitmapAnd","BitmapOr"):
            for gc in c.get("Plans", []): 
                if gc.get("Node Type") == "Bitmap Index Scan": return gc.get("Index Name","")
    return ""

def _gather_workers(node):
    if node.get("Node Type") in ("Gather","Gather Merge"): return node.get("Workers Planned",2)
    for c in node.get("Plans",[]): 
        w = _gather_workers(c)
        if w > 0: return w
    return 0

def _all_aliases(node):
    nt = node.get("Node Type","")
    wrappers = {"Hash","Materialize","Memoize","Sort","Incremental Sort","Aggregate","Group",
                "Unique","Gather","Gather Merge","BitmapAnd","BitmapOr","Bitmap Index Scan",
                "Limit","Result","Subquery Scan","SetOp","LockRows","WindowAgg","Append","MergeAppend"}
    if nt in wrappers:
        a = []
        for c in node.get("Plans",[]): a.extend(_all_aliases(c))
        return a
    if _is_scan(nt):
        al = _alias(node)
        return [al] if al else []
    if nt in ("Nested Loop","Hash Join","Merge Join"):
        a = []
        for c in node.get("Plans",[]): a.extend(_all_aliases(c))
        return a
    al = _alias(node)
    if al: return [al]
    a = []
    for c in node.get("Plans",[]): a.extend(_all_aliases(c))
    return a

def _lead(node):
    nt = node.get("Node Type","")
    if _is_scan(nt): return _alias(node) or ""
    if nt == "Bitmap Index Scan": return ""
    if nt in ("Nested Loop","Hash Join","Merge Join"):
        ch = node.get("Plans",[])
        if len(ch) >= 2:
            l, r = _lead(ch[0]), _lead(ch[1])
            if l and r: return f"({l} {r})"
            return l or r
        return _lead(ch[0]) if ch else ""
    skip = {"Aggregate","Sort","Incremental Sort","Gather","Gather Merge","Hash","Materialize",
            "Memoize","Limit","Unique","SetOp","LockRows","Result","Subquery Scan","Group",
            "WindowAgg","Append","MergeAppend","BitmapAnd","BitmapOr"}
    if nt in skip:
        for c in node.get("Plans",[]):
            r = _lead(c)
            if r: return r
        return ""
    ch = node.get("Plans",[])
    if len(ch) == 1: return _lead(ch[0])
    if len(ch) >= 2:
        l, r = _lead(ch[0]), _lead(ch[1])
        if l and r: return f"({l} {r})"
        return l or r
    return _alias(node) or ""


def generate_hints(plan):
    root = plan["Plan"]
    gw = _gather_workers(root)
    scans, joins, pars = [], [], {}

    def collect(n):
        nt, al = n.get("Node Type",""), _alias(n)
        if nt == "Seq Scan" and al: scans.append(f"SeqScan({al})")
        elif nt == "Index Scan" and al:
            idx = n.get("Index Name","")
            scans.append(f"IndexScan({al} {idx})" if idx else f"IndexScan({al})")
        elif nt == "Index Only Scan" and al:
            idx = n.get("Index Name","")
            scans.append(f"IndexOnlyScan({al} {idx})" if idx else f"IndexOnlyScan({al})")
        elif nt == "Bitmap Heap Scan" and al:
            idx = _bitmap_idx(n)
            scans.append(f"BitmapScan({al} {idx})" if idx else f"BitmapScan({al})")
        if al and n.get("Parallel Aware") and al not in pars: pars[al] = gw
        if nt in ("Nested Loop","Hash Join","Merge Join"):
            ch = n.get("Plans",[])
            if len(ch) >= 2:
                aliases = []
                for c in ch: aliases.extend(_all_aliases(c))
                if len(aliases) >= 2:
                    m = {"Nested Loop":"NestLoop","Hash Join":"HashJoin","Merge Join":"MergeJoin"}[nt]
                    joins.append(f"{m}({' '.join(aliases)})")
        for c in n.get("Plans",[]):
            if c.get("Node Type") != "Bitmap Index Scan": collect(c)
    collect(root)

    leading = _lead(root)
    lines = []
    for h in dict.fromkeys(scans): lines.append(f"    {h}")
    for h in dict.fromkeys(joins): lines.append(f"    {h}")
    if leading: lines.append(f"    Leading({leading})")
    for al in sorted(pars): lines.append(f"    Parallel({al} {pars[al]} hard)")
    return "/*+\n" + "\n".join(lines) + "\n*/" if lines else ""


def generate_guc_hints(plan):
    root = plan["Plan"]
    stypes, jtypes, par, gw = set(), set(), False, 0
    smap = {"Seq Scan":"enable_seqscan","Index Scan":"enable_indexscan",
            "Index Only Scan":"enable_indexonlyscan",
            "Bitmap Heap Scan":"enable_bitmapscan","Bitmap Index Scan":"enable_bitmapscan"}
    jmap = {"Nested Loop":"enable_nestloop","Hash Join":"enable_hashjoin","Merge Join":"enable_mergejoin"}
    def walk(n):
        nonlocal par, gw
        nt = n.get("Node Type","")
        if nt in smap: stypes.add(smap[nt])
        if nt in jmap: jtypes.add(jmap[nt])
        if nt in ("Gather","Gather Merge"): par = True; gw = max(gw, n.get("Workers Planned",2))
        for c in n.get("Plans",[]): walk(c)
    walk(root)
    all_s = {"enable_seqscan","enable_indexscan","enable_indexonlyscan","enable_bitmapscan","enable_tidscan"}
    all_j = {"enable_nestloop","enable_hashjoin","enable_mergejoin"}
    lines = []
    for g in sorted(all_s): lines.append(f"    Set({g} {'on' if g in stypes else 'off'})")
    for g in sorted(all_j): lines.append(f"    Set({g} {'on' if g in jtypes else 'off'})")
    lines.append(f"    Set(max_parallel_workers_per_gather {gw if par else 0})")
    return "/*+\n" + "\n".join(lines) + "\n*/"


# ─── EXECUTION ────────────────────────────────────────────────

def verify_hint(cursor, sql, params, hint, target_hash):
    cursor.execute(f"EXPLAIN (FORMAT JSON) {hint}\n{sql}", params)
    plan = cursor.fetchone()[0][0]
    h = structural_hash(plan)
    return h == target_hash, h, plan


def get_cost(cursor, sql, params, hint=""):
    """EXPLAIN with hint → total cost."""
    q = f"EXPLAIN (FORMAT JSON) {hint}\n{sql}" if hint else f"EXPLAIN (FORMAT JSON) {sql}"
    cursor.execute(q, params)
    plan = cursor.fetchone()[0][0]
    return plan["Plan"].get("Total Cost", 0)


def get_time(cursor, sql, params, hint, runs):
    """EXPLAIN ANALYZE with hint → median execution time (ms)."""
    times = []
    for _ in range(runs):
        cursor.execute(f"EXPLAIN ANALYZE {hint}\n{sql}", params)
        for row in cursor.fetchall():
            if "Execution Time" in row[0]:
                times.append(float(row[0].split(":")[1].replace("ms","").strip()))
                break
    if not times: return 0.0
    times.sort()
    return times[len(times)//2]


def make_params(frac, ranges, n_pl):
    vals = []
    for r in ranges:
        vals.append(r["min"] + frac * (r["max"] - r["min"]))
    while len(vals) < n_pl:
        vals.append(vals[len(vals) % len(ranges)])
    return tuple(vals)


# ─── ANALYSIS ─────────────────────────────────────────────────

def analyze_query(cursor, qname, qinfo, runs, base_dir):
    result_dir = os.path.join(base_dir, qname)
    sw_file = os.path.join(result_dir, "switches.json")
    if not os.path.exists(sw_file):
        print(f"  No switches.json — run sweep.py first"); return []

    switches = json.load(open(sw_file))
    sql_template = open(os.path.join(os.path.dirname(__file__), qinfo["sql_file"])).read()
    sql = sql_template.replace(":p1", "%s").replace(":p2", "%s")
    n_pl = sql.count("%s")

    ranges = []
    for p in qinfo["params"]:
        cursor.execute(f"SELECT MIN({p['column']}), MAX({p['column']}) FROM {p['table']}")
        lo, hi = cursor.fetchone()
        ranges.append({"min": float(lo), "max": float(hi), "label": p["label"],
                       "table": p["table"], "column": p["column"]})

    print(f"\n{'═'*60}")
    print(f"  {qinfo.get('label', qname)} — Analysis")
    print(f"  {len(switches)} switches, {runs} timing runs")
    print(f"{'═'*60}")

    results = []
    prev_sw_frac = 0.0

    for sw_idx, sw in enumerate(switches):
        snum = sw["switch_num"]
        frac = sw["frac"]
        cost_ratio = sw["to_cost"] / sw["from_cost"] if sw["from_cost"] > 0 else 999

        # Compute next switch frac (for forward search boundary)
        next_sw_frac = 1.0
        for future_sw in switches[sw_idx + 1:]:
            next_sw_frac = future_sw["frac"]
            break

        print(f"\n  ── Switch #{snum} at sel={frac*100:.1f}% ──")

        # Generate hints
        hint_a = generate_hints(sw["from_plan"])
        hint_b = generate_hints(sw["to_plan"])
        guc_a = generate_guc_hints(sw["from_plan"])
        guc_b = generate_guc_hints(sw["to_plan"])

        # Verify at boundary
        p_before = make_params(max(frac - 0.005, 0), ranges, n_pl)
        p_at = make_params(frac, ranges, n_pl)

        ok_a, _, _ = verify_hint(cursor, sql, p_before, hint_a, sw["from_hash"])
        if not ok_a:
            ok_a, _, _ = verify_hint(cursor, sql, p_before, guc_a, sw["from_hash"])
            if ok_a: hint_a = guc_a

        ok_b, _, _ = verify_hint(cursor, sql, p_at, hint_b, sw["to_hash"])
        if not ok_b:
            ok_b, _, _ = verify_hint(cursor, sql, p_at, guc_b, sw["to_hash"])
            if ok_b: hint_b = guc_b

        use_a, use_b = hint_a, hint_b
        verify_a, verify_b = ok_a, ok_b

        if not ok_a and not ok_b:
            print(f"    SKIP: both hints failed verification")
            prev_sw_frac = frac; continue

        if not ok_a: use_a = guc_a
        if not ok_b: use_b = guc_b

        print(f"    Plan A hint: {'✓' if ok_a else '✗ (GUC)'}")
        print(f"    Plan B hint: {'✓' if ok_b else '✗ (GUC)'}")

        # ═══════════════════════════════════════════════════════
        #  STEP 1: Cross-force at the boundary
        #
        #  Before switch (frac - delta): planner chose P1
        #  After switch  (frac):         planner chose P2
        #
        #  We force the OPPOSITE plan at each side:
        #    - Force P2 on "before" point (where planner chose P1)
        #    - Force P1 on "after" point  (where planner chose P2)
        # ═══════════════════════════════════════════════════════

        delta = 0.005  # small step back from switch
        frac_before = max(frac - delta, 0.001)
        frac_after = frac
        p_before = make_params(frac_before, ranges, n_pl)
        p_after = make_params(frac_after, ranges, n_pl)

        # Normal (unhinted) times at both points
        before_normal_time = get_time(cursor, sql, p_before, "", runs)
        after_normal_time = get_time(cursor, sql, p_after, "", runs)
        before_normal_cost = get_cost(cursor, sql, p_before)
        after_normal_cost = get_cost(cursor, sql, p_after)

        # Force P1 and P2 at the BEFORE point (planner chose P1 here)
        before_p1_time = get_time(cursor, sql, p_before, use_a, runs)
        before_p2_time = get_time(cursor, sql, p_before, use_b, runs)
        before_p1_cost = get_cost(cursor, sql, p_before, use_a)
        before_p2_cost = get_cost(cursor, sql, p_before, use_b)

        # Force P1 and P2 at the AFTER point (planner chose P2 here)
        after_p1_time = get_time(cursor, sql, p_after, use_a, runs)
        after_p2_time = get_time(cursor, sql, p_after, use_b, runs)
        after_p1_cost = get_cost(cursor, sql, p_after, use_a)
        after_p2_cost = get_cost(cursor, sql, p_after, use_b)

        print(f"\n    CROSS-FORCE RESULTS:")
        print(f"      Before (sel={frac_before*100:.2f}%, planner=P1):")
        print(f"        normal={before_normal_time:.1f}ms  P1={before_p1_time:.1f}ms  P2={before_p2_time:.1f}ms")
        print(f"      After  (sel={frac_after*100:.2f}%, planner=P2):")
        print(f"        normal={after_normal_time:.1f}ms  P1={after_p1_time:.1f}ms  P2={after_p2_time:.1f}ms")

        # ═══════════════════════════════════════════════════════
        #  STEP 2: Determine search direction
        #
        #  p2_better_before = P2 beats P1 at the before point
        #    → planner should have switched earlier → DELAYED → search backward
        #
        #  p1_better_after = P1 beats P2 at the after point
        #    → planner should have switched later → PREMATURE → search forward
        #
        #  Neither → CORRECT (switch is at the right place)
        #  Both    → ANOMALY (interesting edge case)
        # ═══════════════════════════════════════════════════════

        p2_better_before = before_p2_time < before_p1_time
        p1_better_after = after_p1_time < after_p2_time

        if p2_better_before and p1_better_after:
            direction = "ANOMALY"
            print(f"    → ANOMALY: P2 better before AND P1 better after switch!")
        elif p2_better_before:
            direction = "DELAYED"
            print(f"    → DELAYED: P2 was already faster before switch → search backward")
        elif p1_better_after:
            direction = "PREMATURE"
            print(f"    → PREMATURE: P1 still faster after switch → search forward")
        else:
            direction = "CORRECT"
            print(f"    → CORRECT: switch is at the right place")

        # ═══════════════════════════════════════════════════════
        #  STEP 3: Binary search for true switch point
        # ═══════════════════════════════════════════════════════

        search_log = []
        iters = 0
        true_frac = frac  # default: planner switch is correct

        if direction == "DELAYED":
            # Search backward: [prev_sw_frac ... frac]
            lo_frac = prev_sw_frac
            hi_frac = frac
            print(f"\n    Binary search BACKWARD [{lo_frac*100:.1f}% — {hi_frac*100:.1f}%]")

            while hi_frac - lo_frac > 0.002:
                mid = (lo_frac + hi_frac) / 2.0
                iters += 1
                p_mid = make_params(mid, ranges, n_pl)
                ta = get_time(cursor, sql, p_mid, use_a, runs)
                tb = get_time(cursor, sql, p_mid, use_b, runs)

                if tb < ta:
                    hi_frac = mid; arrow = "B faster → go left"
                else:
                    lo_frac = mid; arrow = "A faster → go right"

                search_log.append({
                    "iteration": iters, "frac": mid, "selectivity_pct": mid * 100,
                    "param_values": list(p_mid),
                    "time_a": ta, "time_b": tb, "diff": ta - tb,
                    "gap_pct": (hi_frac - lo_frac) * 100, "direction": arrow,
                })
                print(f"    [{iters:>2d}] sel={mid*100:5.1f}%  A={ta:.1f}ms B={tb:.1f}ms "
                      f"diff={ta-tb:+.1f}ms  gap={100*(hi_frac-lo_frac):.2f}%  {arrow}")

            true_frac = hi_frac

        elif direction == "PREMATURE":
            # Search forward: [frac ... next_sw_frac or 1.0]
            lo_frac = frac
            hi_frac = next_sw_frac
            print(f"\n    Binary search FORWARD [{lo_frac*100:.1f}% — {hi_frac*100:.1f}%]")

            while hi_frac - lo_frac > 0.002:
                mid = (lo_frac + hi_frac) / 2.0
                iters += 1
                p_mid = make_params(mid, ranges, n_pl)
                ta = get_time(cursor, sql, p_mid, use_a, runs)
                tb = get_time(cursor, sql, p_mid, use_b, runs)

                if tb < ta:
                    # P2 is faster here, true switch is before this
                    hi_frac = mid; arrow = "B faster → go left"
                else:
                    # P1 still faster, true switch is after this
                    lo_frac = mid; arrow = "A faster → go right"

                search_log.append({
                    "iteration": iters, "frac": mid, "selectivity_pct": mid * 100,
                    "param_values": list(p_mid),
                    "time_a": ta, "time_b": tb, "diff": ta - tb,
                    "gap_pct": (hi_frac - lo_frac) * 100, "direction": arrow,
                })
                print(f"    [{iters:>2d}] sel={mid*100:5.1f}%  A={ta:.1f}ms B={tb:.1f}ms "
                      f"diff={ta-tb:+.1f}ms  gap={100*(hi_frac-lo_frac):.2f}%  {arrow}")

            true_frac = hi_frac

        # For CORRECT and ANOMALY: true_frac stays at planner frac

        # ═══════════════════════════════════════════════════════
        #  STEP 4: Measure at true switch point
        # ═══════════════════════════════════════════════════════

        true_params = list(make_params(true_frac, ranges, n_pl))
        p_true = tuple(true_params)
        true_p1_time = get_time(cursor, sql, p_true, use_a, runs)
        true_p2_time = get_time(cursor, sql, p_true, use_b, runs)
        true_p1_cost = get_cost(cursor, sql, p_true, use_a)
        true_p2_cost = get_cost(cursor, sql, p_true, use_b)
        true_normal_time = get_time(cursor, sql, p_true, "", runs)
        true_normal_cost = get_cost(cursor, sql, p_true)

        # Calculate gap (signed: positive = delayed, negative = premature)
        if direction == "DELAYED":
            gap_pct = (frac - true_frac) * 100  # positive
        elif direction == "PREMATURE":
            gap_pct = (frac - true_frac) * 100  # negative (true is ahead of planner)
        else:
            gap_pct = 0.0

        print(f"\n    TRUE SWITCH: sel={true_frac*100:.2f}%  direction={direction}  gap={gap_pct:+.2f}%")
        print(f"      P1={true_p1_time:.1f}ms  P2={true_p2_time:.1f}ms  normal={true_normal_time:.1f}ms")

        results.append({
            "switch_num": snum,
            "direction": direction,  # DELAYED / PREMATURE / CORRECT / ANOMALY

            # Planner switch boundary measurements
            "planner_frac": frac,
            "planner_selectivity_pct": frac * 100,
            "planner_param_values": list(p_after),

            "before_switch": {
                "frac": frac_before,
                "selectivity_pct": frac_before * 100,
                "param_values": list(p_before),
                "normal_time": before_normal_time,
                "normal_cost": before_normal_cost,
                "forced_p1_time": before_p1_time,
                "forced_p1_cost": before_p1_cost,
                "forced_p2_time": before_p2_time,
                "forced_p2_cost": before_p2_cost,
                "p2_faster": p2_better_before,
            },
            "after_switch": {
                "frac": frac_after,
                "selectivity_pct": frac_after * 100,
                "param_values": list(p_after),
                "normal_time": after_normal_time,
                "normal_cost": after_normal_cost,
                "forced_p1_time": after_p1_time,
                "forced_p1_cost": after_p1_cost,
                "forced_p2_time": after_p2_time,
                "forced_p2_cost": after_p2_cost,
                "p1_faster": p1_better_after,
            },

            # True switch point
            "true_frac": true_frac,
            "true_selectivity_pct": true_frac * 100,
            "true_param_values": true_params,
            "true_normal_time": true_normal_time,
            "true_normal_cost": true_normal_cost,
            "true_forced_p1_time": true_p1_time,
            "true_forced_p1_cost": true_p1_cost,
            "true_forced_p2_time": true_p2_time,
            "true_forced_p2_cost": true_p2_cost,

            # Gap (signed)
            "selectivity_gap_pct": gap_pct,
            "abs_gap_pct": abs(gap_pct),

            # Plan info
            "planner_cost_before": sw["from_cost"],
            "planner_cost_after": sw["to_cost"],
            "plan_a_label": sw["from_label"],
            "plan_b_label": sw["to_label"],
            "plan_a_hash": sw["from_hash"],
            "plan_b_hash": sw["to_hash"],

            # Verification
            "hint_a_verified": verify_a,
            "hint_b_verified": verify_b,
            "hint_a_used": use_a,
            "hint_b_used": use_b,

            # Binary search
            "search_direction": direction,
            "search_iters": iters,
            "search_log": search_log,
        })

        prev_sw_frac = frac

    # Save
    if results:
        _save_results(result_dir, qname, qinfo, results, ranges, runs)

    return results


def _save_results(outdir, qname, qinfo, results, ranges, runs):
    # JSON (complete)
    n_delayed = sum(1 for r in results if r["direction"] == "DELAYED")
    n_premature = sum(1 for r in results if r["direction"] == "PREMATURE")
    n_correct = sum(1 for r in results if r["direction"] == "CORRECT")
    n_anomaly = sum(1 for r in results if r["direction"] == "ANOMALY")

    export = {
        "query": qname,
        "label": qinfo.get("label", qname),
        "timing_runs": runs,
        "timestamp": datetime.now().isoformat(),
        "ranges": ranges,
        "num_analyzed": len(results),
        "num_delayed": n_delayed,
        "num_premature": n_premature,
        "num_correct": n_correct,
        "num_anomaly": n_anomaly,
        "results": results,
    }
    with open(os.path.join(outdir, "analysis_results.json"), "w") as f:
        json.dump(export, f, indent=2, default=str)

    # Text report
    W = 85
    lines = ["=" * W]
    lines.append(f"  {qinfo.get('label', qname)} — True Switch Point Analysis".center(W))
    lines.append("=" * W)
    lines.append(f"  Timing runs: {runs} (median)")
    lines.append(f"  Analyzed: {len(results)} switches")
    lines.append(f"  Delayed: {n_delayed}  |  Premature: {n_premature}  |  Correct: {n_correct}  |  Anomaly: {n_anomaly}")
    lines.append("")

    for r in results:
        gap = r["selectivity_gap_pct"]
        dr = r["direction"]
        lines.append("─" * W)
        lines.append(f"  Switch #{r['switch_num']}  —  {dr}")
        lines.append("─" * W)
        lines.append(f"  Plan A (P1): {r['plan_a_label'][:65]}")
        lines.append(f"  Plan B (P2): {r['plan_b_label'][:65]}")
        lines.append(f"  Hints: A={'✓' if r['hint_a_verified'] else '✗ GUC'}  "
                     f"B={'✓' if r['hint_b_verified'] else '✗ GUC'}")
        lines.append("")

        bs = r["before_switch"]
        lines.append(f"  BEFORE SWITCH (sel={bs['selectivity_pct']:.2f}%, planner=P1):")
        lines.append(f"    Normal time  : {bs['normal_time']:.2f} ms    Normal cost  : {bs['normal_cost']:,.2f}")
        lines.append(f"    Forced P1    : {bs['forced_p1_time']:.2f} ms    Cost P1      : {bs['forced_p1_cost']:,.2f}")
        lines.append(f"    Forced P2    : {bs['forced_p2_time']:.2f} ms    Cost P2      : {bs['forced_p2_cost']:,.2f}")
        lines.append(f"    P2 faster?   : {'YES' if bs['p2_faster'] else 'no'}")
        lines.append("")

        af = r["after_switch"]
        lines.append(f"  AFTER SWITCH (sel={af['selectivity_pct']:.2f}%, planner=P2):")
        lines.append(f"    Normal time  : {af['normal_time']:.2f} ms    Normal cost  : {af['normal_cost']:,.2f}")
        lines.append(f"    Forced P1    : {af['forced_p1_time']:.2f} ms    Cost P1      : {af['forced_p1_cost']:,.2f}")
        lines.append(f"    Forced P2    : {af['forced_p2_time']:.2f} ms    Cost P2      : {af['forced_p2_cost']:,.2f}")
        lines.append(f"    P1 faster?   : {'YES' if af['p1_faster'] else 'no'}")
        lines.append("")

        lines.append(f"  TRUE SWITCH POINT (sel={r['true_selectivity_pct']:.2f}%):")
        lines.append(f"    Normal time  : {r['true_normal_time']:.2f} ms    Normal cost : {r['true_normal_cost']:,.2f}")
        lines.append(f"    Forced P1    : {r['true_forced_p1_time']:.2f} ms    Cost P1     : {r['true_forced_p1_cost']:,.2f}")
        lines.append(f"    Forced P2    : {r['true_forced_p2_time']:.2f} ms    Cost P2     : {r['true_forced_p2_cost']:,.2f}")
        lines.append("")

        lines.append(f"  VERDICT: {dr}")
        lines.append(f"    Selectivity gap: {gap:+.2f}%")
        if dr == "DELAYED":
            lines.append(f"    Planner switched {abs(gap):.2f}% TOO LATE")
        elif dr == "PREMATURE":
            lines.append(f"    Planner switched {abs(gap):.2f}% TOO EARLY")
        elif dr == "ANOMALY":
            lines.append(f"    Both plans outperform each other on opposite sides!")
        else:
            lines.append(f"    Switch is at the right place")
        lines.append("")

        if r["search_log"]:
            lines.append(f"  BINARY SEARCH ({r['search_direction']}):")
            lines.append(f"  {'#':>3s} {'Sel%':>7s} {'P1(ms)':>10s} {'P2(ms)':>10s} "
                        f"{'Diff':>10s} {'Gap%':>7s}")
            for e in r["search_log"]:
                lines.append(f"  {e['iteration']:>3d} {e['selectivity_pct']:>7.2f} "
                            f"{e['time_a']:>10.2f} {e['time_b']:>10.2f} "
                            f"{e['diff']:>+10.2f} {e['gap_pct']:>7.3f}")
            lines.append("")

    lines.append("=" * W)
    with open(os.path.join(outdir, "analysis_report.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  → {outdir}/")


# ─── MAIN ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="True Switch Point Analysis")
    parser.add_argument("queries", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--results", default="results")
    args = parser.parse_args()

    if args.all:
        names = [q for q in QUERY_ORDER if q not in SKIP_QUERIES]
    elif args.queries:
        names = args.queries
    else:
        parser.print_help(); return

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.results)
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    print(f"\n{'━'*60}")
    print(f"  True Switch Point Analysis — {len(names)} queries")
    print(f"{'━'*60}")

    all_res = {}
    for qn in names:
        if qn not in QUERIES: continue
        try:
            all_res[qn] = analyze_query(cur, qn, QUERIES[qn], args.runs, base)
        except Exception as e:
            print(f"  ERROR on {qn}: {e}")
            import traceback; traceback.print_exc()

    cur.close(); conn.close()

    print(f"\n{'━'*60}")
    print(f"  {'Query':<8s} {'Analyzed':>8s} {'Delayed':>8s} {'Premature':>9s} {'Correct':>8s} {'Anomaly':>8s}")
    for qn in names:
        res = all_res.get(qn, [])
        nd = sum(1 for r in res if r["direction"] == "DELAYED")
        np_ = sum(1 for r in res if r["direction"] == "PREMATURE")
        nc = sum(1 for r in res if r["direction"] == "CORRECT")
        na = sum(1 for r in res if r["direction"] == "ANOMALY")
        print(f"  {qn:<8s} {len(res):>8d} {nd:>8d} {np_:>9d} {nc:>8d} {na:>8d}")
    print(f"{'━'*60}\n")


if __name__ == "__main__":
    main()