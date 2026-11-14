from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Sequence
from fractions import Fraction

import pytest
import z3

from ptisprover import ir
from ptisprover import prover as prover_module
from ptisprover.errors import InternalError
from ptisprover.evaluate import Assessment, assess
from ptisprover.loader import load_rubric, loads_toml
from ptisprover.model import Rubric
from ptisprover.prover import prove, run_checks
from ptisprover.report import Check, Finding, Report, Status
from ptisprover.smt import Answer, Query, Requirement, Result, Session
from tests.conftest import ORIGINAL

HEADER = 'id = "t"\nexploit_threshold = 0.85\n'


def rubric(body: str) -> Rubric:
    return loads_toml(HEADER + body)


def only(report: Report, check: Check, subjects: tuple[str, ...] | None = None) -> Finding:
    found = [
        f
        for f in report.findings
        if f.check is check and (subjects is None or f.subjects == subjects)
    ]
    assert len(found) == 1, found
    return found[0]


SIMPLE = """
[variables]
x = { type = "int", min = 0, max = 5 }
[[criteria]]
id = "high"
weight = 0.5
when = "x >= 3"
[[criteria]]
id = "odd_one"
weight = 0.5
when = "x == 1 or x == 5"
"""


# ------------------------------------------------------------------ findings


def test_original_fixture_verdicts() -> None:
    verdicts = {
        path.stem: prove(load_rubric(path)).verdict for path in sorted(ORIGINAL.glob("*.toml"))
    }
    assert verdicts == {
        "contradictory_pricing": Status.FAIL,
        "govcon_quote": Status.PASS,
        "loophole_volume": Status.FAIL,
        "redundant_latency": Status.PASS,
    }


def test_contradiction_is_reported_as_a_minimal_conflict() -> None:
    report = prove(load_rubric(ORIGINAL / "contradictory_pricing.toml"))
    finding = only(report, Check.PERFECT_SCORE)
    assert finding.status is Status.FAIL
    assert finding.conflict is not None
    assert finding.conflict.minimal
    assert [(i.path, i.requires) for i in finding.conflict.items] == [
        ("assume[0]", "margin + discount <= 0.50"),
        ('criteria["high_margin"]', "margin >= 0.25"),
        ('criteria["aggressive_discount"]', "discount >= 0.30"),
    ]


def test_worst_exploits_of_the_govcon_fixture() -> None:
    report = prove(load_rubric(ORIGINAL / "govcon_quote.toml"))
    worst = {
        f.subjects[0]: (f.status, f.max_score, f.max_proven)
        for f in report.findings
        if f.check is Check.EXPLOIT
    }
    # margin < 0.12 loses target_margin (needs 0.18): 0.35 + 0.30 = 0.65.
    # uncapped liability zeroes the score: 0.
    # Breaking the vendor chain either zeroes the score (debarred) or clears bit 0,
    # which loses full_compliance: 0.35 + 0.35 = 0.70.
    assert worst == {
        "margin_floor": (Status.PASS, Fraction(13, 20), True),
        "no_uncapped_exposure": (Status.PASS, Fraction(0), True),
        "clean_vendor_chain": (Status.PASS, Fraction(7, 10), True),
    }


def test_dead_criterion() -> None:
    report = prove(rubric(SIMPLE.replace('"x == 1 or x == 5"', '"x > 10"')))
    assert only(report, Check.CRITERION, ("odd_one",)).message == "'odd_one' can never pay"
    perfect = only(report, Check.PERFECT_SCORE)
    assert perfect.conflict is not None
    assert [i.path for i in perfect.conflict.items] == [
        "variables.x.max",
        'criteria["odd_one"]',
    ]
    assert report.verdict is Status.FAIL


def test_free_criterion() -> None:
    report = prove(rubric(SIMPLE.replace('"x == 1 or x == 5"', '"x >= 0"')))
    finding = only(report, Check.CRITERION, ("odd_one",))
    assert finding.status is Status.FAIL
    assert finding.message == "'odd_one' pays for every admissible outcome: free reward"


def test_equivalent_criteria() -> None:
    report = prove(rubric(SIMPLE.replace('"x == 1 or x == 5"', '"x > 2"')))
    finding = only(report, Check.OVERLAP)
    assert (finding.status, finding.subjects) == (Status.WARN, ("high", "odd_one"))
    assert finding.message == (
        "'high' and 'odd_one' pay for exactly the same outcomes: one condition counted twice "
        "(1 in total)"
    )
    assert report.verdict is Status.PASS


def test_one_way_implication_is_a_warning() -> None:
    report = prove(load_rubric(ORIGINAL / "redundant_latency.toml"))
    finding = only(report, Check.OVERLAP)
    assert finding.subjects == ("fast_response", "standard_response")
    assert finding.status is Status.WARN
    assert report.verdict is Status.PASS


def test_independent_criteria_pass_the_overlap_check() -> None:
    finding = only(prove(rubric(SIMPLE)), Check.OVERLAP)
    assert finding.status is Status.PASS
    assert finding.message == "no criterion pays whenever another does (2 ordered pairs checked)"


@pytest.mark.parametrize(
    ("when", "status", "message"),
    [
        ("x > 10", Status.WARN, "'p' never fires for any admissible outcome"),
        ("x >= 0", Status.FAIL, "'p' fires for every admissible outcome"),
        ("x == 2", Status.PASS, "'p' can fire and can stay off"),
    ],
)
def test_penalty_ranges(when: str, status: Status, message: str) -> None:
    report = prove(rubric(SIMPLE + f'[[penalties]]\nid = "p"\ndeduct = 0.1\nwhen = "{when}"\n'))
    finding = only(report, Check.PENALTY)
    assert (finding.status, finding.message) == (status, message)


def test_empty_domain_fails_and_skips_everything_else() -> None:
    body = SIMPLE.replace("[variables]", 'assume = ["x > 5"]\n[variables]')
    body += '[[penalties]]\nid = "p"\nzero = true\nwhen = "x == 0"\n'
    report = prove(rubric(body))
    outcomes = report.findings[0]
    assert outcomes.status is Status.FAIL
    assert outcomes.conflict is not None
    assert [i.path for i in outcomes.conflict.items] == ["variables.x.max", "assume[0]"]
    assert [f.status for f in report.findings[1:]] == [Status.SKIPPED] * 5
    assert report.verdict is Status.FAIL


def test_missing_invariants_are_a_warning_not_a_pass() -> None:
    finding = only(prove(rubric(SIMPLE)), Check.EXPLOIT)
    assert finding.status is Status.WARN
    assert finding.message == "no invariants declared, so the reward-hacking check did not run"


def test_invariant_implied_by_the_bounds_cannot_be_broken() -> None:
    report = prove(rubric(SIMPLE + '[[invariants]]\nid = "i"\nholds = "x <= 5"\n'))
    finding = only(report, Check.EXPLOIT)
    assert finding.status is Status.PASS
    assert finding.message == "'i' holds for every admissible outcome"
    assert finding.max_score is None


def test_irrational_outcomes_are_not_replayed_and_not_passed() -> None:
    report = prove(
        loads_toml(
            HEADER
            + """
            [variables]
            r = { type = "real", min = 0, max = 2 }
            [[criteria]]
            id = "root_two"
            weight = 1
            when = "r * r == 2"
            [[invariants]]
            id = "never_root_two"
            holds = "r * r != 2"
            """
        )
    )
    irrational = "the solver's outcome uses an irrational value, which cannot be replayed exactly"
    assert only(report, Check.PERFECT_SCORE).message == irrational
    assert only(report, Check.EXPLOIT).message == irrational
    assert only(report, Check.CRITERION).status is Status.INCONCLUSIVE
    assert report.verdict is Status.INCONCLUSIVE


def test_irrational_domain_is_inconclusive() -> None:
    body = SIMPLE.replace(
        'x = { type = "int", min = 0, max = 5 }',
        'x = { type = "int", min = 0, max = 5 }\nr = "real"',
    )
    body = body.replace("[variables]", 'assume = ["r * r == 2"]\n[variables]')
    finding = prove(rubric(body)).findings[0]
    assert (finding.check, finding.status) == (Check.OUTCOMES, Status.INCONCLUSIVE)


# ------------------------------------------------------------------ undecided


@pytest.fixture
def undecided(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Make every query whose label matches a pattern come back UNKNOWN."""

    def install(pattern: str) -> None:
        real_ask = Session.ask

        def ask(
            self: Session,
            label: str,
            constraints: Sequence[z3.BoolRef] = (),
            tracked: Sequence[Requirement] = (),
        ) -> Result:
            if re.search(pattern, label):
                self.queries.append(Query(label, Answer.UNKNOWN, 0))
                return Result(Answer.UNKNOWN)
            return real_ask(self, label, constraints, tracked)

        monkeypatch.setattr(Session, "ask", ask)

    return install


LOOPHOLE = ORIGINAL / "loophole_volume.toml"


FREE = SIMPLE.replace('"x == 1 or x == 5"', '"x >= 0"')
EQUIVALENT = SIMPLE.replace('"x == 1 or x == 5"', '"x > 2"')
PENALTY_ALWAYS = SIMPLE + '[[penalties]]\nid = "p"\ndeduct = 0.1\nwhen = "x >= 0"\n'
PENALTY_NEVER = SIMPLE + '[[penalties]]\nid = "p"\ndeduct = 0.1\nwhen = "x > 10"\n'
WITH_INVARIANT = SIMPLE + '[[invariants]]\nid = "i"\nholds = "x != 4"\n'


# Each case asks a question no outcome found earlier can answer, so the query is
# really made and really comes back UNKNOWN.
@pytest.mark.parametrize(
    ("body", "pattern", "check", "status", "message"),
    [
        (
            SIMPLE,
            "^does any outcome",
            Check.OUTCOMES,
            Status.INCONCLUSIVE,
            "could not decide within the budget whether any outcome satisfies the bounds and "
            "assumptions",
        ),
        (
            SIMPLE,
            "^can an outcome score 1$",
            Check.PERFECT_SCORE,
            Status.INCONCLUSIVE,
            "could not decide within the budget whether a perfect score is reachable",
        ),
        (
            WITH_INVARIANT,
            "^can 'i' be broken",
            Check.EXPLOIT,
            Status.INCONCLUSIVE,
            "could not decide within the budget whether 'i' can be broken",
        ),
        (
            FREE,
            "^can 'odd_one' fail",
            Check.CRITERION,
            Status.INCONCLUSIVE,
            "could not decide within the budget whether 'odd_one' can fail",
        ),
        (
            EQUIVALENT,
            "^can 'high' pay while",
            Check.OVERLAP,
            Status.WARN,
            "could not decide within the budget whether 'odd_one' pays whenever 'high' does",
        ),
        (
            PENALTY_ALWAYS,
            "^can 'p' stay off",
            Check.PENALTY,
            Status.INCONCLUSIVE,
            "could not decide within the budget whether 'p' can stay off",
        ),
        (
            PENALTY_NEVER,
            "^can 'p' fire",
            Check.PENALTY,
            Status.WARN,
            "could not decide within the budget whether 'p' can fire",
        ),
    ],
)
def test_undecided_questions_are_never_passed(
    undecided: Callable[[str], None],
    body: str,
    pattern: str,
    check: Check,
    status: Status,
    message: str,
) -> None:
    undecided(pattern)
    report = prove(rubric(body))
    matching = [f for f in report.findings if f.check is check and f.message == message]
    assert [f.status for f in matching] == [status]
    if status is Status.INCONCLUSIVE:
        assert report.verdict is not Status.PASS


def test_undecided_minimisation_is_marked_not_minimal(undecided: Callable[[str], None]) -> None:
    undecided(", without ")
    finding = only(prove(load_rubric(ORIGINAL / "contradictory_pricing.toml")), Check.PERFECT_SCORE)
    assert finding.conflict is not None
    assert not finding.conflict.minimal


def test_unproven_maximum_below_threshold_is_inconclusive(
    undecided: Callable[[str], None],
) -> None:
    undecided("^can breaking 'margin_floor' score above")
    report = prove(load_rubric(ORIGINAL / "govcon_quote.toml"))
    finding = only(report, Check.EXPLOIT, ("margin_floor",))
    assert finding.status is Status.INCONCLUSIVE
    assert finding.max_proven is False
    assert finding.message.startswith("breaking 'margin_floor' scores at least ")
    assert report.verdict is Status.INCONCLUSIVE


def test_unproven_maximum_at_or_above_threshold_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prover_module, "MAX_STRENGTHENING_STEPS", 0)
    finding = only(prove(load_rubric(LOOPHOLE)), Check.EXPLOIT, ("positive_margin",))
    assert finding.status is Status.FAIL
    assert finding.max_proven is False
    assert finding.message == (
        "breaking 'positive_margin' can still score 0.9, at or above the threshold 0.85"
    )


# ------------------------------------------------------------------ guard rails


def corrupt_evaluator(
    monkeypatch: pytest.MonkeyPatch, change: Callable[[Assessment], Assessment]
) -> None:
    monkeypatch.setattr("ptisprover.prover.assess", lambda rubric, env: change(assess(rubric, env)))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda a: dataclasses.replace(a, score=a.score + Fraction(1, 100)),
            "the reference evaluator as",
        ),
        (lambda a: dataclasses.replace(a, in_bounds=False), "outside the bounds or assumptions"),
        (
            lambda a: dataclasses.replace(a, assumptions_hold=False),
            "outside the bounds or assumptions",
        ),
        (lambda a: dataclasses.replace(a, broken=()), "does not break 'positive_margin'"),
        (lambda a: dataclasses.replace(a, firing=()), "can 'weak_risk_deduction' fire"),
    ],
)
def test_disagreement_with_the_reference_evaluator_is_an_internal_error(
    monkeypatch: pytest.MonkeyPatch, change: Callable[[Assessment], Assessment], message: str
) -> None:
    corrupt_evaluator(monkeypatch, change)
    with pytest.raises(InternalError, match=re.escape(message)):
        prove(load_rubric(LOOPHOLE))


def fake_answer(
    monkeypatch: pytest.MonkeyPatch, pattern: str, model: dict[str, ir.Value], score: Fraction
) -> None:
    real_ask = Session.ask

    def ask(
        self: Session,
        label: str,
        constraints: Sequence[z3.BoolRef] = (),
        tracked: Sequence[Requirement] = (),
    ) -> Result:
        if re.search(pattern, label):
            return Result(Answer.SAT, model=model, score=score)
        return real_ask(self, label, constraints, tracked)

    monkeypatch.setattr(Session, "ask", ask)


def test_a_perfect_score_claim_that_is_not_perfect_is_an_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_answer(monkeypatch, "^can an outcome score 1$", {"x": 3}, Fraction(1, 2))
    with pytest.raises(InternalError, match="scores 1/2"):
        prove(rubric(SIMPLE))


def test_a_strengthening_step_that_does_not_improve_is_an_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worst: dict[str, ir.Value] = {
        "deal_volume_usd": 750000,
        "quote_latency_ms": 100,
        "net_margin": Fraction(-3, 25),
        "uncapped_liability": 1,
    }
    fake_answer(monkeypatch, "^can breaking 'positive_margin' score above", worst, Fraction(9, 10))
    with pytest.raises(InternalError, match="scores 9/10"):
        prove(load_rubric(LOOPHOLE))


def test_an_irrational_strengthening_step_stops_without_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_ask = Session.ask

    def ask(
        self: Session,
        label: str,
        constraints: Sequence[z3.BoolRef] = (),
        tracked: Sequence[Requirement] = (),
    ) -> Result:
        if label.startswith("can breaking 'margin_floor' score above"):
            return Result(Answer.SAT, model={}, score=Fraction(1), irrational=True)
        return real_ask(self, label, constraints, tracked)

    monkeypatch.setattr(Session, "ask", ask)
    finding = only(
        prove(load_rubric(ORIGINAL / "govcon_quote.toml")), Check.EXPLOIT, ("margin_floor",)
    )
    assert (finding.status, finding.max_proven) == (Status.INCONCLUSIVE, False)


# ------------------------------------------------------------------ bookkeeping


def test_query_log_and_solver_stats() -> None:
    proof = run_checks(load_rubric(LOOPHOLE), budget=1_000_000, keep_smt2=True)
    stats = proof.report.solver
    assert stats.solver.startswith("z3 ")
    assert stats.budget_per_query == 1_000_000
    assert stats.queries == len(proof.queries)
    assert stats.work == sum(q.work for q in proof.queries)
    assert proof.queries[0].label == "does any outcome satisfy the bounds and assumptions"
    assert all(q.smt2 for q in proof.queries)


def test_findings_follow_declaration_order() -> None:
    report = prove(load_rubric(ORIGINAL / "govcon_quote.toml"))
    assert [f.check for f in report.findings] == [
        Check.OUTCOMES,
        Check.PERFECT_SCORE,
        *[Check.EXPLOIT] * 3,
        *[Check.CRITERION] * 3,
        Check.OVERLAP,
        *[Check.PENALTY] * 2,
    ]
    assert [f.subjects for f in report.findings if f.check is Check.CRITERION] == [
        ("target_margin",),
        ("fast_delivery",),
        ("full_compliance",),
    ]


def test_minimisation_shrinks_a_bloated_conflict_to_the_real_one() -> None:
    """Z3's first core is often minimal already; force the shrinking path with a padded one."""
    rubric = load_rubric(ORIGINAL / "contradictory_pricing.toml")
    prover = prover_module._Prover(rubric, budget=1_000_000, keep_smt2=False)
    encoding = prover.encoding
    requirements = [*encoding.domain, *(encoding.criterion_pays(c.id) for c in rubric.criteria)]
    conflict = prover._minimize("padded", [r.path for r in requirements], requirements)
    assert conflict.minimal
    assert [i.path for i in conflict.items] == [
        "assume[0]",
        'criteria["high_margin"]',
        'criteria["aggressive_discount"]',
    ]


def test_an_exploit_exactly_at_the_threshold_fails() -> None:
    body = SIMPLE.replace('"x == 1 or x == 5"', '"x == 5"')
    body += '[[invariants]]\nid = "not_three"\nholds = "x != 3"\n'
    report = prove(loads_toml(HEADER.replace("0.85", "0.5") + body))
    finding = only(report, Check.EXPLOIT)
    # x = 3 is the only way to break the invariant: 'high' pays 0.5, 'odd_one' does not.
    assert (finding.status, finding.max_score, finding.max_proven) == (
        Status.FAIL,
        Fraction(1, 2),
        True,
    )


def test_bit_vector_ordering_is_unsigned() -> None:
    """Read as signed 8-bit, nothing is above 127, so 'top_half' could never pay."""
    report = prove(
        rubric(
            '[variables]\nlevel = "bv8"\n'
            '[[criteria]]\nid = "top_half"\nweight = 1\nwhen = "127 < level"\n'
        )
    )
    assert only(report, Check.CRITERION).status is Status.PASS
    example = only(report, Check.PERFECT_SCORE).example
    assert example is not None
    assert example.assignment["level"] in range(128, 256)


@pytest.mark.parametrize(
    ("bounds", "condition"),
    [
        # Read as signed, 'max = 200' would be -56 and allow only 128..200.
        ("max = 200", "level < 100"),
        # Read as signed, 'min = 100' would allow only 100..127.
        ("min = 100", "level > 127"),
    ],
    ids=["max", "min"],
)
def test_bit_vector_bounds_are_unsigned(bounds: str, condition: str) -> None:
    report = prove(
        rubric(
            f'[variables]\nlevel = {{ type = "bv8", {bounds} }}\n'
            f'[[criteria]]\nid = "c"\nweight = 1\nwhen = "{condition}"\n'
        )
    )
    assert only(report, Check.CRITERION).status is Status.PASS


def test_the_step_limit_is_named_when_it_stops_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prover_module, "MAX_STRENGTHENING_STEPS", 0)
    report = prove(load_rubric(ORIGINAL / "govcon_quote.toml"))
    finding = only(report, Check.EXPLOIT, ("no_uncapped_exposure",))
    # Uncapped liability zeroes the score, so the first outcome found scores 0.
    assert finding.status is Status.INCONCLUSIVE
    assert finding.message == (
        "breaking 'no_uncapped_exposure' scores at least 0; could not decide whether it can "
        "reach the threshold 0.85: the search stopped after 0 improvements"
    )


def test_an_irrational_outcome_is_not_blamed_on_the_budget() -> None:
    report = prove(
        rubric(
            '[variables]\nr = { type = "real", min = 0, max = 2 }\n'
            '[[criteria]]\nid = "root_two"\nweight = 1\nwhen = "r * r == 2"\n'
        )
    )
    message = only(report, Check.CRITERION).message
    assert message == (
        "could not decide whether 'root_two' can pay: the solver's outcome uses an irrational "
        "value, which cannot be replayed exactly"
    )


def test_a_long_flat_chain_is_checked() -> None:
    chain = " or ".join(f"x == {i}" for i in range(150))
    report = prove(
        rubric(
            '[variables]\nx = { type = "int", min = 0, max = 500 }\n'
            f'[[criteria]]\nid = "c"\nweight = 1\nwhen = "{chain}"\n'
        )
    )
    assert only(report, Check.CRITERION).status is Status.PASS
