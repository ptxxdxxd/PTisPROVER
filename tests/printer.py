"""Prints a syntax tree as source text with the fewest parentheses that parse back to it.

Test-only: the round-trip property (print, then parse, gives the same tree) checks the
parser's precedence and associativity from the other side.
"""

from __future__ import annotations

from rubric_prover.syntax import (
    COMPARISON_OPS,
    BoolLiteral,
    DecimalLiteral,
    IntLiteral,
    Name,
    Node,
    Unary,
)

# Precedence levels, written independently of the parser's binding powers.
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
