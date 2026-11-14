"""Pratt parser for condition expressions. See ``syntax`` for the grammar."""

from __future__ import annotations

from decimal import Decimal
from typing import NoReturn

from ptisprover import syntax
from ptisprover.errors import RubricError, position
from ptisprover.lexer import Kind, Token, tokenize

MAX_DEPTH = 200

# token text -> (operator, left binding power, right binding power). Left-associative
# operators bind their right operand one step tighter; 'implies' is the reverse.
_INFIX: dict[str, tuple[syntax.BinaryOp, int, int]] = {
    "implies": ("implies", 2, 1),
    "or": ("or", 3, 4),
    "and": ("and", 5, 6),
    "==": ("==", 9, 10),
    "!=": ("!=", 9, 10),
    "<": ("<", 9, 10),
    "<=": ("<=", 9, 10),
    ">": (">", 9, 10),
    ">=": (">=", 9, 10),
    "|": ("|", 11, 12),
    "^": ("^", 13, 14),
    "&": ("&", 15, 16),
    "+": ("+", 17, 18),
    "-": ("-", 17, 18),
    "*": ("*", 19, 20),
}
# A chain such as "a or b or c" is a left-leaning tree, so it counts one level per operator.
_TOO_DEEP = f"expression has more than {MAX_DEPTH} levels of nested or chained operators"
_NOT_OPERAND_BP = 7
_NEGATION_OPERAND_BP = 21


def parse_expression(text: str) -> syntax.Node:
    """Parse a condition expression. Raises RubricError with the offending position."""
    return _Parser(text).parse()


class _Parser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._tokens = tokenize(text)
        self._index = 0

    def parse(self) -> syntax.Node:
        node = self._expression(0, 1)
        token = self._peek()
        if token.kind is not Kind.END:
            if token.text == ")":
                self._fail("unmatched ')'", token)
            self._fail(f"unexpected {token.describe()} after a complete expression", token)
        if syntax.depth(node) > MAX_DEPTH:
            self._fail_span(_TOO_DEEP, (0, 1))
        return node

    def _peek(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._tokens[self._index]
        if token.kind is not Kind.END:
            self._index += 1
        return token

    def _fail(self, message: str, token: Token) -> NoReturn:
        end = token.end if token.end > token.start else token.start + 1
        self._fail_span(message, (token.start, end))

    def _fail_span(self, message: str, span: syntax.Span) -> NoReturn:
        raise RubricError.single(message, text=self._text, span=span)

    def _expression(self, min_bp: int, depth: int) -> syntax.Node:
        if depth > MAX_DEPTH:
            self._fail(_TOO_DEEP, self._peek())
        left = self._prefix(self._advance(), depth)
        previous_was_comparison = False
        while True:
            token = self._peek()
            if token.kind not in (Kind.OP, Kind.KEYWORD) or token.text not in _INFIX:
                break
            op, left_bp, right_bp = _INFIX[token.text]
            if left_bp < min_bp:
                break
            is_comparison = op in syntax.COMPARISON_OPS
            if is_comparison and previous_was_comparison:
                self._fail("comparisons cannot be chained; join them with 'and'", token)
            self._advance()
            right = self._expression(right_bp, depth + 1)
            left = syntax.Binary(
                op,
                left,
                right,
                span=(left.span[0], right.span[1]),
                op_span=(token.start, token.end),
            )
            previous_was_comparison = is_comparison
        return left

    def _prefix(self, token: Token, depth: int) -> syntax.Node:
        span = (token.start, token.end)
        if token.kind is Kind.NAME:
            return syntax.Name(token.text, span=span)
        if token.kind is Kind.INT:
            return syntax.IntLiteral(int(token.text.replace("_", ""), 0), span=span)
        if token.kind is Kind.DECIMAL:
            return syntax.DecimalLiteral(Decimal(token.text.replace("_", "")), span=span)
        if token.text in ("true", "false") and token.kind is Kind.KEYWORD:
            return syntax.BoolLiteral(token.text == "true", span=span)
        if token.text in ("not", "-") and token.kind in (Kind.KEYWORD, Kind.OP):
            op: syntax.UnaryOp = "not" if token.text == "not" else "-"
            bp = _NOT_OPERAND_BP if op == "not" else _NEGATION_OPERAND_BP
            operand = self._expression(bp, depth + 1)
            return syntax.Unary(
                op,
                operand,
                span=(token.start, operand.span[1]),
                op_span=span,
            )
        if token.text == "(" and token.kind is Kind.OP:
            inner = self._expression(0, depth + 1)
            closing = self._peek()
            if closing.text != ")" or closing.kind is not Kind.OP:
                _, column = position(self._text, token.start)
                self._fail(
                    f"expected ')' to close the '(' at column {column}, found {closing.describe()}",
                    closing,
                )
            self._advance()
            return inner
        self._fail(f"expected an expression, found {token.describe()}", token)
