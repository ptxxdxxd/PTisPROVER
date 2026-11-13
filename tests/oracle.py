"""Brute-force answers to the prover's questions, for rubrics with finite domains.

Lists every outcome and scores it with the reference evaluator. No solver.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from rubric_prover import ir
from rubric_prover.evaluate import Assessment, assess, evaluate
from rubric_prover.model import Rubric, Variable
from rubric_prover.sorts import BOOL, INT, BitVecSort


def domain(variable: Variable) -> list[ir.Value]:
    if variable.sort == BOOL:
        return [False, True]
    if isinstance(variable.sort, BitVecSort):
        low, high = 0, variable.sort.max_value
    else:
        assert variable.sort == INT, "brute force needs finite domains"
        assert variable.lower is not None
        assert variable.upper is not None
        low, high = int(variable.lower), int(variable.upper)
    if variable.lower is not None:
        low = max(low, int(variable.lower))
    if variable.upper is not None:
        high = min(high, int(variable.upper))
    return list(range(low, high + 1))


def outcomes_within_bounds(rubric: Rubric) -> Iterator[dict[str, ir.Value]]:
    names = [v.name for v in rubric.variables]
    for values in itertools.product(*(domain(v) for v in rubric.variables)):
        yield dict(zip(names, values, strict=True))


def holds(expr: ir.Expr, outcome: dict[str, ir.Value]) -> bool:
    value = evaluate(expr, outcome)
    assert isinstance(value, bool)
    return value


@dataclass(frozen=True)
class Expected:
    exists: bool
    perfect: bool
    worst_exploit: dict[str, Fraction | None]  # None: the invariant cannot be broken
    pays: dict[str, bool]
    fails: dict[str, bool]
    implies: frozenset[tuple[str, str]]  # among criteria that can both pay and fail
    fires: dict[str, bool]
    rests: dict[str, bool]

    def verdict_fails(self, threshold: Fraction) -> bool:
        return (
            not self.exists
            or not self.perfect
            or any(s is not None and s >= threshold for s in self.worst_exploit.values())
            or not all(self.pays.values())
            or not all(self.fails.values())
            or not all(self.rests.values())
        )


def expected(rubric: Rubric) -> Expected:
    admissible: list[tuple[dict[str, ir.Value], Assessment]] = []
    for outcome in outcomes_within_bounds(rubric):
        assessment = assess(rubric, outcome)
        assert assessment.in_bounds
        if assessment.assumptions_hold:
            admissible.append((outcome, assessment))
    scored = [a for _, a in admissible]
    criteria = [c.id for c in rubric.criteria]
    pays = {c: any(c in a.paying for a in scored) for c in criteria}
    fails = {c: any(c not in a.paying for a in scored) for c in criteria}
    both = [c for c in criteria if pays[c] and fails[c]]
    implies = frozenset(
        (x, y)
        for x in both
        for y in both
        if x != y and all(y in a.paying for a in scored if x in a.paying)
    )
    worst: dict[str, Fraction | None] = {}
    for invariant in rubric.invariants:
        scores = [a.score for a in scored if invariant.id in a.broken]
        worst[invariant.id] = max(scores) if scores else None
    return Expected(
        exists=bool(admissible),
        perfect=any(a.score == 1 for a in scored),
        worst_exploit=worst,
        pays=pays,
        fails=fails,
        implies=implies,
        fires={p.id: any(p.id in a.firing for a in scored) for p in rubric.penalties},
        rests={p.id: any(p.id not in a.firing for a in scored) for p in rubric.penalties},
    )


def conflict_is_unsatisfiable(rubric: Rubric, paths: list[str]) -> bool:
    """No outcome within the bounds meets every listed requirement."""
    checks = []
    for path in paths:
        if path.startswith("assume["):
            checks.append((rubric.assumptions[int(path[7:-1])].expr, True))
        elif path.startswith("criteria["):
            ident = path[10:-2]
            checks.append((next(c.when.expr for c in rubric.criteria if c.id == ident), True))
        elif path.startswith("penalties["):
            ident = path[11:-2]
            checks.append((next(p.when.expr for p in rubric.penalties if p.id == ident), False))
        else:
            assert path.startswith("variables."), path  # enforced by the enumeration
    return not any(
        all(holds(expr, outcome) is wanted for expr, wanted in checks)
        for outcome in outcomes_within_bounds(rubric)
    )
