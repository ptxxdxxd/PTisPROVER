"""The prover against brute force: every answer must match on finite-domain rubrics."""

from __future__ import annotations

import os

from hypothesis import HealthCheck, given, settings

from rubric_prover.evaluate import assess
from rubric_prover.model import Rubric
from rubric_prover.prover import prove
from rubric_prover.report import Check, Finding, Report, Status
from tests import oracle
from tests.strategies import finite_rubrics

EXAMPLES = int(os.environ.get("DIFFERENTIAL_EXAMPLES", "500"))


def by_check(report: Report, check: Check) -> list[Finding]:
    return [f for f in report.findings if f.check is check]


def implications(report: Report) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for finding in by_check(report, Check.OVERLAP):
        if finding.status is not Status.WARN:
            continue
        a, b = finding.subjects
        found.add((a, b))
        if "exactly the same outcomes" in finding.message:
            found.add((b, a))
    return found


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(finite_rubrics())
def test_prover_agrees_with_brute_force(rubric: Rubric) -> None:
    report = prove(rubric)
    truth = oracle.expected(rubric)

    assert all(f.status is not Status.INCONCLUSIVE for f in report.findings), report.findings
    for finding in report.findings:
        if finding.example is not None:
            replay = assess(rubric, finding.example.assignment)
            assert replay.admissible
            assert replay.score == finding.example.score

    (outcomes,) = by_check(report, Check.OUTCOMES)
    if not truth.exists:
        assert outcomes.status is Status.FAIL
        assert outcomes.conflict is not None
        assert oracle.conflict_is_unsatisfiable(rubric, [i.path for i in outcomes.conflict.items])
        assert {f.status for f in report.findings[1:]} == {Status.SKIPPED}
        assert report.verdict is Status.FAIL
        return
    assert outcomes.status is Status.PASS

    (perfect,) = by_check(report, Check.PERFECT_SCORE)
    assert (perfect.status is Status.PASS) == truth.perfect
    if not truth.perfect:
        assert perfect.conflict is not None
        assert perfect.conflict.minimal
        assert oracle.conflict_is_unsatisfiable(rubric, [i.path for i in perfect.conflict.items])

    exploits = by_check(report, Check.EXPLOIT)
    if not rubric.invariants:
        assert [f.status for f in exploits] == [Status.WARN]
    for finding, invariant in zip(exploits, rubric.invariants, strict=False):
        assert finding.subjects == (invariant.id,)
        worst = truth.worst_exploit[invariant.id]
        assert finding.max_score == worst
        if worst is None:
            assert finding.status is Status.PASS
        else:
            assert finding.max_proven is True
            assert (finding.status is Status.FAIL) == (worst >= rubric.exploit_threshold)

    for finding, criterion in zip(by_check(report, Check.CRITERION), rubric.criteria, strict=True):
        healthy = truth.pays[criterion.id] and truth.fails[criterion.id]
        assert finding.status is (Status.PASS if healthy else Status.FAIL)

    assert implications(report) == truth.implies

    for finding, penalty in zip(by_check(report, Check.PENALTY), rubric.penalties, strict=True):
        if not truth.rests[penalty.id]:
            assert finding.status is Status.FAIL
        elif not truth.fires[penalty.id]:
            assert finding.status is Status.WARN
        else:
            assert finding.status is Status.PASS

    expected_verdict = Status.FAIL if truth.verdict_fails(rubric.exploit_threshold) else Status.PASS
    assert report.verdict is expected_verdict
