"""Reference evaluator: computes a rubric's score for one concrete outcome.

Plain Python with exact arithmetic, written independently of the solver
backend. It is the oracle that every counterexample the solver produces is
replayed through, and the brute-force side of the differential tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from rubric_prover import ir
from rubric_prover.model import Rubric
from rubric_prover.sorts import BoolSort, IntSort, RealSort

Assignment = Mapping[str, ir.Value]


def evaluate(expr: ir.Expr, env: Assignment) -> ir.Value:
    """Value of a typed expression under ``env`` (variable name -> value)."""
    if isinstance(expr, ir.Var):
        return env[expr.name]
    if isinstance(expr, ir.Const):
        return expr.value
    if isinstance(expr, ir.ToReal):
        return Fraction(_number(evaluate(expr.arg, env)))
    if isinstance(expr, ir.Neg):
        return -_number(evaluate(expr.arg, env))
    if isinstance(expr, ir.Not):
        return not _truth(evaluate(expr.arg, env))
    if isinstance(expr, ir.Logic):
        left = _truth(evaluate(expr.left, env))
        right = _truth(evaluate(expr.right, env))
        if expr.op == "and":
            return left and right
        if expr.op == "or":
            return left or right
        return (not left) or right
    if isinstance(expr, ir.Arith):
        a = _number(evaluate(expr.left, env))
        b = _number(evaluate(expr.right, env))
        if expr.op == "+":
            return a + b
        if expr.op == "-":
            return a - b
        return a * b
    if isinstance(expr, ir.BitOp):
        x = _bits(evaluate(expr.left, env))
        y = _bits(evaluate(expr.right, env))
        if expr.op == "&":
            return x & y
        if expr.op == "|":
            return x | y
        return x ^ y
    left_value = evaluate(expr.left, env)
    right_value = evaluate(expr.right, env)
    if expr.op == "==":
        return left_value == right_value
    if expr.op == "!=":
        return left_value != right_value
    a, b = _number(left_value), _number(right_value)
    if expr.op == "<":
        return a < b
    if expr.op == "<=":
        return a <= b
    if expr.op == ">":
        return a > b
    return a >= b


@dataclass(frozen=True, slots=True)
class Assessment:
    """Everything the rubric says about one outcome."""

    in_bounds: bool
    assumptions_hold: bool
    paying: tuple[str, ...]
    firing: tuple[str, ...]
    broken: tuple[str, ...]
    score: Fraction

    @property
    def admissible(self) -> bool:
        """True if the outcome is one the rubric considers possible."""
        return self.in_bounds and self.assumptions_hold


def assess(rubric: Rubric, env: Assignment) -> Assessment:
    """Evaluate every part of ``rubric`` for one outcome."""
    checked = validate_assignment(rubric, env)
    in_bounds = all(
        (v.lower is None or _number(checked[v.name]) >= v.lower)
        and (v.upper is None or _number(checked[v.name]) <= v.upper)
        for v in rubric.variables
    )
    assumptions_hold = all(_truth(evaluate(a.expr, checked)) for a in rubric.assumptions)
    paying = tuple(c.id for c in rubric.criteria if _truth(evaluate(c.when.expr, checked)))
    firing = tuple(p.id for p in rubric.penalties if _truth(evaluate(p.when.expr, checked)))
    broken = tuple(i.id for i in rubric.invariants if not _truth(evaluate(i.holds.expr, checked)))
    return Assessment(
        in_bounds=in_bounds,
        assumptions_hold=assumptions_hold,
        paying=paying,
        firing=firing,
        broken=broken,
        score=_score(rubric, set(paying), set(firing)),
    )


def score(rubric: Rubric, env: Assignment) -> Fraction:
    return assess(rubric, env).score


def _score(rubric: Rubric, paying: set[str], firing: set[str]) -> Fraction:
    fired = [p for p in rubric.penalties if p.id in firing]
    if any(p.deduction is None for p in fired):
        return Fraction(0)
    earned = sum((c.weight for c in rubric.criteria if c.id in paying), Fraction(0))
    deducted = sum((p.deduction for p in fired if p.deduction is not None), Fraction(0))
    return max(Fraction(0), earned - deducted)


def validate_assignment(rubric: Rubric, env: Assignment) -> dict[str, ir.Value]:
    """Check that ``env`` gives every variable a value of the right kind.

    Bounds are not enforced here; ``Assessment.in_bounds`` reports them.
    Raises ValueError, because a malformed assignment is a programming error.
    """
    missing = [v.name for v in rubric.variables if v.name not in env]
    if missing:
        raise ValueError(f"no value for: {', '.join(missing)}")
    checked: dict[str, ir.Value] = {}
    for variable in rubric.variables:
        value = env[variable.name]
        sort = variable.sort
        if isinstance(sort, BoolSort):
            ok = isinstance(value, bool)
        elif isinstance(sort, IntSort):
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(sort, RealSort):
            ok = isinstance(value, int | Fraction) and not isinstance(value, bool)
            if ok:
                value = Fraction(value)
        else:
            ok = (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= sort.max_value
            )
        if not ok:
            raise ValueError(f"{variable.name}: {value!r} is not a valid {sort} value")
        checked[variable.name] = value
    return checked


def _truth(value: ir.Value) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"expected a bool, got {value!r}")
    return value


def _number(value: ir.Value) -> int | Fraction:
    if isinstance(value, bool):
        raise TypeError(f"expected a number, got {value!r}")
    return value


def _bits(value: ir.Value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected a bit-vector value, got {value!r}")
    return value
