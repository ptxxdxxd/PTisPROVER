"""Fill in the measured parts of README.md.

    python scripts/build_readme.py          # rewrite README.md
    python scripts/build_readme.py --check  # exit 1 if README.md is out of date

Each part sits between '<!-- BEGIN GENERATED: name -->' and '<!-- END GENERATED: name -->'.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import z3

from ptisprover import __version__, load_rubric
from ptisprover.prover import prove
from ptisprover.render import render_text
from ptisprover.report import Status

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
EXAMPLES = sorted((ROOT / "examples").glob("*.toml"))
FIXTURES = sorted((ROOT / "tests" / "rubrics" / "original").glob("*.toml"))
EXIT_CODES = {Status.PASS: 0, Status.FAIL: 1, Status.INCONCLUSIVE: 2}


def example_run() -> str:
    path = ROOT / "examples" / "coding_agent.toml"
    report = prove(load_rubric(path))
    return "\n".join(
        [
            "```console",
            "$ ptisprover check examples/coding_agent.toml",
            render_text(report, __version__).rstrip("\n"),
            "$ echo $?",
            str(EXIT_CODES[report.verdict]),
            "```",
        ]
    )


def examples_table() -> str:
    rows = ["| Rubric | Verdict | Solver queries | Work units |", "|---|---|---:|---:|"]
    for path in EXAMPLES:
        report = prove(load_rubric(path))
        rows.append(
            f"| [{path.name}](examples/{path.name}) | {report.verdict} "
            f"| {report.solver.queries} | {report.solver.work:,} |"
        )
    rows += ["", "What each example shows is in [examples/README.md](examples/README.md)."]
    return "\n".join(rows)


def evidence() -> str:
    differential = (ROOT / "tests" / "test_differential.py").read_text(encoding="utf-8")
    match = re.search(r'"DIFFERENTIAL_EXAMPLES", "(\d+)"', differential)
    if match is None:
        raise SystemExit("cannot find the differential test's example count")
    text_test = (ROOT / "tests" / "test_text_differential.py").read_text(encoding="utf-8")
    text_match = re.search(r'"DIFFERENTIAL_EXAMPLES", "(\d+)"', text_test)
    if text_match is None:
        raise SystemExit("cannot find the text differential test's example count")
    text_count = text_match.group(1)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cross_check.py"), "--strict"]
        + [str(p) for p in EXAMPLES + FIXTURES],
        capture_output=True,
        text=True,
        check=False,
    )
    summary = re.fullmatch(
        r"cvc5 (\S+): (\d+) queries agree, 0 undecided, 0 disagree",
        result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "",
    )
    if result.returncode != 0 or summary is None:
        raise SystemExit(f"cross-check did not pass:\n{result.stdout}{result.stderr}")
    return "\n".join(
        [
            f"- **Against brute force.** {match.group(1)} generated rubrics small enough to list "
            "every outcome; each answer the solver gives must match the answer found by listing "
            "them. (On CI the generator is seeded, so it is the same set each run.)",
            f"- **Against an evaluator that shares no code.** {text_count} more rubrics are "
            "generated as text alongside an equivalent Python expression. The text goes through "
            "the loader, parser, type checker and solver; the Python is run with `eval` over "
            "every outcome; the findings must match.",
            f"- **Against a second solver.** Every query can be exported as SMT-LIB2 "
            f"(`--emit-smt2`). cvc5 {summary.group(1)} agrees with Z3 "
            f"{z3.get_version_string()} on all {summary.group(2)} queries produced by the "
            f"{len(EXAMPLES)} examples and {len(FIXTURES)} test fixtures.",
        ]
    )


BLOCKS = {"example-run": example_run, "examples": examples_table, "evidence": evidence}


def render(text: str) -> str:
    for name, build in BLOCKS.items():
        begin, end = f"<!-- BEGIN GENERATED: {name} -->\n", f"<!-- END GENERATED: {name} -->"
        if text.count(begin) != 1 or text.count(end) != 1:
            raise SystemExit(f"README.md needs exactly one '{name}' block")
        head, rest = text.split(begin)
        _, tail = rest.split(end)
        text = f"{head}{begin}{build()}\n{end}{tail}"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report staleness, change nothing")
    args = parser.parse_args(argv)
    current = README.read_text(encoding="utf-8")
    expected = render(current)
    if current == expected:
        return 0
    if args.check:
        print("README.md is out of date; run: python scripts/build_readme.py")
        return 1
    README.write_text(expected, encoding="utf-8")
    print("wrote README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
