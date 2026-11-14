"""The same rubric gives byte-identical reports, in this process and in fresh ones."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import z3

from ptisprover.loader import load_rubric
from ptisprover.prover import prove
from tests.conftest import EXAMPLES, ORIGINAL

RUBRICS = sorted(ORIGINAL.glob("*.toml")) + sorted(EXAMPLES.glob("*.toml"))

SCRIPT = (
    "import sys; from ptisprover import load_rubric, prove; "
    "sys.stdout.write(prove(load_rubric(sys.argv[1])).report.to_json())"
)


def report_in_fresh_process(path: Path) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


@pytest.mark.parametrize("path", sorted(ORIGINAL.glob("*.toml")), ids=lambda p: p.stem)
def test_reports_are_identical_across_processes(path: Path) -> None:
    here = prove(load_rubric(path)).report.to_json()
    assert report_in_fresh_process(path) == here
    assert report_in_fresh_process(path) == here


@pytest.mark.parametrize("path", RUBRICS, ids=lambda p: p.stem)
def test_work_does_not_depend_on_when_python_frees_z3_objects(
    monkeypatch: pytest.MonkeyPatch, path: Path
) -> None:
    # Python 3.14 releases temporaries at different moments than 3.13, and Z3 reuses the ids
    # of freed terms. Before each query got its own Context, math_answer.toml cost 6,730 work
    # units on 3.13 and 6,709 on 3.14. Never freeing anything is the extreme case.
    expected = prove(load_rubric(path)).report.to_json()
    for name in dir(z3):
        cls = getattr(z3, name)
        if isinstance(cls, type) and "__del__" in vars(cls):
            monkeypatch.setattr(cls, "__del__", lambda self: None)
    assert prove(load_rubric(path)).report.to_json() == expected


@pytest.mark.parametrize("path", RUBRICS, ids=lambda p: p.stem)
def test_exporting_smt2_does_not_change_the_report(path: Path) -> None:
    rubric = load_rubric(path)
    assert prove(rubric, keep_smt2=True).report.to_json() == prove(rubric).report.to_json()
