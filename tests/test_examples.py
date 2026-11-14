"""The examples show what they say they show, and their committed reports are current."""

from __future__ import annotations

import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from ptisprover.loader import load_rubric
from ptisprover.prover import prove
from ptisprover.report import Check, Status

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def test_committed_example_reports_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_examples.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("name", "verdict", "check", "status", "subjects"),
    [
        ("coding_agent", Status.FAIL, Check.EXPLOIT, Status.FAIL, ("original_tests_kept",)),
        ("coding_agent_fixed", Status.PASS, Check.EXPLOIT, Status.PASS, ("original_tests_kept",)),
        ("support_reply", Status.FAIL, Check.EXPLOIT, Status.FAIL, ("refunds_only_on_request",)),
        ("summary_length", Status.FAIL, Check.PERFECT_SCORE, Status.FAIL, None),
        ("math_answer", Status.FAIL, Check.CRITERION, Status.FAIL, ("within_limit",)),
        ("math_answer", Status.FAIL, Check.OVERLAP, Status.WARN, ("thorough", "shows_work")),
    ],
)
def test_each_example_shows_its_flaw(
    name: str,
    verdict: Status,
    check: Check,
    status: Status,
    subjects: tuple[str, ...] | None,
) -> None:
    report = prove(load_rubric(EXAMPLES / f"{name}.toml"))
    assert report.verdict is verdict
    assert any(
        f.check is check and f.status is status and (subjects is None or f.subjects == subjects)
        for f in report.findings
    )


def test_the_fix_closes_the_exploit_completely() -> None:
    def worst(name: str) -> Fraction | None:
        report = prove(load_rubric(EXAMPLES / f"{name}.toml"))
        (finding,) = [f for f in report.findings if f.check is Check.EXPLOIT]
        assert finding.max_proven
        return finding.max_score

    # Editing the tests: 0.6 + 0.2 + 0.2 = 1 before the fix, zeroed after it.
    assert (worst("coding_agent"), worst("coding_agent_fixed")) == (Fraction(1), Fraction(0))
