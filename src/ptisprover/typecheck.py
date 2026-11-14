"""Type checker: untyped syntax -> typed IR.

Coercion rules (the only implicit conversions):

* An int may widen to real. A real never narrows to int.
* An integer literal takes the sort of the operand it meets: int, real, or a
  bit-vector if it fits in the width. Two literals together are int.
* A decimal literal is real; meeting an int operand widens that operand.
* Bit-vectors only meet bit-vectors of the same width, and support ``& | ^``,
  ``==``/``!=`` and unsigned ordering. No arithmetic: it would wrap silently.
* ``and``, ``or``, ``not`` and ``implies`` take bools only.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import NoReturn

from ptisprover import ir, syntax
from ptisprover.errors import RubricError
from ptisprover.exact import decimal_to_fraction
from ptisprover.parser import parse_expression
from ptisprover.sorts import BOOL, INT, REAL, BitVecSort, Sort, is_numeric


@dataclass(frozen=True, slots=True)
class _Literal:
    """A numeric literal whose sort is not fixed until it meets an operand."""

    value: int | Fraction
    is_decimal: bool
    span: syntax.Span

    @property
    def default_sort(self) -> Sort:
        return REAL if self.is_decimal else INT


_Elaborated = ir.Expr | _Literal


_LOGICAL: dict[str, ir.LogicalOp] = {"and": "and", "or": "or", "implies": "implies"}
_BITWISE: dict[str, ir.BitwiseOp] = {"&": "&", "|": "|", "^": "^"}
_ARITHMETIC: dict[str, ir.ArithmeticOp] = {"+": "+", "-": "-", "*": "*"}
_COMPARISON: dict[str, ir.CompareOp] = {
    "==": "==",
    "!=": "!=",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
}


def check_condition(text: str, sorts: Mapping[str, Sort]) -> ir.Expr:
    """Parse and type-check a condition, which must be a bool."""
    return _Checker(text, sorts).condition(parse_expression(text))


class _Checker:
    def __init__(self, text: str, sorts: Mapping[str, Sort]) -> None:
        self._text = text
        self._sorts = sorts

    def _fail(self, message: str, span: syntax.Span) -> NoReturn:
        raise RubricError.single(message, text=self._text, span=span)

    def condition(self, node: syntax.Node) -> ir.Expr:
        expr = self._settle(self._elaborate(node))
        if expr.sort != BOOL:
            self._fail(f"a condition must be true or false, but this is {expr.sort}", node.span)
        return expr

    def _bool(self, node: syntax.Node, context: str) -> ir.Expr:
        expr = self._settle(self._elaborate(node))
        if expr.sort != BOOL:
            self._fail(f"'{context}' needs true/false operands, found {expr.sort}", node.span)
        return expr

    def _settle(self, value: _Elaborated) -> ir.Expr:
        if isinstance(value, _Literal):
            return ir.Const(value.default_sort, _as(value.value, value.default_sort))
        return value

    def _elaborate(self, node: syntax.Node) -> _Elaborated:
        if isinstance(node, syntax.Name):
            return self._variable(node)
        if isinstance(node, syntax.IntLiteral):
            return _Literal(node.value, False, node.span)
        if isinstance(node, syntax.DecimalLiteral):
            return _Literal(decimal_to_fraction(node.value), True, node.span)
        if isinstance(node, syntax.BoolLiteral):
            return ir.Const(BOOL, node.value)
        if isinstance(node, syntax.Unary):
            return self._unary(node)
        return self._binary(node)

    def _variable(self, node: syntax.Name) -> ir.Var:
        sort = self._sorts.get(node.id)
        if sort is None:
            close = difflib.get_close_matches(node.id, list(self._sorts), n=1)
            hint = f"; did you mean '{close[0]}'?" if close else ""
            self._fail(f"unknown variable '{node.id}'{hint}", node.span)
        return ir.Var(node.id, sort)

    def _unary(self, node: syntax.Unary) -> _Elaborated:
        if node.op == "not":
            return ir.Not(self._bool(node.operand, "not"))
        operand = self._elaborate(node.operand)
        if isinstance(operand, _Literal):
            return _Literal(-operand.value, operand.is_decimal, node.span)
        if not is_numeric(operand.sort):
            self._fail(f"'-' needs a number, found {operand.sort}", node.op_span)
        return ir.Neg(operand)

    def _binary(self, node: syntax.Binary) -> ir.Expr:
        op = node.op
        logical = _LOGICAL.get(op)
        if logical is not None:
            return ir.Logic(logical, self._bool(node.left, op), self._bool(node.right, op))
        left = self._elaborate(node.left)
        right = self._elaborate(node.right)
        bitwise = _BITWISE.get(op)
        if bitwise is not None:
            if isinstance(left, _Literal) and isinstance(right, _Literal):
                self._fail(
                    f"'{op}' needs a bit-vector variable on one side to fix the width",
                    node.op_span,
                )
            a, b = self._unify(left, right, node)
            if a.sort == BOOL:
                self._fail(f"'{op}' works on bit-vectors; use 'and'/'or' for bools", node.op_span)
            if not isinstance(a.sort, BitVecSort):
                self._fail(f"'{op}' works on bit-vectors only, found {a.sort}", node.op_span)
            return ir.BitOp(bitwise, a, b)
        a, b = self._unify(left, right, node)
        arithmetic = _ARITHMETIC.get(op)
        if arithmetic is not None:
            if isinstance(a.sort, BitVecSort):
                self._fail(
                    "arithmetic on bit-vectors is not supported (it would wrap around); "
                    "use &, |, ^ or compare them",
                    node.op_span,
                )
            if not is_numeric(a.sort):
                self._fail(f"'{op}' needs numbers, found {a.sort}", node.op_span)
            return ir.Arith(arithmetic, a, b)
        comparison = _COMPARISON[op]
        if comparison in syntax.ORDERING_OPS and a.sort == BOOL:
            self._fail(f"'{op}' cannot order true/false values", node.op_span)
        return ir.Compare(comparison, a, b)

    def _unify(
        self, left: _Elaborated, right: _Elaborated, node: syntax.Binary
    ) -> tuple[ir.Expr, ir.Expr]:
        """Bring both operands to one sort, applying the coercion rules."""
        if isinstance(left, _Literal) and isinstance(right, _Literal):
            sort = REAL if (left.is_decimal or right.is_decimal) else INT
            return ir.Const(sort, _as(left.value, sort)), ir.Const(sort, _as(right.value, sort))
        if isinstance(left, _Literal):
            assert not isinstance(right, _Literal)
            new_right, new_left = self._meet(right, left, node)
            return new_left, new_right
        if isinstance(right, _Literal):
            return self._meet(left, right, node)
        if left.sort == right.sort:
            return left, right
        if left.sort == INT and right.sort == REAL:
            return ir.ToReal(left), right
        if left.sort == REAL and right.sort == INT:
            return left, ir.ToReal(right)
        if isinstance(left.sort, BitVecSort) and isinstance(right.sort, BitVecSort):
            self._fail(
                f"bit-vector widths differ: {left.sort} {node.op} {right.sort}", node.op_span
            )
        self._fail(f"'{node.op}' cannot combine {left.sort} and {right.sort}", node.op_span)

    def _meet(
        self, expr: ir.Expr, literal: _Literal, node: syntax.Binary
    ) -> tuple[ir.Expr, ir.Expr]:
        """Give ``literal`` the sort of ``expr``. Returns (expr, literal) in that order."""
        sort = expr.sort
        if sort == INT:
            if literal.is_decimal:
                return ir.ToReal(expr), ir.Const(REAL, literal.value)
            return expr, ir.Const(INT, literal.value)
        if sort == REAL:
            return expr, ir.Const(REAL, Fraction(literal.value))
        if isinstance(sort, BitVecSort):
            if literal.is_decimal:
                self._fail(f"a {sort} value cannot meet a decimal", literal.span)
            value = literal.value
            assert isinstance(value, int)
            if not 0 <= value <= sort.max_value:
                self._fail(f"{value} does not fit in {sort} (0 to {sort.max_value})", literal.span)
            return expr, ir.Const(sort, value)
        self._fail(f"'{node.op}' cannot combine {sort} and a number", node.op_span)


def _as(value: int | Fraction, sort: Sort) -> int | Fraction:
    if sort == REAL:
        return Fraction(value)
    assert isinstance(value, int)
    return value
