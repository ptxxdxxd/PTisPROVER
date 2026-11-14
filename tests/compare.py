"""Compare a report with answers found by listing every outcome."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from rubric_prover.report import Check, Finding, Report, Status


@dataclass(frozen=True)
class Truth:
    """What listing every admissible outcome says about a rubric."""

    exists: bool
    perfect: bool
    worst_exploit: dict[str, Fraction | None]  # None: the invariant cannot be broken
    pays: dict[str, bool]
    fails: dict[str, bool]
    implies: frozenset[tuple[str, str]]  # among criteria that can both pay and fail
    fires: dict[str, bool]
    rests: dict[str, bool]

    @classmethod
    def from_outcomes(
        cls,
        outcomes: Sequence[tuple[Fraction, frozenset[str], frozenset[str], frozenset[str]]],
        criteria: Sequence[str],
        penalties: Sequence[str],
        invariants: Sequence[str],
    ) -> Truth:
        """``outcomes``: (score, paying, firing, broken) for every admissible outcome."""
        pays = {c: any(c in paying for _, paying, _, _ in outcomes) for c in criteria}
        fails = {c: any(c not in paying for _, paying, _, _ in outcomes) for c in criteria}
        healthy = [c for c in criteria if pays[c] and fails[c]]
        worst: dict[str, Fraction | None] = {}
        for invariant in invariants:
            scores = [score for score, _, _, broken in outcomes if invariant in broken]
            worst[invariant] = max(scores) if scores else None
        return cls(
            exists=bool(outcomes),
            perfect=any(score == 1 for score, _, _, _ in outcomes),
            worst_exploit=worst,
            pays=pays,
            fails=fails,
            implies=frozenset(
                (x, y)
                for x in healthy
                for y in healthy
                if x != y and all(y in paying for _, paying, _, _ in outcomes if x in paying)
            ),
            fires={p: any(p in firing for _, _, firing, _ in outcomes) for p in penalties},
            rests={p: any(p not in firing for _, _, firing, _ in outcomes) for p in penalties},
        )

    def fails_overall(self, threshold: Fraction) -> bool:
        return (
            not self.exists
            or not self.perfect
            or any(s is not None and s >= threshold for s in self.worst_exploit.values())
            or not all(self.pays.values())
            or not all(self.fails.values())
            or not all(self.rests.values())
        )


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


def assert_report_matches(
    report: Report,
    truth: Truth,
    *,
    criteria: Sequence[str],
    penalties: Sequence[str],
    invariants: Sequence[str],
    threshold: Fraction,
) -> None:
    """Every finding in ``report`` must be what ``truth`` says. Assumes finite domains."""
    assert all(f.status is not Status.INCONCLUSIVE for f in report.findings), report.findings

    (outcomes,) = by_check(report, Check.OUTCOMES)
    if not truth.exists:
        assert outcomes.status is Status.FAIL
        assert outcomes.conflict is not None
        assert {f.status for f in report.findings[1:]} == {Status.SKIPPED}
        assert report.verdict is Status.FAIL
        return
    assert outcomes.status is Status.PASS

    (perfect,) = by_check(report, Check.PERFECT_SCORE)
    assert (perfect.status is Status.PASS) == truth.perfect
    assert (perfect.conflict is None) == truth.perfect

    exploits = by_check(report, Check.EXPLOIT)
    if not invariants:
        assert [f.status for f in exploits] == [Status.WARN]
    else:
        for finding, invariant in zip(exploits, invariants, strict=True):
            assert finding.subjects == (invariant,)
            worst = truth.worst_exploit[invariant]
            assert finding.max_score == worst
            if worst is None:
                assert finding.status is Status.PASS
            else:
                assert finding.max_proven is True
                assert (finding.status is Status.FAIL) == (worst >= threshold)

    for finding, criterion in zip(by_check(report, Check.CRITERION), criteria, strict=True):
        healthy = truth.pays[criterion] and truth.fails[criterion]
        assert finding.status is (Status.PASS if healthy else Status.FAIL)

    assert implications(report) == truth.implies

    for finding, penalty in zip(by_check(report, Check.PENALTY), penalties, strict=True):
        if not truth.rests[penalty]:
            assert finding.status is Status.FAIL
        elif not truth.fires[penalty]:
            assert finding.status is Status.WARN
        else:
            assert finding.status is Status.PASS

    expected = Status.FAIL if truth.fails_overall(threshold) else Status.PASS
    assert report.verdict is expected
