# =========================================================
# scripts/summary_all.py
#
# Standalone aggregator — scans every gt_results_* directory
# under cwd (or a given base path), collects summary.csv
# for every (run_type, resolution, method, query) combination,
# and writes one output file per (resolution × method × run_type):
#
#   gt_results_sfX_{res}/{qt_a_qt_b_.._qt_z}/summary_all_{method}_{run_type}.csv
#
# Example:
#   gt_results_sf1_10x10/qt1_qt5_qt8/summary_all_m0_s.csv
#   gt_results_sf1_10x10/qt1_qt5_qt8/summary_all_m1_s.csv
#   ...
#
# Format (wide, section-separated like summarise.py):
#   Section                        | Metric            | qt1 | qt5 | qt8
#   Basic stats                    |                   |     |     |
#                                  | Query             | QT1 | QT5 | QT8
#                                  | max_rt            | ... | ... | ...
#   Plan operator transition stats |                   |     |     |
#                                  | JOIN_transitions  | ... | ... | ...
#
# Usage:
#   python summary_all.py              # scan cwd
#   python summary_all.py /path/to/    # scan given base
# =========================================================

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


_GT_ROOT_RE = re.compile(
    r"^gt_results_sf(?P<sf>\d+)_(?P<resolution>\d+x\d+)_(?P<run_type>\w+)$",
    re.IGNORECASE,
)

_QUERY_DIR_RE = re.compile(
    r"^(?P<query>.+?)$",
    re.IGNORECASE,
)

_FRACTION_RE = re.compile(r"\b(\d+)/(\d+)\b")


# =========================================================
# helpers
# =========================================================

def _sanitize_value(v: str) -> str:
    """Replace N/N fractions with 'N of N' to prevent Excel date coercion."""
    return _FRACTION_RE.sub(r"\1 of \2", v)


def _read_summary(path: Path) -> pd.Series:
    """
    Read a summary.csv -> Series indexed by (Section, Metric) -> Value.
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
    df["Metric"] = df["Metric"].str.strip()
    df["Value"] = df["Value"].str.strip().apply(_sanitize_value)

    return df.set_index(["Section", "Metric"])["Value"]


def _format_with_separators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply section-separator formatting:
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
            formatted.append({"Section": section, "Metric": "", **blank_vals})
            last_section = section

        formatted.append(
            {
                "Section": "",
                "Metric": row["Metric"],
                **{c: row[c] for c in value_cols},
            }
        )

    return pd.DataFrame(formatted, columns=df.columns)


def _discover_summaries(base: Path) -> dict:
    """
    Walk base looking for:
      gt_results_sfX_RESOLUTION_SUFFIX/QUERYDIR/METHOD/summary.csv

    Returns nested dict:
      {
        (gt_root_path, resolution, run_type, method): {
            query: summary_path,
            ...
        },
        ...
      }
    """
    index: dict = {}

    for gt_root in sorted(base.iterdir()):
        if not gt_root.is_dir():
            continue

        gt_match = _GT_ROOT_RE.match(gt_root.name)
        if not gt_match:
            continue

        resolution = gt_match.group("resolution")

        for query_dir in sorted(gt_root.iterdir()):
            if not query_dir.is_dir():
                continue

            qmatch = _QUERY_DIR_RE.match(query_dir.name)
            if not qmatch:
                continue

            query = qmatch.group("query")
            run_type = qmatch.group("run_type").lower()

            for method_dir in sorted(query_dir.iterdir()):
                if not method_dir.is_dir():
                    continue

                summary_path = method_dir / "summary.csv"
                if not summary_path.exists():
                    continue

                method = method_dir.name
                key = (gt_root, resolution, run_type, method)

                index.setdefault(key, {})[query] = summary_path

    return index


# =========================================================
# main
# =========================================================

def run(base_path: Path):
    base_path = Path(base_path).resolve()

    print()
    print("=" * 70)
    print("SUMMARY ALL — AGGREGATING ACROSS QUERIES")
    print("=" * 70)
    print(f"Scanning : {base_path}")

    index = _discover_summaries(base_path)

    if not index:
        print(
            "No summary.csv files found. "
            f"Check that gt_results_* directories exist under:\n  {base_path}"
        )
        return

    total_files = 0

    for (gt_root, res, run_type, method) in sorted(
        index.keys(),
        key=lambda x: (str(x[0]), x[1], x[2], x[3]),
    ):
        query_paths = index[(gt_root, res, run_type, method)]
        queries = sorted(query_paths)

        # queries_dir_name = "_".join(queries)
        out_dir = gt_root / "summaries" # queries_dir_name
        out_dir.mkdir(parents=True, exist_ok=True)

        print()
        print(f"  GT root   : {gt_root.name}")
        print(f"  Run type  : {run_type}")
        print(f"  Resolution: {res}")
        print(f"  Method    : {method}")
        print(f"  Queries   : {queries}")

        # -----------------------------------------
        # Load each query's summary into a Series
        # -----------------------------------------
        series_map = {}

        for query in queries:
            try:
                series_map[query] = _read_summary(query_paths[query])
            except Exception as e:
                print(f"    [WARN] skipping {query}: {e}")

        if not series_map:
            print(
                f"    [WARN] no valid summaries for {method} @ {res} [{run_type}]"
            )
            continue

        # -----------------------------------------
        # Build wide DataFrame
        # rows  = (Section, Metric)
        # cols  = query names (sorted)
        # -----------------------------------------
        wide = pd.DataFrame(series_map)
        wide.index.names = ["Section", "Metric"]
        wide.columns.name = None
        wide = wide.reset_index()

        # Apply section-separator formatting
        wide = _format_with_separators(wide)

        # -----------------------------------------
        # Save inside the GT root:
        #   gt_results_sfX_RES/qt1_qt5_qt8/summary_all_{method}_{run_type}.csv
        # -----------------------------------------
        out_name = f"summary_all_{method}_{run_type}.csv"
        out_path = out_dir / out_name

        wide.to_csv(out_path, index=False)

        total_files += 1

        print(
            f"    Saved ({len(wide)} rows, {len(series_map)} queries): "
            f"{gt_root.name}/summaries/{out_name}" # {queries_dir_name}/{out_name}"
        )

    print()
    print("=" * 70)
    print(f"DONE — wrote {total_files} file(s) under {base_path}")
    print("=" * 70)


# =========================================================
# entry point
# =========================================================

if __name__ == "__main__":
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    run(base)