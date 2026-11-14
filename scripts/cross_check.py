"""Re-solve PTisPROVER's queries with cvc5 and compare the answers with Z3's.

    python scripts/cross_check.py examples/*.toml       # run the checks, compare every query
    python scripts/cross_check.py out/                  # compare files written by --emit-smt2

A query both solvers decide must get the same answer; anything else exits 1.
With --strict, a query Z3 decided and cvc5 could not also exits 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cvc5

from ptisprover import load_rubric
from ptisprover.prover import prove

CVC5_TIME_LIMIT_MS = 10_000


def solve_with_cvc5(text: str) -> str:
    """cvc5's answer to one SMT-LIB2 query: 'sat', 'unsat' or 'unknown'."""
    terms = cvc5.TermManager()
    solver = cvc5.Solver(terms)
    solver.setOption("tlimit-per", str(CVC5_TIME_LIMIT_MS))
    symbols = cvc5.SymbolManager(terms)
    parser = cvc5.InputParser(solver, symbols)
    parser.setStringInput(cvc5.InputLanguage.SMT_LIB_2_6, text, "query")
    answers = []
    while True:
        command = parser.nextCommand()
        if command.isNull():
            break
        output = command.invoke(solver, symbols).strip()
        if output:
            answers.append(output)
    if len(answers) != 1 or answers[0] not in ("sat", "unsat", "unknown"):
        raise ValueError(f"expected one check-sat answer from cvc5, got {answers}")
    return str(answers[0])


def header(text: str, key: str) -> str:
    prefix = f"; {key}: "
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise ValueError(f"no '{prefix.strip()}' header line")


def queries(source: Path) -> dict[str, str]:
    """Name -> SMT-LIB2 text, from a directory of query files or by checking a rubric file."""
    if source.is_dir():
        files = sorted(source.glob("query-*.smt2"))
        if not files:
            raise ValueError(f"no query-*.smt2 files in {source}")
        return {str(f): f.read_text(encoding="utf-8") for f in files}
    proof = prove(load_rubric(source), keep_smt2=True)
    return {f"{source}:{name}": text for name, text in proof.smt2_files().items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sources", nargs="+", type=Path, help="rubric files or --emit-smt2 dirs")
    parser.add_argument("--strict", action="store_true", help="fail if cvc5 cannot decide")
    args = parser.parse_args(argv)

    agreed = undecided = disagreed = 0
    for source in args.sources:
        for name, text in queries(source).items():
            z3_answer = header(text, "z3")
            try:
                cvc5_answer = solve_with_cvc5(text)
            except (RuntimeError, ValueError) as exc:
                disagreed += 1
                print(f"UNREADABLE {name}: cvc5 could not process the query: {exc}")
                continue
            if "unknown" in (z3_answer, cvc5_answer):
                undecided += 1
                print(f"undecided  {name}: z3 {z3_answer}, cvc5 {cvc5_answer}")
            elif z3_answer == cvc5_answer:
                agreed += 1
            else:
                disagreed += 1
                print(f"DISAGREE   {name}: z3 {z3_answer}, cvc5 {cvc5_answer}")
                print(f"           question: {header(text, 'question')}")
    print(
        f"cvc5 {cvc5.__version__}: {agreed} queries agree, "
        f"{undecided} undecided, {disagreed} disagree"
    )
    return 1 if disagreed or (args.strict and undecided) else 0


if __name__ == "__main__":
    sys.exit(main())
