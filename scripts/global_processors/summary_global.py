# =========================================================
# scripts/global_processors/summary_global.py
#
# Merges per-method summary.csv files for a single query
# into one wide table, one column per method.
#
# Called by build_gt.py as a global processor:
#   run(config_gt.MAIN_DIR / config_gt.GLOBAL_PROCESSOR_RES)
#
# Input layout expected under results_dir:
#   {results_dir}/m0/summary.csv
#   {results_dir}/m1/summary.csv
#   {results_dir}/m2/summary.csv
#   ...
#
# Output:
#   {results_dir}/summary_methods.csv
#
# Format (wide, section-separated like summarise.py):
#   Section                        | Metric            | m0  | m1  | m2
#   Basic stats                    |                   |     |     |
#                                  | Query             | QT8 | QT8 | QT8
#                                  | max_rt            | ... | ... | ...
#   Plan operator transition stats |                   |     |     |
#                                  | JOIN_transitions  | ... | ... | ...
# =========================================================

from pathlib import Path
import re

import numpy as np
import pandas as pd


# =========================================================
# helpers
# =========================================================

_GT_DIR_RE = re.compile(
    r"^gt_results_sf\d+_.+?_(?P<run_type>[sm])$",
    re.IGNORECASE,
)

_FRACTION_RE = re.compile(r"\b(\d+)/(\d+)\b")


def _infer_run_type(results_dir: Path) -> str:
    for part in reversed(results_dir.parts):
        m = _GT_DIR_RE.match(part)
        if m:
            return m.group("run_type").lower()
    return "unknown"


def _sanitize_value(v: str) -> str:
    """Replace N/N fractions with 'N of N' to prevent Excel date coercion."""
    return _FRACTION_RE.sub(r"\1 of \2", v)


def _read_summary(path: Path) -> pd.Series:
    """
    Read a summary.csv → Series indexed by (Section, Metric) → Value.
    Drops blank separator rows, forward-fills Section, sanitizes values.
    """
    df = pd.read_csv(path, dtype=str).fillna("")

    if not {"Section", "Metric", "Value"}.issubset(df.columns):
        raise ValueError(
            f"Expected Section/Metric/Value columns in:\n{path}"
        )

    df["Section"] = df["Section"].replace("", np.nan).ffill()
    df = df[df["Metric"].str.strip() != ""].copy()

    df["Section"] = df["Section"].str.strip()
    df["Metric"]  = df["Metric"].str.strip()
    df["Value"]   = df["Value"].str.strip().apply(_sanitize_value)

    return df.set_index(["Section", "Metric"])["Value"]


def _format_with_separators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply the same section-separator formatting as summarise.py:
      - one blank header row per new Section (Section name in Section col,
        empty string in all other cols)
      - data rows with Section blanked out

    Input df must have columns: Section, Metric, <value cols...>
    """
    value_cols = [c for c in df.columns if c not in ("Section", "Metric")]
    blank_vals = {c: "" for c in value_cols}

    formatted = []
    last_section = None

    for _, row in df.iterrows():

        section = row["Section"]

        if section != last_section:
            # Section header separator row
            formatted.append(
                {"Section": section, "Metric": "", **blank_vals}
            )
            last_section = section

        # Data row — Section blanked out
        formatted.append(
            {
                "Section": "",
                "Metric": row["Metric"],
                **{c: row[c] for c in value_cols},
            }
        )

    return pd.DataFrame(formatted, columns=df.columns)


def _discover_methods(results_dir: Path) -> dict:
    """
    Return {method_name: method_dir} for every subdir that has
    a summary.csv, sorted by name.
    """
    found = {}
    for d in sorted(results_dir.iterdir()):
        if not d.is_dir():
            continue
        if (d / "summary.csv").exists():
            found[d.name] = d
    return found


# =========================================================
# entry point
# =========================================================

def run(results_dir):

    results_dir = Path(results_dir)
    run_type    = _infer_run_type(results_dir)

    print()
    print("=" * 60)
    print("SUMMARY GLOBAL — MERGING METHOD SUMMARIES")
    print("=" * 60)
    print(f"Resolution dir : {results_dir}")
    print(f"Run type       : {run_type}")

    method_dirs = _discover_methods(results_dir)

    if not method_dirs:
        print(f"No method summary.csv files found under:\n  {results_dir}")
        return

    print(f"Methods found  : {', '.join(method_dirs)}")

    # =====================================================
    # Read each method summary → wide DataFrame
    # =====================================================

    series_map = {}

    for method, mdir in method_dirs.items():
        try:
            series_map[method] = _read_summary(mdir / "summary.csv")
        except Exception as e:
            print(f"  [WARN] skipping {method}: {e}")

    if not series_map:
        print("No valid summaries loaded.")
        return

    # Wide: rows = (Section, Metric), cols = method names
    merged = pd.DataFrame(series_map)
    merged.index.names = ["Section", "Metric"]
    merged.columns.name = None
    merged = merged.reset_index()

    # Apply section-separator formatting (matches summarise.py output style)
    merged = _format_with_separators(merged)

    # =====================================================
    # Save
    # =====================================================

    out_path = results_dir / "summary_methods.csv"
    merged.to_csv(out_path, index=False)

    print()
    print(f"Rows    : {len(merged)}")
    print(f"Methods : {list(series_map)}")
    print(f"Saved   : {out_path}")
    print()
    print(merged.to_string(index=False))
    print()
    print("DONE")


# =========================================================
# standalone test
# =========================================================

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "gt_results_sf10_qt8_s/10x10"
    run(path)