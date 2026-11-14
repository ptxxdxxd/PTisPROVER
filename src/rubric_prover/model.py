"""In-memory form of a validated rubric. Built by ``loader``; immutable."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from rubric_prover import ir
from rubric_prover.sorts import Sort


@dataclass(frozen=True, slots=True)
class Variable:
    """An observable property of a graded output, with optional inclusive bounds."""

    name: str
    sort: Sort
    lower: int | Fraction | None = None
    upper: int | Fraction | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class Condition:
    """A checked condition, with the text it was written as."""

    source: str
    expr: ir.Expr


@dataclass(frozen=True, slots=True)
class Criterion:
    """Pays ``weight`` when ``when`` holds."""

    id: str
    weight: Fraction
    when: Condition
    description: str = ""


@dataclass(frozen=True, slots=True)
class Penalty:
    """Subtracts ``deduction`` when ``when`` holds, or zeroes the score if ``deduction`` is None."""

    id: str
    when: Condition
    deduction: Fraction | None
    description: str = ""


@dataclass(frozen=True, slots=True)
class Invariant:
    """Something every output that scores well is supposed to satisfy."""

    id: str
    holds: Condition
    description: str = ""


@dataclass(frozen=True, slots=True)
class Rubric:
    """A weighted grading rubric.

    Score of an outcome: 0 if any zeroing penalty fires; otherwise the weights of
    the criteria that hold, minus the deductions of the penalties that fire,
    floored at 0. Weights sum to exactly 1, so the score lies in [0, 1].
    """

    id: str
    variables: tuple[Variable, ...]
    criteria: tuple[Criterion, ...]
    exploit_threshold: Fraction
    assumptions: tuple[Condition, ...] = ()
    penalties: tuple[Penalty, ...] = ()
    invariants: tuple[Invariant, ...] = ()
    description: str = ""
