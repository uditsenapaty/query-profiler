"""
comparator.py — PostgreSQL plan comparison via the Decision–Witness model.

Determines whether two execution plans (EXPLAIN FORMAT JSON) are the same
plan by splitting every plan component into two buckets:

  WITNESSES (Bucket 1) — planner decisions and data-source identities.
      Any difference here GUARANTEES the plans are different.
        - decision fields   (Node Type, Strategy, Join Type, Index Name, ...)
        - identity fields   (Relation Name, Function Name, Command, ...)
        - condition STRUCTURE (the normalized text of Filter / *Cond keys)

  ATTRIBUTION (Bucket 2) — labels, literals. Differences here can NEVER
      prove a plan change on their own; they are reported as causes and
      context alongside witnesses.
        - labels    (Schema, Alias, CTE Name, Subplan Name)
        - literals  (constants and $n parameters inside conditions)

Two fingerprints are computed per plan:

  shape_hash — SHA-256 over witnesses only. Equality means "same plan" in
      the sense of PostgreSQL 18's plan_id / pg_stat_plans ("plan shape",
      approximately EXPLAIN (COSTS OFF)) and pg_store_plans ("the same
      except for literal constants and fluctuating values").
  param_hash — SHA-256 over the literal values, in tree order.

compare() yields exactly one of three verdicts:

  STRUCTURAL — shape hashes differ      -> guaranteed plan change
  PARAMETRIC — same shape, new literals -> same plan, different parameters
  IDENTICAL  — both hashes equal

Deliberately-exposed contested knobs (real implementations disagree):

  include_workers_planned — PostgreSQL stores the planned parallel degree
      in the plan tree; Oracle's PLAN_HASH_VALUE ignores degree entirely.
      Default True (PostgreSQL semantics).
  collapse_partitions — treat partition members under Append/Merge Append
      as interchangeable. pg_stat_plans lists per-partition plan-id churn
      as a known issue; object-identity purists disagree. Default False.

Costs, row estimates, and runtime telemetry are never part of identity.
"""

import json
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ComparatorConfig", "DEFAULT_CONFIG",
    "Fingerprint", "FieldDiff", "PlanComparison",
    "fingerprint", "shape_hash", "param_hash", "compare",
    "clean_node", "collect_literals", "normalize_expression",
    "structural_hash",
    "count_nodes", "max_depth", "short_label",
    "build_tree_lines", "plan_tree_str",
]

# ───────────────────────────── field classification ─────────────────────────

# Bucket 1 / decisions — planner degrees of freedom (≈ the pg_hint_plan set).
DECISION_KEYS: Tuple[str, ...] = (
    "Node Type", "Strategy", "Partial Mode", "Join Type",
    "Parent Relationship", "Index Name", "Scan Direction",
    "Parallel Aware", "Inner Unique", "Async Capable",
    "Single Copy", "Custom Plan Provider",
)

# Decision fields whose values are expressions and may embed literals.
EXPRESSION_KEYS: Tuple[str, ...] = (
    "Sort Key", "Presorted Key", "Group Key", "Cache Key",
)

# Decision-bearing but excluded by some identity schemes (Oracle PHV).
CONTESTED_KEYS: Tuple[str, ...] = ("Workers Planned",)

# Bucket 1 / identity — a different data source or statement type.
IDENTITY_KEYS: Tuple[str, ...] = (
    "Relation Name", "Function Name", "Table Function Name",
    "Command", "Operation",
)

# Conditions: structure (normalized) is Bucket 1; literals are Bucket 2.
CONDITION_KEYS: Tuple[str, ...] = (
    "Filter", "Index Cond", "Hash Cond", "Merge Cond",
    "Recheck Cond", "Join Filter", "One-Time Filter", "TID Cond",
)

# Bucket 2 / labels — invisible to the cost model; never hashed,
# always reported (renames, search_path flips, subplan renumbering).
LABEL_KEYS: Tuple[str, ...] = ("Schema", "Alias", "CTE Name", "Subplan Name")

_PARTITION_PARENTS = ("Append", "Merge Append")

# Single pass matches quoted strings (with '' escapes), $n parameters,
# and numbers (including decimals and exponents). All become "?", so a
# generic plan ($1) and a custom plan ('42') normalize identically.
_LITERAL_RE = re.compile(
    r"'(?:[^']|'')*'"
    r"|\$\d+\b"
    r"|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"
)


# ───────────────────────────── configuration ────────────────────────────────

@dataclass(frozen=True)
class ComparatorConfig:
    """Comparison policy. Defaults follow PostgreSQL plan_id semantics."""
    include_workers_planned: bool = True
    collapse_partitions: bool = False

    def shape_keys(self) -> Tuple[str, ...]:
        keys = DECISION_KEYS + EXPRESSION_KEYS + IDENTITY_KEYS
        if self.include_workers_planned:
            keys += CONTESTED_KEYS
        return keys


DEFAULT_CONFIG = ComparatorConfig()


# ───────────────────────────── normalization ────────────────────────────────

def normalize_expression(text: str) -> str:
    """Replace every literal/parameter in an expression with '?'."""
    return _LITERAL_RE.sub("?", text)


def _normalize(value: Any) -> Any:
    """Normalize a condition/expression value of any JSON shape."""
    if isinstance(value, str):
        return normalize_expression(value)
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return normalize_expression(json.dumps(value, sort_keys=True))


def _extract_literals(value: Any, acc: List[str]) -> None:
    if isinstance(value, str):
        acc.extend(m.group(0) for m in _LITERAL_RE.finditer(value))
    elif isinstance(value, (list, tuple)):
        for v in value:
            _extract_literals(v, acc)


# ───────────────────────────── plan access ──────────────────────────────────

def _root(plan: Any) -> Dict[str, Any]:
    """Accept EXPLAIN JSON in any of its common shapes; fail descriptively."""
    if isinstance(plan, list):
        if plan and isinstance(plan[0], dict) and "Plan" in plan[0]:
            return plan[0]["Plan"]
    elif isinstance(plan, dict):
        if isinstance(plan.get("Plan"), dict):
            return plan["Plan"]
        if "Node Type" in plan:
            return plan
    raise ValueError(
        "Expected EXPLAIN (FORMAT JSON) output: a plan node, a {'Plan': ...} "
        "dict, or the top-level [{'Plan': ...}] list."
    )


def _shape_value(node: Dict[str, Any], key: str,
                 parent_node_type: Optional[str],
                 cfg: ComparatorConfig) -> Any:
    """The value of a shape key as it participates in plan identity."""
    value = node.get(key)
    if value is None:
        return None
    if (key == "Relation Name"
            and cfg.collapse_partitions
            and parent_node_type in _PARTITION_PARENTS
            and node.get("Parent Relationship") == "Member"):
        return "<partition-member>"
    if key in EXPRESSION_KEYS:
        return _normalize(value)
    return value


# ───────────────────────────── fingerprints ─────────────────────────────────

def clean_node(node: Dict[str, Any],
               cfg: ComparatorConfig = DEFAULT_CONFIG,
               parent_node_type: Optional[str] = None) -> Dict[str, Any]:
    """The witness view of a node: exactly what the shape hash sees."""
    cleaned: Dict[str, Any] = {}
    for key in cfg.shape_keys():
        value = _shape_value(node, key, parent_node_type, cfg)
        if value is not None:
            cleaned[key] = value
    for key in CONDITION_KEYS:
        if key in node:
            cleaned[key] = _normalize(node[key])
    if "Plans" in node:
        node_type = node.get("Node Type")
        cleaned["Plans"] = [clean_node(child, cfg, node_type)
                            for child in node["Plans"]]
    return cleaned


def collect_literals(plan: Any,
                     cfg: ComparatorConfig = DEFAULT_CONFIG) -> List[str]:
    """All literals/parameters in tree order: the parameter view."""
    acc: List[str] = []

    def walk(node: Dict[str, Any]) -> None:
        for key in CONDITION_KEYS + EXPRESSION_KEYS:
            if key in node:
                _extract_literals(node[key], acc)
        for child in node.get("Plans", []):
            walk(child)

    walk(_root(plan))
    return acc


def _digest(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def shape_hash(plan: Any, config: ComparatorConfig = DEFAULT_CONFIG) -> str:
    """Hash of witnesses only. Differs  <=>  plan change guaranteed."""
    return _digest(clean_node(_root(plan), config))


def param_hash(plan: Any, config: ComparatorConfig = DEFAULT_CONFIG) -> str:
    """Hash of literal values only."""
    return _digest(collect_literals(plan, config))


@dataclass(frozen=True)
class Fingerprint:
    shape: str
    params: str


def fingerprint(plan: Any,
                config: ComparatorConfig = DEFAULT_CONFIG) -> Fingerprint:
    return Fingerprint(shape_hash(plan, config), param_hash(plan, config))


def structural_hash(plan: Any, strict: bool = False,
                    config: ComparatorConfig = DEFAULT_CONFIG) -> str:
    """Backward-compatible wrapper for the original single-hash API.

    strict=False -> the shape hash (the meaningful identity).
    strict=True  -> shape and literals folded together. Note that two
    differing strict hashes do NOT imply a plan change (the difference
    may be purely parametric) — prefer compare().
    """
    if strict:
        fp = fingerprint(plan, config)
        return _digest([fp.shape, fp.params])
    return shape_hash(plan, config)


# ───────────────────────────── comparison ───────────────────────────────────

@dataclass(frozen=True)
class FieldDiff:
    """One observed difference, located in the tree.

    kind: decision | identity | condition | structure  (witnesses)
          label | literal                              (attribution)
    """
    path: str
    node_type: str
    key: str
    a: Any
    b: Any
    kind: str


_JOIN_NODES = {"Nested Loop", "Hash Join", "Merge Join"}
_AGG_NODES = {"Aggregate", "Group", "WindowAgg", "SetOp"}
_PARALLEL_NODES = {"Gather", "Gather Merge"}
_AUX_NODES = {"Sort", "Incremental Sort", "Materialize", "Memoize",
              "Hash", "Unique"}

_KEY_CATEGORY = {
    "Join Type": "JOIN", "Hash Cond": "JOIN", "Merge Cond": "JOIN",
    "Join Filter": "JOIN", "Parent Relationship": "JOIN",
    "Inner Unique": "JOIN",
    "Index Name": "SCAN", "Scan Direction": "SCAN", "Index Cond": "SCAN",
    "Recheck Cond": "SCAN", "TID Cond": "SCAN", "Relation Name": "SCAN",
    "Function Name": "SCAN", "Table Function Name": "SCAN",
    "Custom Plan Provider": "SCAN",
    "Strategy": "AGG", "Partial Mode": "AGG", "Group Key": "AGG",
    "Parallel Aware": "PARALLEL", "Workers Planned": "PARALLEL",
    "Single Copy": "PARALLEL",
    "Sort Key": "AUX", "Presorted Key": "AUX", "Cache Key": "AUX",
    "Command": "DML", "Operation": "DML",
}

_CATEGORY_ORDER = ("ROOT", "SCAN", "JOIN", "AGG",
                   "PARALLEL", "AUX", "DML", "STRUCTURE")


def _node_category(node_type: str) -> str:
    if node_type in _JOIN_NODES:
        return "JOIN"
    if node_type in _AGG_NODES:
        return "AGG"
    if node_type in _PARALLEL_NODES:
        return "PARALLEL"
    if node_type in _AUX_NODES:
        return "AUX"
    if "Scan" in node_type:
        return "SCAN"
    return "STRUCTURE"


def _classify(witness: FieldDiff) -> set:
    categories = set()
    if witness.key == "Node Type":
        if witness.path == "Plan":
            categories.add("ROOT")
        for value in (witness.a, witness.b):
            if isinstance(value, str):
                categories.add(_node_category(value))
    elif witness.kind == "structure":
        categories.add("STRUCTURE")
    elif witness.key in _KEY_CATEGORY:
        categories.add(_KEY_CATEGORY[witness.key])
    elif witness.kind == "condition":
        categories.add(_node_category(witness.node_type))
    else:
        categories.add("STRUCTURE")
    return categories


def _diff(a: Dict[str, Any], b: Dict[str, Any], path: str,
          parent_node_type: Optional[str], cfg: ComparatorConfig,
          witnesses: List[FieldDiff], attributions: List[FieldDiff]) -> None:
    node_type = a.get("Node Type", b.get("Node Type", "?"))

    for key in cfg.shape_keys():
        va = _shape_value(a, key, parent_node_type, cfg)
        vb = _shape_value(b, key, parent_node_type, cfg)
        if va != vb:
            kind = "identity" if key in IDENTITY_KEYS else "decision"
            witnesses.append(FieldDiff(path, node_type, key, va, vb, kind))

    for key in CONDITION_KEYS:
        ra, rb = a.get(key), b.get(key)
        na = _normalize(ra) if ra is not None else None
        nb = _normalize(rb) if rb is not None else None
        if na != nb:
            witnesses.append(
                FieldDiff(path, node_type, key, na, nb, "condition"))
        elif ra != rb:
            attributions.append(
                FieldDiff(path, node_type, key, ra, rb, "literal"))

    for key in LABEL_KEYS:
        if a.get(key) != b.get(key):
            attributions.append(
                FieldDiff(path, node_type, key, a.get(key), b.get(key),
                          "label"))

    children_a = a.get("Plans", [])
    children_b = b.get("Plans", [])
    if len(children_a) != len(children_b):
        witnesses.append(FieldDiff(
            path, node_type, "Plans",
            "%d children" % len(children_a),
            "%d children" % len(children_b),
            "structure"))
    for i, (ca, cb) in enumerate(zip(children_a, children_b)):
        _diff(ca, cb, "%s/Plans[%d]" % (path, i), node_type, cfg,
              witnesses, attributions)


@dataclass(frozen=True)
class PlanComparison:
    verdict: str                       # STRUCTURAL | PARAMETRIC | IDENTICAL
    change_types: Tuple[str, ...]      # e.g. ("ROOT", "SCAN") — empty unless STRUCTURAL
    distance: int                      # witness count (upper-bound heuristic)
    witnesses: Tuple[FieldDiff, ...]   # Bucket-1 differences (the proof)
    attributions: Tuple[FieldDiff, ...]  # Bucket-2 differences (the context)
    a: Fingerprint
    b: Fingerprint

    @property
    def plan_changed(self) -> bool:
        return self.verdict == "STRUCTURAL"

    def summary(self) -> str:
        if self.verdict == "IDENTICAL":
            return "IDENTICAL — same plan, same parameters."
        if self.verdict == "PARAMETRIC":
            return ("PARAMETRIC — same plan shape; %d literal/label "
                    "difference(s)." % len(self.attributions))
        return ("STRUCTURAL — plan changed (%s); %d witness(es), "
                "%d attribution(s)."
                % (", ".join(self.change_types) or "STRUCTURE",
                   self.distance, len(self.attributions)))


def compare(plan_a: Any, plan_b: Any,
            config: ComparatorConfig = DEFAULT_CONFIG) -> PlanComparison:
    """Compare two plans for the same normalized query.

    Verdict logic (the Witness Principle): a plan change is guaranteed
    if and only if at least one witness differs — i.e. the shape hashes
    differ. Label and literal differences alone are never sufficient.

    Note: child alignment is positional, so `distance` after a node
    insertion is an upper bound, not a true tree-edit distance. The
    verdict itself is exact either way (a child-count mismatch is
    itself a witness).
    """
    fa = fingerprint(plan_a, config)
    fb = fingerprint(plan_b, config)

    witnesses: List[FieldDiff] = []
    attributions: List[FieldDiff] = []
    _diff(_root(plan_a), _root(plan_b), "Plan", None, config,
          witnesses, attributions)

    if fa.shape != fb.shape:
        verdict = "STRUCTURAL"
        categories = set()
        for w in witnesses:
            categories |= _classify(w)
        change_types = tuple(c for c in _CATEGORY_ORDER if c in categories)
    elif fa.params != fb.params:
        verdict, change_types = "PARAMETRIC", ()
    else:
        verdict, change_types = "IDENTICAL", ()

    return PlanComparison(verdict, change_types, len(witnesses),
                          tuple(witnesses), tuple(attributions), fa, fb)


# ───────────────────────────── display utilities ────────────────────────────

def count_nodes(plan: Any) -> int:
    def walk(node: Dict[str, Any]) -> int:
        return 1 + sum(walk(c) for c in node.get("Plans", []))
    return walk(_root(plan))


def max_depth(plan: Any) -> int:
    def walk(node: Dict[str, Any], depth: int = 0) -> int:
        child_depths = [walk(c, depth + 1) for c in node.get("Plans", [])]
        return max(child_depths) if child_depths else depth
    return walk(_root(plan))


def short_label(plan: Any) -> str:
    def _node_label(node: Dict[str, Any]) -> str:
        parts = [node.get("Node Type", "?")]
        if "Relation Name" in node:
            parts.append("on %s" % node["Relation Name"])
        if "Index Name" in node:
            parts.append("using %s" % node["Index Name"])
        if "Join Type" in node:
            parts.append("(%s)" % node["Join Type"])
        if node.get("Parallel Aware"):
            parts.insert(0, "Parallel")
        return " ".join(parts)

    def _walk(node: Dict[str, Any]) -> List[str]:
        labels = []
        skip = node.get("Node Type", "") in (
            "Aggregate", "Sort", "Hash", "Materialize",
            "Incremental Sort", "Memoize")
        if not skip:
            labels.append(_node_label(node))
        for child in node.get("Plans", []):
            labels.extend(_walk(child))
        return labels

    root = _root(plan)
    labels = _walk(root)
    return " → ".join(labels) if labels else _node_label(root)


def build_tree_lines(node: Dict[str, Any], prefix: str = "",
                     is_last: bool = True) -> List[str]:
    connector = "└── " if is_last else "├── "
    label = node.get("Node Type", "?")
    extras = []
    if "Strategy" in node and node["Strategy"] != "Plain":
        extras.append(node["Strategy"])
    if "Partial Mode" in node and node["Partial Mode"] != "Simple":
        extras.append(node["Partial Mode"])
    if "Relation Name" in node:
        extras.append("on %s" % node["Relation Name"])
    if "Index Name" in node:
        extras.append("using %s" % node["Index Name"])
    if "Join Type" in node:
        extras.append("(%s)" % node["Join Type"])
    for ck in CONDITION_KEYS:
        if ck in node:
            extras.append("%s: %s" % (ck, node[ck]))
    detail = "  " + ", ".join(extras) if extras else ""
    lines = ["%s%s%s%s" % (prefix, connector, label, detail)]
    children = node.get("Plans", [])
    child_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(children):
        lines.extend(build_tree_lines(child, child_prefix,
                                      i == len(children) - 1))
    return lines


def plan_tree_str(plan: Any) -> str:
    return "\n".join(build_tree_lines(_root(plan), prefix="  ", is_last=True))


# ───────────────────────────── self-demonstration ───────────────────────────

if __name__ == "__main__":
    index_42 = {"Plan": {
        "Node Type": "Index Scan", "Relation Name": "orders",
        "Schema": "public", "Alias": "o",
        "Index Name": "orders_pkey", "Scan Direction": "Forward",
        "Index Cond": "(id = 42)",
    }}
    index_99 = {"Plan": {
        "Node Type": "Index Scan", "Relation Name": "orders",
        "Schema": "tenant_7", "Alias": "ord",
        "Index Name": "orders_pkey", "Scan Direction": "Forward",
        "Index Cond": "(id = 99)",
    }}
    seq_scan = {"Plan": {
        "Node Type": "Seq Scan", "Relation Name": "orders",
        "Schema": "public", "Alias": "o",
        "Filter": "(id = 42)",
    }}

    print("A vs B :", compare(index_42, index_99).summary())
    #   PARAMETRIC — literal 42->99 plus Schema/Alias label changes:
    #   pure Bucket-2 deltas, so no plan change is claimed.

    result = compare(index_42, seq_scan)
    print("A vs C :", result.summary())
    for w in result.witnesses:
        print("  witness     %-18s %-12s %r -> %r"
              % (w.path, w.key, w.a, w.b))
    for x in result.attributions:
        print("  attribution %-18s %-12s %r -> %r"
              % (x.path, x.key, x.a, x.b))