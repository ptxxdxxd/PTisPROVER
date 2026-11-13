"""The checks run on a rubric.

Each question is one budgeted solver query. A question the solver cannot
decide is reported as undecided, never as passed. Every outcome the solver
produces is replayed through the reference evaluator before it is reported;
if the two disagree, ``InternalError`` is raised.

Severity of an undecided question follows the problem it could be hiding:
if that problem would fail the rubric, the result is INCONCLUSIVE; if it
would only be a warning, the result is a warning that says it was not decided.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import z3

from rubric_prover.errors import InternalError
from rubric_prover.evaluate import assess
from rubric_prover.exact import format_number
from rubric_prover.model import Invariant, Rubric
from rubric_prover.report import (
    Check,
    Conflict,
    ConflictItem,
    Example,
    Finding,
    Report,
    SolverStats,
    Status,
    verdict_of,
)
from rubric_prover.smt import (
    DEFAULT_BUDGET,
    Answer,
    Encoding,
    Query,
    Requirement,
    Result,
    Session,
    solver_name,
)

MAX_STRENGTHENING_STEPS = 64

_IRRATIONAL = "the solver's outcome uses an irrational value, which cannot be replayed exactly"


def _pays(criterion: str, *, expected: bool = True) -> Callable[[Example], bool]:
    return lambda example: (criterion in example.paying) is expected


def _pays_without(criterion: str, other: str) -> Callable[[Example], bool]:
    return lambda example: criterion in example.paying and other not in example.paying


def _fires(penalty: str, *, expected: bool = True) -> Callable[[Example], bool]:
    return lambda example: (penalty in example.firing) is expected


@dataclass(frozen=True, slots=True)
class Proof:
    report: Report
    queries: tuple[Query, ...]


def prove(rubric: Rubric, *, budget: int = DEFAULT_BUDGET) -> Report:
    """Run every check on ``rubric``. ``budget`` is Z3 resource units per query."""
    return run_checks(rubric, budget=budget).report


def run_checks(rubric: Rubric, *, budget: int = DEFAULT_BUDGET, keep_smt2: bool = False) -> Proof:
    """Like ``prove``, also returning the log of solver queries (with SMT-LIB2 if asked)."""
    prover = _Prover(rubric, budget, keep_smt2)
    report = prover.run()
    return Proof(report, tuple(prover.session.queries))


class _Prover:
    def __init__(self, rubric: Rubric, budget: int, keep_smt2: bool) -> None:
        self.rubric = rubric
        self.encoding = Encoding(rubric)
        self.session = Session(self.encoding, budget, keep_smt2=keep_smt2)
        self.pool: list[Example] = []  # replayed admissible outcomes, reused as evidence
        self.findings: list[Finding] = []

    def run(self) -> Report:
        if self._outcomes_exist() is Status.FAIL:
            self._skip_the_rest()
        else:
            self._perfect_score()
            self._exploits()
            self._criteria()
            self._penalties()
        findings = tuple(self.findings)
        return Report(
            rubric_id=self.rubric.id,
            verdict=verdict_of(findings),
            findings=findings,
            solver=SolverStats(
                solver=solver_name(),
                budget_per_query=self.session.budget,
                queries=len(self.session.queries),
                work=self.session.work,
            ),
        )

    # ------------------------------------------------------------- helpers

    def _record(self, finding: Finding) -> Status:
        self.findings.append(finding)
        return finding.status

    def _domain(self) -> list[z3.BoolRef]:
        return [r.formula for r in self.encoding.domain]

    def _replay(self, result: Result, question: str) -> Example | None:
        """Score the solver's outcome with the reference evaluator. None if it can't be exact."""
        if result.irrational:
            return None
        assert result.model is not None
        assert result.score is not None
        assessment = assess(self.rubric, result.model)
        if not assessment.admissible:
            raise InternalError(
                f"{question}: the solver returned {result.model}, which the reference "
                "evaluator says is outside the bounds or assumptions"
            )
        if assessment.score != result.score:
            raise InternalError(
                f"{question}: the solver scores {result.model} as "
                f"{format_number(result.score)}, the reference evaluator as "
                f"{format_number(assessment.score)}"
            )
        example = Example(
            assignment=dict(result.model),
            score=assessment.score,
            paying=assessment.paying,
            firing=assessment.firing,
            broken=assessment.broken,
        )
        self.pool.append(example)
        return example

    def _exists(
        self, question: str, constraints: Sequence[z3.BoolRef], holds: Callable[[Example], bool]
    ) -> bool | None:
        """Is there an admissible outcome for which ``holds`` is true? None if undecided."""
        if any(holds(example) for example in self.pool):
            return True
        result = self.session.ask(question, [*self._domain(), *constraints])
        if result.answer is Answer.UNSAT:
            return False
        if result.answer is Answer.UNKNOWN:
            return None
        example = self._replay(result, question)
        if example is None:
            return None
        if not holds(example):
            raise InternalError(f"{question}: the solver's outcome {example.assignment} does not")
        return True

    def _minimize(
        self, question: str, core: Sequence[str], candidates: Sequence[Requirement]
    ) -> Conflict:
        """Shrink an unsat core by deletion until removing any item makes it satisfiable."""
        by_path = {r.path: r for r in candidates}
        current = [by_path[path] for path in core]
        settled: set[str] = set()
        minimal = True
        while True:
            pending = [r for r in current if r.path not in settled]
            if not pending:
                break
            item = pending[0]
            trial = [r for r in current if r.path != item.path]
            result = self.session.ask(f"{question}, without {item.path}", tracked=trial)
            if result.answer is Answer.UNSAT:
                keep = set(result.core)
                current = [r for r in trial if r.path in keep] if keep else trial
            else:
                settled.add(item.path)
                minimal = minimal and result.answer is Answer.SAT
        return Conflict(tuple(ConflictItem(r.path, r.requires) for r in current), minimal)

    # ------------------------------------------------------------- checks

    def _outcomes_exist(self) -> Status:
        question = "does any outcome satisfy the bounds and assumptions"
        domain = self.encoding.domain
        result = self.session.ask(question, tracked=domain)
        if result.answer is Answer.UNSAT:
            return self._record(
                Finding(
                    Check.OUTCOMES,
                    Status.FAIL,
                    (),
                    "no outcome satisfies the bounds and assumptions, so every other check "
                    "would be vacuous",
                    conflict=self._minimize(question, result.core, domain),
                )
            )
        if result.answer is Answer.UNKNOWN:
            return self._record(
                Finding(
                    Check.OUTCOMES,
                    Status.INCONCLUSIVE,
                    (),
                    "could not decide within the budget whether any outcome satisfies the bounds "
                    "and assumptions",
                )
            )
        example = self._replay(result, question)
        if example is None:
            return self._record(Finding(Check.OUTCOMES, Status.INCONCLUSIVE, (), _IRRATIONAL))
        return self._record(
            Finding(
                Check.OUTCOMES,
                Status.PASS,
                (),
                "at least one outcome satisfies the bounds and assumptions",
                example=example,
            )
        )

    def _skip_the_rest(self) -> None:
        reason = "not run: no outcome satisfies the bounds and assumptions"
        rubric = self.rubric
        self._record(Finding(Check.PERFECT_SCORE, Status.SKIPPED, (), reason))
        self._record(
            Finding(Check.EXPLOIT, Status.SKIPPED, tuple([i.id for i in rubric.invariants]), reason)
        )
        self._record(
            Finding(Check.CRITERION, Status.SKIPPED, tuple([c.id for c in rubric.criteria]), reason)
        )
        self._record(
            Finding(Check.OVERLAP, Status.SKIPPED, tuple([c.id for c in rubric.criteria]), reason)
        )
        if rubric.penalties:
            self._record(
                Finding(
                    Check.PENALTY, Status.SKIPPED, tuple([p.id for p in rubric.penalties]), reason
                )
            )

    def _perfect_score(self) -> None:
        question = "can an outcome score 1"
        encoding = self.encoding
        requirements = [
            *encoding.domain,
            *(encoding.criterion_pays(c.id) for c in self.rubric.criteria),
            *(encoding.penalty_stays_off(p.id) for p in self.rubric.penalties),
        ]
        result = self.session.ask(question, tracked=requirements)
        if result.answer is Answer.UNSAT:
            conflict = self._minimize(question, result.core, requirements)
            self._record(
                Finding(
                    Check.PERFECT_SCORE,
                    Status.FAIL,
                    tuple([i.path for i in conflict.items]),
                    "no outcome can score 1, because these requirements cannot all hold",
                    conflict=conflict,
                )
            )
            return
        if result.answer is Answer.UNKNOWN:
            self._record(
                Finding(
                    Check.PERFECT_SCORE,
                    Status.INCONCLUSIVE,
                    (),
                    "could not decide within the budget whether a perfect score is reachable",
                )
            )
            return
        example = self._replay(result, question)
        if example is None:
            self._record(Finding(Check.PERFECT_SCORE, Status.INCONCLUSIVE, (), _IRRATIONAL))
            return
        if example.score != 1:
            raise InternalError(f"{question}: the solver's outcome scores {example.score}")
        self._record(
            Finding(
                Check.PERFECT_SCORE,
                Status.PASS,
                (),
                "a perfect score of 1 is reachable",
                example=example,
            )
        )

    def _exploits(self) -> None:
        if not self.rubric.invariants:
            self._record(
                Finding(
                    Check.EXPLOIT,
                    Status.WARN,
                    (),
                    "no invariants declared, so the reward-hacking check did not run",
                )
            )
            return
        for invariant in self.rubric.invariants:
            self._exploit(invariant)

    def _exploit(self, invariant: Invariant) -> None:
        """Highest score reachable while breaking ``invariant``, by iterative strengthening."""
        ident = invariant.id
        threshold = self.rubric.exploit_threshold
        broken = z3.Not(self.encoding.invariants[ident], self.encoding.ctx)
        base = [*self._domain(), broken]
        question = f"can '{ident}' be broken"
        result = self.session.ask(question, base)
        if result.answer is Answer.UNSAT:
            self._record(
                Finding(
                    Check.EXPLOIT,
                    Status.PASS,
                    (ident,),
                    f"'{ident}' holds for every admissible outcome",
                )
            )
            return
        if result.answer is Answer.UNKNOWN:
            self._record(
                Finding(
                    Check.EXPLOIT,
                    Status.INCONCLUSIVE,
                    (ident,),
                    f"could not decide within the budget whether '{ident}' can be broken",
                )
            )
            return
        best = self._exploit_example(result, question, ident)
        if best is None:
            self._record(Finding(Check.EXPLOIT, Status.INCONCLUSIVE, (ident,), _IRRATIONAL))
            return
        proven = False
        for _ in range(MAX_STRENGTHENING_STEPS):
            question = f"can breaking '{ident}' score above {format_number(best.score)}"
            above = self.encoding.score > self.encoding.rational(best.score)
            result = self.session.ask(question, [*base, above])
            if result.answer is not Answer.SAT:
                proven = result.answer is Answer.UNSAT
                break
            better = self._exploit_example(result, question, ident)
            if better is None:
                break
            if better.score <= best.score:
                raise InternalError(f"{question}: the solver's outcome scores {better.score}")
            best = better
        score, limit = format_number(best.score), format_number(threshold)
        if best.score >= threshold:
            status = Status.FAIL
            message = (
                f"breaking '{ident}' can still score {score}, at or above the threshold {limit}"
            )
            if proven:
                message += "; nothing that breaks it scores higher"
        elif proven:
            status = Status.PASS
            message = f"breaking '{ident}' scores at most {score}, below the threshold {limit}"
        else:
            status = Status.INCONCLUSIVE
            message = (
                f"breaking '{ident}' scores at least {score}; could not decide within the "
                f"budget whether it can reach the threshold {limit}"
            )
        self._record(
            Finding(
                Check.EXPLOIT,
                status,
                (ident,),
                message,
                example=best,
                max_score=best.score,
                max_proven=proven,
            )
        )

    def _exploit_example(self, result: Result, question: str, ident: str) -> Example | None:
        example = self._replay(result, question)
        if example is not None and ident not in example.broken:
            raise InternalError(f"{question}: the solver's outcome does not break '{ident}'")
        return example

    def _criteria(self) -> None:
        encoding, ctx = self.encoding, self.encoding.ctx
        both_ways: list[str] = []
        for criterion in self.rubric.criteria:
            ident = criterion.id
            pays = self._exists(f"can '{ident}' pay", [encoding.criteria[ident]], _pays(ident))
            fails = self._exists(
                f"can '{ident}' fail",
                [z3.Not(encoding.criteria[ident], ctx)],
                _pays(ident, expected=False),
            )
            if pays is False:
                self._record(
                    Finding(Check.CRITERION, Status.FAIL, (ident,), f"'{ident}' can never pay")
                )
            elif fails is False:
                self._record(
                    Finding(
                        Check.CRITERION,
                        Status.FAIL,
                        (ident,),
                        f"'{ident}' pays for every admissible outcome: free reward",
                    )
                )
            elif pays is None or fails is None:
                what = "pay" if pays is None else "fail"
                self._record(
                    Finding(
                        Check.CRITERION,
                        Status.INCONCLUSIVE,
                        (ident,),
                        f"could not decide within the budget whether '{ident}' can {what}",
                    )
                )
            else:
                self._record(
                    Finding(
                        Check.CRITERION, Status.PASS, (ident,), f"'{ident}' can pay and can fail"
                    )
                )
                both_ways.append(ident)
        self._overlaps(both_ways)

    def _overlaps(self, idents: list[str]) -> None:
        """Pairs where one criterion pays whenever another does."""
        encoding, ctx = self.encoding, self.encoding.ctx
        weights = {c.id: c.weight for c in self.rubric.criteria}
        implies: dict[tuple[str, str], bool | None] = {}
        for a in idents:
            for b in idents:
                if a == b:
                    continue
                counterexample = self._exists(
                    f"can '{a}' pay while '{b}' does not",
                    [encoding.criteria[a], z3.Not(encoding.criteria[b], ctx)],
                    _pays_without(a, b),
                )
                implies[a, b] = None if counterexample is None else not counterexample
        reported = False
        for i, a in enumerate(idents):
            for b in idents[i + 1 :]:
                forward, backward = implies[a, b], implies[b, a]
                total = format_number(weights[a] + weights[b])
                if forward and backward:
                    reported = True
                    self._record(
                        Finding(
                            Check.OVERLAP,
                            Status.WARN,
                            (a, b),
                            f"'{a}' and '{b}' pay for exactly the same outcomes: one condition "
                            f"counted twice ({total} in total)",
                        )
                    )
                    continue
                for x, y, holds in ((a, b, forward), (b, a, backward)):
                    if holds:
                        reported = True
                        self._record(
                            Finding(
                                Check.OVERLAP,
                                Status.WARN,
                                (x, y),
                                f"whenever '{x}' pays, '{y}' pays too ({total} together); fine for "
                                "intentional tiers, otherwise it double counts",
                            )
                        )
                    elif holds is None:
                        reported = True
                        self._record(
                            Finding(
                                Check.OVERLAP,
                                Status.WARN,
                                (x, y),
                                f"could not decide within the budget whether '{y}' pays whenever "
                                f"'{x}' does",
                            )
                        )
        if not reported:
            pairs = len(implies)
            self._record(
                Finding(
                    Check.OVERLAP,
                    Status.PASS,
                    tuple(idents),
                    f"no criterion pays whenever another does ({pairs} ordered pairs checked)",
                )
            )

    def _penalties(self) -> None:
        encoding, ctx = self.encoding, self.encoding.ctx
        for penalty in self.rubric.penalties:
            ident = penalty.id
            fires = self._exists(f"can '{ident}' fire", [encoding.penalties[ident]], _fires(ident))
            rests = self._exists(
                f"can '{ident}' stay off",
                [z3.Not(encoding.penalties[ident], ctx)],
                _fires(ident, expected=False),
            )
            if rests is False:
                self._record(
                    Finding(
                        Check.PENALTY,
                        Status.FAIL,
                        (ident,),
                        f"'{ident}' fires for every admissible outcome",
                    )
                )
            elif rests is None:
                self._record(
                    Finding(
                        Check.PENALTY,
                        Status.INCONCLUSIVE,
                        (ident,),
                        f"could not decide within the budget whether '{ident}' can stay off",
                    )
                )
            elif fires is False:
                self._record(
                    Finding(
                        Check.PENALTY,
                        Status.WARN,
                        (ident,),
                        f"'{ident}' never fires for any admissible outcome",
                    )
                )
            elif fires is None:
                self._record(
                    Finding(
                        Check.PENALTY,
                        Status.WARN,
                        (ident,),
                        f"could not decide within the budget whether '{ident}' can fire",
                    )
                )
            else:
                self._record(
                    Finding(
                        Check.PENALTY, Status.PASS, (ident,), f"'{ident}' can fire and can stay off"
                    )
                )
