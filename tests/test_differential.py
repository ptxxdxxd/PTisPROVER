"""The prover against brute force: every answer must match on finite-domain rubrics.

Rubrics here are built directly as typed IR, and outcomes are scored with the reference
evaluator. test_text_differential.py covers the parser and type checker with an evaluator
of its own.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, given, settings

from rubric_prover.evaluate import assess
from rubric_prover.model import Rubric
from rubric_prover.prover import prove
from rubric_prover.report import Check
from tests import oracle
from tests.compare import assert_report_matches, by_check
from tests.strategies import finite_rubrics

EXAMPLES = int(os.environ.get("DIFFERENTIAL_EXAMPLES", "500"))


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(finite_rubrics())
def test_prover_agrees_with_brute_force(rubric: Rubric) -> None:
    report = prove(rubric)
    assert_report_matches(
        report,
        oracle.truth(rubric),
        criteria=[c.id for c in rubric.criteria],
        penalties=[p.id for p in rubric.penalties],
        invariants=[i.id for i in rubric.invariants],
        threshold=rubric.exploit_threshold,
    )
    for finding in report.findings:
        if finding.example is not None:
            replay = assess(rubric, finding.example.assignment)
            assert replay.admissible
            assert replay.score == finding.example.score
    for check in (Check.OUTCOMES, Check.PERFECT_SCORE):
        (finding,) = by_check(report, check)
        if finding.conflict is not None:
            paths = [item.path for item in finding.conflict.items]
            assert finding.conflict.minimal
            assert oracle.conflict_is_genuine(rubric, paths)
            assert oracle.conflict_is_irreducible(rubric, paths) is not False
