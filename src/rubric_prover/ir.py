"""Typed expression IR produced by the type checker.

Every node knows its sort and every coercion is explicit (``ToReal``), so the
solver backend and the reference evaluator interpret exactly the same tree and
neither has to know the coercion rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from rubric_prover.sorts import BOOL, REAL, Sort

ArithmeticOp = Literal["+", "-", "*"]
BitwiseOp = Literal["&", "|", "^"]
CompareOp = Literal["==", "!=", "<", "<=", ">", ">="]
LogicalOp = Literal["and", "or", "implies"]

# bool for BOOL, int for INT and bit-vectors, Fraction for REAL.
Value = bool | int | Fraction


@dataclass(frozen=True, slots=True)
class Var:
    name: str
    sort: Sort


@dataclass(frozen=True, slots=True)
class Const:
    sort: Sort
    value: Value


@dataclass(frozen=True, slots=True)
class ToReal:
    arg: Expr

    @property
    def sort(self) -> Sort:
        return REAL


@dataclass(frozen=True, slots=True)
class Neg:
    arg: Expr

    @property
    def sort(self) -> Sort:
        return self.arg.sort


@dataclass(frozen=True, slots=True)
class Arith:
    op: ArithmeticOp
    left: Expr
    right: Expr

    @property
    def sort(self) -> Sort:
        return self.left.sort


@dataclass(frozen=True, slots=True)
class BitOp:
    op: BitwiseOp
    left: Expr
    right: Expr

    @property
    def sort(self) -> Sort:
        return self.left.sort


@dataclass(frozen=True, slots=True)
class Compare:
    op: CompareOp
    left: Expr
    right: Expr

    @property
    def sort(self) -> Sort:
        return BOOL


@dataclass(frozen=True, slots=True)
class Not:
    arg: Expr

    @property
    def sort(self) -> Sort:
        return BOOL


@dataclass(frozen=True, slots=True)
class Logic:
    op: LogicalOp
    left: Expr
    right: Expr

    @property
    def sort(self) -> Sort:
        return BOOL


Expr = Var | Const | ToReal | Neg | Arith | BitOp | Compare | Not | Logic


def free_variables(expr: Expr) -> frozenset[str]:
    """Names of the variables an expression reads."""
    names: set[str] = set()
    stack: list[Expr] = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, Var):
            names.add(node.name)
        elif isinstance(node, ToReal | Neg | Not):
            stack.append(node.arg)
        elif isinstance(node, Arith | BitOp | Compare | Logic):
            stack.append(node.left)
            stack.append(node.right)
    return frozenset(names)
