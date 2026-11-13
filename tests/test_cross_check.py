"""Every query can be exported and re-solved by cvc5, and a disagreement is reported."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from rubric_prover.cli import main
from rubric_prover.loader import load_rubric, loads_toml
from rubric_prover.prover import run_checks
from tests.conftest import ORIGINAL

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cross_check.py"
CONTRADICTORY = ORIGINAL / "contradictory_pricing.toml"


def cross_check(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, check=False
    )


def test_cvc5_agrees_on_every_example_and_fixture_query() -> None:
    rubrics = sorted((ROOT / "examples").glob("*.toml")) + sorted(ORIGINAL.glob("*.toml"))
    result = cross_check("--strict", *rubrics)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ", 0 undecided, 0 disagree" in result.stdout


def test_emitted_files_carry_the_question_and_answer(tmp_path: Path) -> None:
    out = tmp_path / "queries"
    (tmp_path / "queries").mkdir()
    stale = out / "query-999.smt2"
    stale.write_text("left over from an earlier run", encoding="utf-8")
    assert (
        main(["check", str(CONTRADICTORY), "--emit-smt2", str(out), "-o", str(tmp_path / "r")]) == 1
    )
    files = sorted(out.iterdir())
    assert stale not in files
    assert [f.name for f in files[:2]] == ["query-001.smt2", "query-002.smt2"]
    assert files[0].read_text(encoding="utf-8").splitlines()[:4] == [
        "; rubric: contradictory-pricing",
        "; question: does any outcome satisfy the bounds and assumptions",
        "; z3: sat",
        "(set-logic ALL)",
    ]
    result = cross_check("--strict", out)
    assert result.returncode == 0, result.stdout + result.stderr


def test_tracked_requirements_are_exported_as_plain_assertions() -> None:
    """Z3 would export them as 'tracker => formula', which is satisfiable by itself."""
    proof = run_checks(load_rubric(CONTRADICTORY), keep_smt2=True)
    unsat = next(q for q in proof.queries if q.label == "can an outcome score 1")
    assert unsat.smt2 is not None
    assert "req!" not in unsat.smt2


def test_a_single_criterion_score_is_valid_smt_lib(tmp_path: Path) -> None:
    """z3.Sum over one term prints '(+ x)', which cvc5 rejects."""
    rubric = loads_toml(
        'id = "one"\nexploit_threshold = 0.5\n[variables]\nx = { type = "int", min = 0, max = 9 }\n'
        '[[criteria]]\nid = "c"\nweight = 1\nwhen = "x > 4"\n'
        '[[penalties]]\nid = "p"\ndeduct = 0.5\nwhen = "x == 9"\n'
        '[[invariants]]\nid = "i"\nholds = "x != 7"\n'
    )
    proof = run_checks(rubric, keep_smt2=True)
    assert any("score above" in q.label for q in proof.queries)
    assert all(q.smt2 is not None and "(+ (ite" not in q.smt2 for q in proof.queries)
    out = tmp_path / "queries"
    out.mkdir()
    for name, text in proof.smt2_files().items():
        (out / name).write_text(text, encoding="utf-8")
    result = cross_check("--strict", out)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (lambda text: text.replace("(check-sat)", "(assert false)\n(check-sat)"), "DISAGREE"),
        (lambda text: text.replace("; z3: sat", "; z3: unsat"), "DISAGREE"),
    ],
    ids=["query-altered", "answer-altered"],
)
def test_a_disagreement_is_reported(
    tmp_path: Path, edit: Callable[[str], str], expected: str
) -> None:
    out = tmp_path / "queries"
    main(["check", str(CONTRADICTORY), "--emit-smt2", str(out), "-o", str(tmp_path / "r")])
    first = out / "query-001.smt2"
    first.write_text(edit(first.read_text(encoding="utf-8")), encoding="utf-8")
    result = cross_check(out)
    assert result.returncode == 1
    assert f"{expected}   {first}: z3 " in result.stdout
    assert "question: does any outcome satisfy the bounds and assumptions" in result.stdout
    assert ", 1 disagree" in result.stdout


def test_cvc5_undecided_fails_only_in_strict_mode(tmp_path: Path) -> None:
    out = tmp_path / "queries"
    main(["check", str(CONTRADICTORY), "--emit-smt2", str(out), "-o", str(tmp_path / "r")])
    first = out / "query-001.smt2"
    first.write_text(
        first.read_text(encoding="utf-8").replace("; z3: sat", "; z3: unknown"), encoding="utf-8"
    )
    assert cross_check(out).returncode == 0
    strict = cross_check("--strict", out)
    assert strict.returncode == 1
    assert "undecided" in strict.stdout


def test_smt2_files_need_the_query_text() -> None:
    proof = run_checks(load_rubric(CONTRADICTORY))
    with pytest.raises(ValueError, match="keep_smt2=True"):
        proof.smt2_files()
