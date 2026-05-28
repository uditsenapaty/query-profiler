"""
run.py — Run sweep + analyze in sequence.

Usage:
    python run.py                  # all queries, default settings
    python run.py qt1 qt3 qt8      # specific queries
    python run.py --runs 5         # 5 timing runs for analysis
"""

import subprocess
import sys
import time

def main():
    args = sys.argv[1:]
    
    # Separate our flags from query names
    queries = []
    runs = "3"
    resolution = "1000"
    
    i = 0
    while i < len(args):
        if args[i] == "--runs" and i + 1 < len(args):
            runs = args[i + 1]; i += 2
        elif args[i] == "--resolution" and i + 1 < len(args):
            resolution = args[i + 1]; i += 2
        else:
            queries.append(args[i]); i += 1

    query_args = queries if queries else ["--all"]

    print(f"\n{'━' * 50}")
    print(f"  Step 1: Sweep")
    print(f"{'━' * 50}\n")
    
    t0 = time.time()
    r1 = subprocess.run(
        [sys.executable, "sweep.py"] + query_args + ["--resolution", resolution],
        cwd=sys.path[0] or "."
    )
    if r1.returncode != 0:
        print("Sweep failed!"); return

    print(f"\n{'━' * 50}")
    print(f"  Step 2: Analyze")
    print(f"{'━' * 50}\n")

    r2 = subprocess.run(
        [sys.executable, "analyze.py"] + query_args + ["--runs", runs],
        cwd=sys.path[0] or "."
    )

    total = time.time() - t0
    print(f"\n{'━' * 50}")
    print(f"  Done. Total: {total/60:.1f} minutes")
    print(f"{'━' * 50}\n")


if __name__ == "__main__":
    main()