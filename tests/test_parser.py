from __future__ import annotations

import contextlib
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ptisprover import syntax
from ptisprover.errors import RubricError
from ptisprover.parser import MAX_DEPTH, parse_expression
from tests.printer import format_expr
from tests.strategies import syntax_trees, token_soup


def sexpr(node: syntax.Node) -> str:
    """Fully parenthesized prefix form, so expected trees are easy to read."""
    if isinstance(node, syntax.Name):
        return node.id
    if isinstance(node, syntax.BoolLiteral):
        return "true" if node.value else "false"
    if isinstance(node, syntax.IntLiteral | syntax.DecimalLiteral):
        return str(node.value)
    if isinstance(node, syntax.Unary):
        return f"({node.op} {sexpr(node.operand)})"
    return f"({node.op} {sexpr(node.left)} {sexpr(node.right)})"


@pytest.mark.parametrize(
    ("text", "tree"),
    [
        ("a or b and c", "(or a (and b c))"),
        ("a and b or c", "(or (and a b) c)"),
        ("a implies b implies c", "(implies a (implies b c))"),
        ("a or b implies c", "(implies (or a b) c)"),
        ("a implies b or c", "(implies a (or b c))"),
        ("not a and b", "(and (not a) b)"),
        ("not a == b", "(not (== a b))"),
        ("not not a", "(not (not a))"),
        ("mask & 7 == 7", "(== (& mask 7) 7)"),
        ("a | b ^ c & d", "(| a (^ b (& c d)))"),
        ("a - b - c", "(- (- a b) c)"),
        ("a + b * c", "(+ a (* b c))"),
        ("-a * b", "(* (- a) b)"),
        ("- -a", "(- (- a))"),
        ("x >= -0.5", "(>= x (- 0.5))"),
        ("(a or b) and c", "(and (or a b) c)"),
        ("a == (b == c)", "(== a (== b c))"),
        ("0x1F + 0b101 + 1_000", "(+ (+ 31 5) 1000)"),
        ("true and false", "(and true false)"),
        ("a\n  and\n  b", "(and a b)"),
    ],
)
def test_precedence_and_associativity(text: str, tree: str) -> None:
    assert sexpr(parse_expression(text)) == tree


def test_spans_cover_the_source() -> None:
    node = parse_expression("x >= 10 and y")
    assert isinstance(node, syntax.Binary)
    assert node.span == (0, 13)
    assert node.op_span == (8, 11)
    assert node.left.span == (0, 7)


@pytest.mark.parametrize(
    ("text", "message", "line", "column"),
    [
        ("", "expected an expression, found end of input", 1, 1),
        ("a and", "expected an expression, found end of input", 1, 6),
        ("not", "expected an expression, found end of input", 1, 4),
        ("and a", "expected an expression, found 'and'", 1, 1),
        ("a * * b", "expected an expression, found '*'", 1, 5),
        ("a b", "unexpected 'b' after a complete expression", 1, 3),
        ("a)", "unmatched ')'", 1, 2),
        ("(a", "expected ')' to close the '(' at column 1, found end of input", 1, 3),
        ("x > (a b)", "expected ')' to close the '(' at column 5, found 'b'", 1, 8),
        ("a < b < c", "comparisons cannot be chained; join them with 'and'", 1, 7),
        ("a == b != c", "comparisons cannot be chained; join them with 'and'", 1, 8),
        ("a and\n  (b or", "expected an expression, found end of input", 2, 8),
    ],
)
def test_syntax_errors_say_what_and_where(text: str, message: str, line: int, column: int) -> None:
    with pytest.raises(RubricError) as exc:
        parse_expression(text)
    (diagnostic,) = exc.value.diagnostics
    assert (diagnostic.message, diagnostic.line, diagnostic.column) == (message, line, column)


NESTED_TOO_DEEP = f"expression has more than {MAX_DEPTH} levels of nested or chained operators"


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("(" * (MAX_DEPTH - 1) + "x" + ")" * (MAX_DEPTH - 1), True),
        ("(" * MAX_DEPTH + "x" + ")" * MAX_DEPTH, False),
        ("-" * (MAX_DEPTH - 1) + "x", True),
        ("-" * MAX_DEPTH + "x", False),
        (" + ".join(["x"] * MAX_DEPTH), True),
        (" + ".join(["x"] * (MAX_DEPTH + 1)), False),
    ],
    ids=["parens-ok", "parens-deep", "minus-ok", "minus-deep", "chain-ok", "chain-deep"],
)
def test_nesting_limit(text: str, ok: bool) -> None:
    if ok:
        parse_expression(text)
        return
    with pytest.raises(RubricError) as exc:
        parse_expression(text)
    assert exc.value.diagnostics[0].message == NESTED_TOO_DEEP


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        ("((a)) and ((b))", "a and b"),
        ("(a and b) and c", "a and b and c"),
        ("a and (b and c)", "a and (b and c)"),
        ("(a implies b) implies c", "(a implies b) implies c"),
        ("not (a and b)", "not (a and b)"),
        ("(not a) == b", "(not a) == b"),
        ("-(a * b)", "-(a * b)"),
        ("x >= 1.50", "x >= 1.50"),
        ("0x10 == mask", "16 == mask"),
    ],
)
def test_printer_uses_minimal_parentheses(text: str, printed: str) -> None:
    assert format_expr(parse_expression(text)) == printed


def test_printer_keeps_integral_decimals_decimal() -> None:
    node = syntax.DecimalLiteral(Decimal("1E+2"))
    assert format_expr(node) == "100.0"
    assert parse_expression("100.0") == node


@given(syntax_trees)
def test_print_then_parse_gives_back_the_same_tree(node: syntax.Node) -> None:
    assert parse_expression(format_expr(node)) == node


@given(st.text(max_size=200))
def test_arbitrary_text_parses_or_raises_rubric_error(text: str) -> None:
    with contextlib.suppress(RubricError):
        parse_expression(text)


@given(token_soup)
def test_token_soup_parses_or_raises_rubric_error(text: str) -> None:
    with contextlib.suppress(RubricError):
        node = parse_expression(text)
        assert parse_expression(format_expr(node)) == node
