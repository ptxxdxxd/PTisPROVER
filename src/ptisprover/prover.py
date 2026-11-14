"""The checks run on a rubric.

Each question is one budgeted solver query. A question the solver cannot
decide is reported as undecided, never as passed. Every outcome the solver
produces is replayed through the reference evaluator before it is reported;
if the two disagree, ``InternalError`` is raised.

Severity of an undecided question follows the problem it could be hiding:
if that problem would fail the rubric, the reply is INCONCLUSIVE; if it
would only be a warning, the reply is a warning that says it was not decided.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

import z3

from ptisprover.errors import InternalError
from ptisprover.evaluate import assess
from ptisprover.exact import format_number
from ptisprover.model import Invariant, Rubric
from ptisprover.report import (
    Check,
    Conflict,
    ConflictRequirement,
    Example,
    Finding,
    Report,
    SolverStats,
    Status,
    verdict_of,
)
from ptisprover.smt import (
    DEFAULT_BUDGET,
    Encoding,
    Query,
    Requirement,
    Sat,
    Session,
    Unknown,
    Unsat,
    solver_name,
)

MAX_STRENGTHENING_STEPS = 64

_IRRATIONAL = "the solver's outcome uses an irrational value, which cannot be replayed exactly"


# Only BUDGET can be cured by a larger budget.
class _Why(Enum):
    BUDGET = "budget"
    IRRATIONAL = "irrational"
    STEP_LIMIT = "step limit"


def _undecided(why: _Why, what: str) -> str:
    if why is _Why.BUDGET:
        return f"could not decide within the budget whether {what}"
    if why is _Why.IRRATIONAL:
        return f"could not decide whether {what}: {_IRRATIONAL}"
    return (
        f"could not decide whether {what}: the search stopped after "
        f"{MAX_STRENGTHENING_STEPS} improvements"
    )


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

    def smt2_files(self) -> dict[str, str]:
        """File name -> SMT-LIB2 text for every query, headed by the question and Z3's answer."""
        files = {}
        for number, query in enumerate(self.queries, start=1):
            if query.smt2 is None:
                raise ValueError("prove was not called with keep_smt2=True")
            files[f"query-{number:03}.smt2"] = (
                f"; rubric: {self.report.rubric_id}\n"
                f"; question: {query.label}\n"
                f"; z3: {query.answer.value}\n"
                f"{query.smt2}"
            )
        return files


def prove(rubric: Rubric, *, budget: int = DEFAULT_BUDGET, keep_smt2: bool = False) -> Proof:
    """Run every check on ``rubric`` and return the report with the log of solver queries.

    ``budget`` is Z3 resource units per query. ``keep_smt2`` keeps each query as SMT-LIB2 text,
    for ``Proof.smt2_files``.
    """
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

    def _record(self, finding: Finding) -> Status:
        self.findings.append(finding)
        return finding.status

    def _domain(self) -> list[z3.BoolRef]:
        return [r.formula for r in self.encoding.domain]

    # None when the outcome has an irrational value, which the evaluator cannot score exactly.
    def _replay(self, reply: Sat, question: str) -> Example | None:
        if reply.irrational:
            return None
        assessment = assess(self.rubric, reply.model)
        if not assessment.admissible:
            raise InternalError(
                f"{question}: the solver returned {reply.model}, which the reference "
                "evaluator says is outside the bounds or assumptions"
            )
        if assessment.score != reply.score:
            raise InternalError(
                f"{question}: the solver scores {reply.model} as "
                f"{format_number(reply.score)}, the reference evaluator as "
                f"{format_number(assessment.score)}"
            )
        example = Example(
            assignment=dict(reply.model),
            score=assessment.score,
            paying=assessment.paying,
            firing=assessment.firing,
            broken=assessment.broken,
        )
        self.pool.append(example)
        return example

    # Outcomes found by earlier queries are checked first; the solver is asked only if none
    # of them answers the question.
    def _exists(
        self, question: str, constraints: Sequence[z3.BoolRef], holds: Callable[[Example], bool]
    ) -> bool | _Why:
        if any(holds(example) for example in self.pool):
            return True
        reply = self.session.ask(question, [*self._domain(), *constraints])
        if isinstance(reply, Unsat):
            return False
        if isinstance(reply, Unknown):
            return _Why.BUDGET
        example = self._replay(reply, question)
        if example is None:
            return _Why.IRRATIONAL
        if not holds(example):
            raise InternalError(
                f"{question}: the solver's outcome {example.assignment} "
                "does not have the property asked for"
            )
        return True

    # Deletion: drop each requirement in turn and keep it out if the rest still conflict.
    # The result is irreducible, which is not always the smallest conflict.
    def _minimize(
        self, question: str, core: Sequence[str], candidates: Sequence[Requirement]
    ) -> Conflict:
        by_path = {r.path: r for r in candidates}
        current = [by_path[path] for path in core]
        settled: set[str] = set()
        minimal = True
        while True:
            pending = [r for r in current if r.path not in settled]
            if not pending:
                break
            candidate = pending[0]
            trial = [r for r in current if r.path != candidate.path]
            reply = self.session.ask(f"{question}, without {candidate.path}", tracked=trial)
            if isinstance(reply, Unsat):
                keep = set(reply.core)
                current = [r for r in trial if r.path in keep] if keep else trial
            else:
                settled.add(candidate.path)
                minimal = minimal and isinstance(reply, Sat)
        return Conflict(tuple(ConflictRequirement(r.path, r.requires) for r in current), minimal)

    def _outcomes_exist(self) -> Status:
        question = "does any outcome satisfy the bounds and assumptions"
        domain = self.encoding.domain
        reply = self.session.ask(question, tracked=domain)
        if isinstance(reply, Unsat):
            return self._record(
                Finding(
                    Check.OUTCOMES,
                    Status.FAIL,
                    (),
                    "no outcome satisfies the bounds and assumptions, so every other check "
                    "would be vacuous",
                    conflict=self._minimize(question, reply.core, domain),
                )
            )
        if isinstance(reply, Unknown):
            return self._record(
                Finding(
                    Check.OUTCOMES,
                    Status.INCONCLUSIVE,
                    (),
                    "could not decide within the budget whether any outcome satisfies the bounds "
                    "and assumptions",
                )
            )
        example = self._replay(reply, question)
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
        reply = self.session.ask(question, tracked=requirements)
        if isinstance(reply, Unsat):
            conflict = self._minimize(question, reply.core, requirements)
            self._record(
                Finding(
                    Check.PERFECT_SCORE,
                    Status.FAIL,
                    tuple([r.path for r in conflict.requirements]),
                    "no outcome can score 1, because these requirements cannot all hold",
                    conflict=conflict,
                )
            )
            return
        if isinstance(reply, Unknown):
            self._record(
                Finding(
                    Check.PERFECT_SCORE,
                    Status.INCONCLUSIVE,
                    (),
                    "could not decide within the budget whether a perfect score is reachable",
                )
            )
            return
        example = self._replay(reply, question)
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

    # Iterative strengthening: ask for a strictly higher score until the solver proves
    # none exists. The final unsat answer is the proof that the score is the maximum.
    def _exploit(self, invariant: Invariant) -> None:
        ident = invariant.id
        threshold = self.rubric.exploit_threshold
        broken = z3.Not(self.encoding.invariants[ident], self.encoding.ctx)
        base = [*self._domain(), broken]
        question = f"can '{ident}' be broken"
        reply = self.session.ask(question, base)
        if isinstance(reply, Unsat):
            self._record(
                Finding(
                    Check.EXPLOIT,
                    Status.PASS,
                    (ident,),
                    f"'{ident}' holds for every admissible outcome",
                )
            )
            return
        if isinstance(reply, Unknown):
            self._record(
                Finding(
                    Check.EXPLOIT,
                    Status.INCONCLUSIVE,
                    (ident,),
                    _undecided(_Why.BUDGET, f"'{ident}' can be broken"),
                )
            )
            return
        best = self._exploit_example(reply, question, ident)
        if best is None:
            self._record(Finding(Check.EXPLOIT, Status.INCONCLUSIVE, (ident,), _IRRATIONAL))
            return
        stopped: _Why | None = _Why.STEP_LIMIT  # None once the maximum is proven
        for _ in range(MAX_STRENGTHENING_STEPS):
            question = f"can breaking '{ident}' score above {format_number(best.score)}"
            above = self.encoding.score > self.encoding.rational(best.score)
            reply = self.session.ask(question, [*base, above])
            if not isinstance(reply, Sat):
                stopped = None if isinstance(reply, Unsat) else _Why.BUDGET
                break
            better = self._exploit_example(reply, question, ident)
            if better is None:
                stopped = _Why.IRRATIONAL
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
            if stopped is None:
                message += "; nothing that breaks it scores higher"
        elif stopped is None:
            status = Status.PASS
            message = f"breaking '{ident}' scores at most {score}, below the threshold {limit}"
        else:
            status = Status.INCONCLUSIVE
            message = f"breaking '{ident}' scores at least {score}; " + _undecided(
                stopped, f"it can reach the threshold {limit}"
            )
        self._record(
            Finding(
                Check.EXPLOIT,
                status,
                (ident,),
                message,
                example=best,
                max_score=best.score,
                max_proven=stopped is None,
            )
        )

    def _exploit_example(self, reply: Sat, question: str, ident: str) -> Example | None:
        example = self._replay(reply, question)
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
            elif isinstance(pays, _Why):
                message = _undecided(pays, f"'{ident}' can pay")
                self._record(Finding(Check.CRITERION, Status.INCONCLUSIVE, (ident,), message))
            elif isinstance(fails, _Why):
                message = _undecided(fails, f"'{ident}' can fail")
                self._record(Finding(Check.CRITERION, Status.INCONCLUSIVE, (ident,), message))
            else:
                self._record(
                    Finding(
                        Check.CRITERION, Status.PASS, (ident,), f"'{ident}' can pay and can fail"
                    )
                )
                both_ways.append(ident)
        self._overlaps(both_ways)

    def _overlaps(self, idents: list[str]) -> None:
        encoding, ctx = self.encoding, self.encoding.ctx
        weights = {c.id: c.weight for c in self.rubric.criteria}
        implies: dict[tuple[str, str], bool | _Why] = {}
        for a in idents:
            for b in idents:
                if a == b:
                    continue
                counterexample = self._exists(
                    f"can '{a}' pay while '{b}' does not",
                    [encoding.criteria[a], z3.Not(encoding.criteria[b], ctx)],
                    _pays_without(a, b),
                )
                implies[a, b] = (
                    counterexample if isinstance(counterexample, _Why) else not counterexample
                )
        reported = False
        for i, a in enumerate(idents):
            for b in idents[i + 1 :]:
                forward, backward = implies[a, b], implies[b, a]
                total = format_number(weights[a] + weights[b])
                if forward is True and backward is True:
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
                    if holds is True:
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
                    elif isinstance(holds, _Why):
                        reported = True
                        message = _undecided(holds, f"'{y}' pays whenever '{x}' does")
                        self._record(Finding(Check.OVERLAP, Status.WARN, (x, y), message))
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
            elif isinstance(rests, _Why):
                message = _undecided(rests, f"'{ident}' can stay off")
                self._record(Finding(Check.PENALTY, Status.INCONCLUSIVE, (ident,), message))
            elif fires is False:
                self._record(
                    Finding(
                        Check.PENALTY,
                        Status.WARN,
                        (ident,),
                        f"'{ident}' never fires for any admissible outcome",
                    )
                )
            elif isinstance(fires, _Why):
                message = _undecided(fires, f"'{ident}' can fire")
                self._record(Finding(Check.PENALTY, Status.WARN, (ident,), message))
            else:
                self._record(
                    Finding(
                        Check.PENALTY, Status.PASS, (ident,), f"'{ident}' can fire and can stay off"
                    )
                )
