"""Untyped syntax tree for condition expressions, and a printer that inverts the parser.

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

LOGICAL_OPS: frozenset[str] = frozenset({"implies", "or", "and"})
COMPARISON_OPS: frozenset[str] = frozenset({"==", "!=", "<", "<=", ">", ">="})
ORDERING_OPS: frozenset[str] = frozenset({"<", "<=", ">", ">="})
BITWISE_OPS: frozenset[str] = frozenset({"|", "^", "&"})
ARITHMETIC_OPS: frozenset[str] = frozenset({"+", "-", "*"})


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

# Printer precedence levels. Kept in step with the parser's binding powers;
# the round-trip property test (print then parse) checks that they agree.
_BINARY_LEVEL: dict[str, int] = {
    "implies": 1,
    "or": 2,
    "and": 3,
    **dict.fromkeys(COMPARISON_OPS, 5),
    "|": 6,
    "^": 7,
    "&": 8,
    "+": 9,
    "-": 9,
    "*": 10,
}
_UNARY_LEVEL: dict[str, int] = {"not": 4, "-": 11}
_ATOM_LEVEL = 12


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


def format_expr(node: Node) -> str:
    """Print ``node`` with the fewest parentheses that parse back to the same tree."""
    return _format(node)[0]


def _format(node: Node) -> tuple[str, int]:
    if isinstance(node, Name):
        return node.id, _ATOM_LEVEL
    if isinstance(node, BoolLiteral):
        return ("true" if node.value else "false"), _ATOM_LEVEL
    if isinstance(node, IntLiteral):
        return str(node.value), _ATOM_LEVEL
    if isinstance(node, DecimalLiteral):
        text = format(node.value, "f")
        return (text if "." in text else f"{text}.0"), _ATOM_LEVEL
    if isinstance(node, Unary):
        level = _UNARY_LEVEL[node.op]
        operand = _wrap(node.operand, level)
        if node.op == "not":
            return f"not {operand}", level
        separator = " " if operand.startswith("-") else ""
        return f"-{separator}{operand}", level
    level = _BINARY_LEVEL[node.op]
    if node.op == "implies":
        left_min, right_min = level + 1, level
    elif node.op in COMPARISON_OPS:
        left_min, right_min = level + 1, level + 1
    else:
        left_min, right_min = level, level + 1
    return f"{_wrap(node.left, left_min)} {node.op} {_wrap(node.right, right_min)}", level


def _wrap(node: Node, minimum: int) -> str:
    text, level = _format(node)
    return f"({text})" if level < minimum else text
