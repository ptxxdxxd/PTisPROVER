"""Solver work and wall-clock time for each example rubric.

    python scripts/benchmark.py [--runs N]

Queries and work units are the same on every machine with the same Z3 build.
Milliseconds are not: they describe the machine this was run on.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

from ptisprover import load_rubric
from ptisprover.prover import prove

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=20, help="timed runs per rubric (default 20)")
    args = parser.parse_args(argv)
    print("| Rubric | Verdict | Queries | Work units | Median ms | Slowest ms |")
    print("|---|---|---:|---:|---:|---:|")
    for path in sorted(EXAMPLES.glob("*.toml")):
        rubric = load_rubric(path)
        times = []
        for _ in range(args.runs):
            start = time.perf_counter()
            report = prove(rubric)
            times.append((time.perf_counter() - start) * 1000)
        stats = report.solver
        print(
            f"| {path.name} | {report.verdict} | {stats.queries} | {stats.work:,} "
            f"| {statistics.median(times):.1f} | {max(times):.1f} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
