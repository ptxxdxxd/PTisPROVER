"""Brute-force answers to the prover's questions, for rubrics with finite domains.

Lists every outcome and scores it with the reference evaluator. No solver.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

from ptisprover import ir
from ptisprover.evaluate import assess, evaluate
from ptisprover.model import Rubric, Variable
from ptisprover.sorts import BOOL, INT, BitVecSort
from tests.compare import Truth


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


def truth(rubric: Rubric) -> Truth:
    """List every admissible outcome and score it with the reference evaluator."""
    scored = []
    for outcome in outcomes_within_bounds(rubric):
        assessment = assess(rubric, outcome)
        assert assessment.in_bounds
        if assessment.assumptions_hold:
            scored.append(
                (
                    assessment.score,
                    frozenset(assessment.paying),
                    frozenset(assessment.firing),
                    frozenset(assessment.broken),
                )
            )
    return Truth.from_outcomes(
        scored,
        [c.id for c in rubric.criteria],
        [p.id for p in rubric.penalties],
        [i.id for i in rubric.invariants],
    )


# None for a bound, which _listed_domain applies instead.
def _requirement(rubric: Rubric, path: str) -> tuple[ir.Expr, bool] | None:
    if path.startswith("assume["):
        return rubric.assumptions[int(path[7:-1])].expr, True
    if path.startswith("criteria["):
        ident = path[10:-2]
        return next(c.when.expr for c in rubric.criteria if c.id == ident), True
    if path.startswith("penalties["):
        ident = path[11:-2]
        return next(p.when.expr for p in rubric.penalties if p.id == ident), False
    assert path.startswith("variables."), path
    return None


# Only bounds that the conflict lists narrow the domain.
def _listed_domain(variable: Variable, paths: list[str]) -> list[ir.Value]:
    if variable.sort == BOOL:
        return [False, True]
    assert isinstance(variable.sort, BitVecSort), "exact only without int variables"
    low, high = 0, variable.sort.max_value
    if f"variables.{variable.name}.min" in paths:
        assert variable.lower is not None
        low = int(variable.lower)
    if f"variables.{variable.name}.max" in paths:
        assert variable.upper is not None
        high = int(variable.upper)
    return list(range(low, high + 1))


# Brute force over bools and bit-vectors.
def _satisfiable(rubric: Rubric, paths: list[str]) -> bool:
    checks = [r for r in (_requirement(rubric, path) for path in paths) if r is not None]
    names = [v.name for v in rubric.variables]
    for values in itertools.product(*(_listed_domain(v, paths) for v in rubric.variables)):
        outcome = dict(zip(names, values, strict=True))
        if all(holds(expr, outcome) is wanted for expr, wanted in checks):
            return True
    return False


def conflict_is_genuine(rubric: Rubric, paths: list[str]) -> bool:
    """The listed requirements cannot all hold.

    Without int variables this uses only the listed requirements, so a conflict that leaves out a
    bound it depends on is caught. With int variables, which cannot be listed without their
    bounds, it checks the weaker statement that nothing inside all the bounds satisfies them.
    """
    if all(v.sort != INT for v in rubric.variables):
        return not _satisfiable(rubric, paths)
    checks = [r for r in (_requirement(rubric, path) for path in paths) if r is not None]
    return not any(
        all(holds(expr, outcome) is wanted for expr, wanted in checks)
        for outcome in outcomes_within_bounds(rubric)
    )


def conflict_is_irreducible(rubric: Rubric, paths: list[str]) -> bool | None:
    """Dropping any one requirement makes the rest satisfiable.

    None when int variables prevent an exact check.
    """
    if any(v.sort == INT for v in rubric.variables):
        return None
    return all(_satisfiable(rubric, [p for p in paths if p != dropped]) for dropped in paths)
