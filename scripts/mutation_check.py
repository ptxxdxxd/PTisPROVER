"""Plant known bugs in a copy of the source and check that the test suite notices each one.

    python scripts/mutation_check.py

The working tree is never modified: each bug is applied to a temporary copy,
and the tests run against that copy. Exits 1 if any planted bug survives.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = [
    "tests/test_differential.py",
    "tests/test_smt.py",
    "tests/test_prover.py",
    "tests/test_evaluate.py",
    "tests/test_parser.py",
]


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    old: str
    new: str


MUTATIONS = [
    Mutation(
        "exploit search stops at the first counterexample",
        "prover.py",
        "for _ in range(MAX_STRENGTHENING_STEPS):",
        "for _ in range(0):",
    ),
    Mutation(
        "exploit at exactly the threshold is let through",
        "prover.py",
        "if best.score >= threshold:",
        "if best.score > threshold:",
    ),
    Mutation(
        "overlap reported in the wrong direction",
        "prover.py",
        "implies[a, b] = None if counterexample is None else not counterexample",
        "implies[b, a] = None if counterexample is None else not counterexample",
    ),
    Mutation(
        "solver score is not floored at 0",
        "smt.py",
        "floored = z3.If(net < zero, zero, net)",
        "floored = net",
    ),
    Mutation(
        "solver ignores zeroing penalties",
        "smt.py",
        "return z3.If(z3.Or(*zeroing, self.ctx), zero, floored)",
        "return floored",
    ),
    Mutation(
        "solver compares bit-vectors as signed",
        "smt.py",
        "return z3.ULT(left, right) if unsigned else left < right",
        "return left < right",
    ),
    Mutation(
        "reference evaluator gets 'implies' wrong",
        "evaluate.py",
        "return (not left) or right",
        "return left or right",
    ),
    Mutation(
        "parser gives 'or' the precedence of 'and'",
        "parser.py",
        '"or": ("or", 3, 4),',
        '"or": ("or", 5, 6),',
    ),
]


def run_tests(copy: Path) -> int:
    env = {**os.environ, "PYTHONPATH": str(copy / "src"), "HYPOTHESIS_PROFILE": "ci"}
    command = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS]
    return subprocess.run(command, cwd=copy, env=env, capture_output=True, check=False).returncode


def make_copy(directory: Path) -> Path:
    copy = directory / "repo"
    for name in ("src", "tests"):
        shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", copy / "pyproject.toml")
    return copy


def main() -> int:
    survivors = 0
    with tempfile.TemporaryDirectory() as tmp:
        copy = make_copy(Path(tmp))
        if run_tests(copy) != 0:
            print("the unmodified copy does not pass its tests; nothing was checked")
            return 2
        print("baseline  the unmodified copy passes")
        for mutation in MUTATIONS:
            target = copy / "src" / "rubric_prover" / mutation.file
            original = target.read_text(encoding="utf-8")
            if original.count(mutation.old) != 1:
                print(f"STALE     {mutation.name}: the line to change is not in {mutation.file}")
                survivors += 1
                continue
            target.write_text(original.replace(mutation.old, mutation.new), encoding="utf-8")
            code = run_tests(copy)
            target.write_text(original, encoding="utf-8")
            # pytest exits 1 when a test fails. Anything else means the bug went unnoticed.
            if code == 1:
                print(f"caught    {mutation.name}")
            else:
                print(f"SURVIVED  {mutation.name} (pytest exit {code})")
                survivors += 1
    print(f"{len(MUTATIONS) - survivors} of {len(MUTATIONS)} planted bugs caught")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
