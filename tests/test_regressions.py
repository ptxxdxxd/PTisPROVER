"""Regression tests for the defects found in the audit of the original project (R1-R6)."""

from __future__ import annotations

import json
from fractions import Fraction

from rubric_prover.loader import load_rubric, loads_json, loads_toml
from rubric_prover.prover import prove
from rubric_prover.report import Check, Report, Status
from tests.conftest import ORIGINAL

FERMAT = """
id = "fermat"
exploit_threshold = 0.85

[variables]
x = {{ type = "int", min = 1, max = {top} }}
y = {{ type = "int", min = 1, max = {top} }}
z = {{ type = "int", min = 1, max = {top} }}

[[criteria]]
id = "small_x"
weight = 0.5
when = "x <= 5"

[[criteria]]
id = "not_a_cube_sum"
weight = 0.5
when = "x * x * x + y * y * y != z * z * z"
"""


def test_r1_a_free_criterion_is_found_when_the_solver_can_decide() -> None:
    """x^3 + y^3 = z^3 has no positive solutions, so the second criterion is free reward."""
    report = prove(loads_toml(FERMAT.format(top=10)))
    finding = next(f for f in report.findings if f.subjects == ("not_a_cube_sum",))
    assert finding.status is Status.FAIL
    assert finding.message == "'not_a_cube_sum' pays for every admissible outcome: free reward"


def test_r1_an_undecided_check_is_never_a_pass() -> None:
    """The original called this rubric sound when its 30 ms timeout expired."""
    report = prove(loads_toml(FERMAT.format(top=60)), budget=200_000)
    finding = next(f for f in report.findings if f.subjects == ("not_a_cube_sum",))
    assert finding.status is Status.INCONCLUSIVE
    assert report.verdict is Status.INCONCLUSIVE


def test_r2_the_answer_does_not_depend_on_the_clock() -> None:
    """Budgets are solver work units, so repeated runs agree exactly (see test_determinism)."""
    rubric = loads_toml(FERMAT.format(top=10))
    first = prove(rubric).to_json()
    assert all(prove(rubric).to_json() == first for _ in range(3))


def test_r3_no_invariants_means_the_exploit_check_did_not_run() -> None:
    """The original reported 'unsat, passed' here without calling the solver."""
    report = prove(loads_toml(FERMAT.format(top=3)))
    (finding,) = [f for f in report.findings if f.check is Check.EXPLOIT]
    assert finding.status is Status.WARN
    assert finding.message == "no invariants declared, so the reward-hacking check did not run"


def test_r4_a_rubric_written_as_json_loads_and_is_checked() -> None:
    """The original refused every JSON rubric, including its own fixtures."""
    rubric = loads_json(
        json.dumps(
            {
                "id": "minimal",
                "exploit_threshold": 1,
                "variables": {"x": {"type": "int", "min": 0, "max": 10}},
                "criteria": [{"id": "c1", "weight": 1, "when": "x >= 5"}],
            }
        )
    )
    assert prove(rubric).verdict is Status.PASS


def test_r5_witnesses_are_exact() -> None:
    """The original printed 1/3 as 0.3333333333333333333333333333."""
    rubric = loads_toml(
        """
        id = "third"
        exploit_threshold = 1
        assume = ["a * 3 == 1"]
        [variables]
        a = "real"
        [[criteria]]
        id = "c"
        weight = 1
        when = "a > 0"
        """
    )
    report = prove(rubric)
    example = report.findings[0].example
    assert example is not None
    assert example.assignment["a"] == Fraction(1, 3)
    outcome = json.loads(report.to_json())["findings"][0]["example"]["outcome"]
    assert outcome == {"a": "1/3"}


def worst_exploit(report: Report, invariant: str) -> tuple[Fraction | None, bool | None]:
    (finding,) = [
        f for f in report.findings if f.check is Check.EXPLOIT and f.subjects == (invariant,)
    ]
    return finding.max_score, finding.max_proven


def test_r6_the_worst_exploit_is_reported_not_the_first() -> None:
    """Without its two assumptions, fixture 3 hides a perfect-score exploit."""
    shipped = prove(load_rubric(ORIGINAL / "loophole_volume.toml"))
    text = (ORIGINAL / "loophole_volume.toml").read_text(encoding="utf-8")
    start = text.index("assume = [")
    end = text.index("]\n", start) + 2
    without_assumptions = prove(loads_toml(text[:start] + text[end:]))

    # As shipped: margin < 0.05 forces uncapped liability, which forces the -0.12 margin
    # and earns 0.55 + 0.45 - 0.10 = 0.90.
    assert worst_exploit(shipped, "positive_margin") == (Fraction(9, 10), True)
    # Without them: a margin in [0, 0.05) breaks the invariant, trips no penalty
    # (the penalty only looks at margin < 0), and earns 0.55 + 0.45 = 1.
    assert worst_exploit(without_assumptions, "positive_margin") == (Fraction(1), True)
