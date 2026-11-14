"""Untyped syntax tree for condition expressions.

Precedence, loosest first (Python's order, so ``mask & 7 == 7`` means
``(mask & 7) == 7``):

    implies (right-associative)
    or
    and
    not
    == != < <= > >=   (cannot be chained)
    |
    ^
    &
    + -
    *
    unary -
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Span = tuple[int, int]
NO_SPAN: Span = (0, 0)

UnaryOp = Literal["-", "not"]
BinaryOp = Literal[
    "implies", "or", "and", "==", "!=", "<", "<=", ">", ">=", "|", "^", "&", "+", "-", "*"
]

COMPARISON_OPS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})
ORDERING_OPS: frozenset[str] = frozenset({"<", "<=", ">", ">="})


@dataclass(frozen=True, slots=True)
class Name:
    id: str
    span: Span = field(default=NO_SPAN, compare=False)


@dataclass(frozen=True, slots=True)
class IntLiteral:
    value: int
    span: Span = field(default=NO_SPAN, compare=False)


@dataclass(frozen=True, slots=True)
class DecimalLiteral:
    value: Decimal
    span: Span = field(default=NO_SPAN, compare=False)


@dataclass(frozen=True, slots=True)
class BoolLiteral:
    value: bool
    span: Span = field(default=NO_SPAN, compare=False)


@dataclass(frozen=True, slots=True)
class Unary:
    op: UnaryOp
    operand: Node
    span: Span = field(default=NO_SPAN, compare=False)
    op_span: Span = field(default=NO_SPAN, compare=False)


@dataclass(frozen=True, slots=True)
class Binary:
    op: BinaryOp
    left: Node
    right: Node
    span: Span = field(default=NO_SPAN, compare=False)
    op_span: Span = field(default=NO_SPAN, compare=False)


Node = Name | IntLiteral | DecimalLiteral | BoolLiteral | Unary | Binary


def depth(node: Node) -> int:
    """Height of the tree, computed without recursion."""
    deepest = 0
    stack: list[tuple[Node, int]] = [(node, 1)]
    while stack:
        current, level = stack.pop()
        deepest = max(deepest, level)
        if isinstance(current, Unary):
            stack.append((current.operand, level + 1))
        elif isinstance(current, Binary):
            stack.append((current.left, level + 1))
            stack.append((current.right, level + 1))
    return deepest
