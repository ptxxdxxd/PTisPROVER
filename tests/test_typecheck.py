from __future__ import annotations

import contextlib
from fractions import Fraction

import pytest
from hypothesis import given

from rubric_prover import ir
from rubric_prover.errors import RubricError
from rubric_prover.sorts import BOOL, INT, REAL, BitVecSort, Sort
from rubric_prover.typecheck import check_condition
from tests.strategies import token_soup

BV8 = BitVecSort(8)
BV4 = BitVecSort(4)
SORTS: dict[str, Sort] = {
    "x": INT,
    "r": REAL,
    "mask": BV8,
    "nibble": BV4,
    "a": BOOL,
    "b": BOOL,
    "margin": INT,
}

X, R, MASK = ir.Var("x", INT), ir.Var("r", REAL), ir.Var("mask", BV8)
A, B = ir.Var("a", BOOL), ir.Var("b", BOOL)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # An int variable meeting a decimal widens to real; the literal stays exact.
        ("x >= 0.5", ir.Compare(">=", ir.ToReal(X), ir.Const(REAL, Fraction(1, 2)))),
        # An integer literal takes the sort of the variable it meets.
        ("r > 1", ir.Compare(">", R, ir.Const(REAL, Fraction(1)))),
        ("x > 1", ir.Compare(">", X, ir.Const(INT, 1))),
        ("mask == 255", ir.Compare("==", MASK, ir.Const(BV8, 255))),
        # int + real widens the int side.
        (
            "x + r > 0",
            ir.Compare(">", ir.Arith("+", ir.ToReal(X), R), ir.Const(REAL, Fraction(0))),
        ),
        (
            "mask & 0x07 == 7",
            ir.Compare("==", ir.BitOp("&", MASK, ir.Const(BV8, 7)), ir.Const(BV8, 7)),
        ),
        # Two literals: int unless either is a decimal.
        (
            "1 + 2 == 3",
            ir.Compare("==", ir.Arith("+", ir.Const(INT, 1), ir.Const(INT, 2)), ir.Const(INT, 3)),
        ),
        (
            "0.5 + 1 == 1.5",
            ir.Compare(
                "==",
                ir.Arith("+", ir.Const(REAL, Fraction(1, 2)), ir.Const(REAL, Fraction(1))),
                ir.Const(REAL, Fraction(3, 2)),
            ),
        ),
        # Unary minus on a literal folds into the literal.
        ("-1 < x", ir.Compare("<", ir.Const(INT, -1), X)),
        ("-x <= 3", ir.Compare("<=", ir.Neg(X), ir.Const(INT, 3))),
        ("r > x", ir.Compare(">", R, ir.ToReal(X))),
        ("a == true", ir.Compare("==", A, ir.Const(BOOL, True))),
        ("a implies not b", ir.Logic("implies", A, ir.Not(B))),
        ("true", ir.Const(BOOL, True)),
    ],
)
def test_well_typed_conditions(text: str, expected: ir.Expr) -> None:
    assert check_condition(text, SORTS) == expected


@pytest.mark.parametrize(
    ("text", "message", "column"),
    [
        ("x", "a condition must be true or false, but this is int", 1),
        ("x + 1", "a condition must be true or false, but this is int", 1),
        ("y > 1", "unknown variable 'y'", 1),
        ("margn > 0", "unknown variable 'margn'; did you mean 'margin'?", 1),
        ("x + a > 0", "'+' cannot combine int and bool", 3),
        ("a + 1 > 0", "'+' cannot combine bool and a number", 3),
        ("a == 1", "'==' cannot combine bool and a number", 3),
        ("a + b", "'+' needs numbers, found bool", 3),
        (
            "mask + 1 == 2",
            "arithmetic on bit-vectors is not supported (it would wrap around); "
            "use &, |, ^ or compare them",
            6,
        ),
        ("mask & 256 == 0", "256 does not fit in bv8 (0 to 255)", 8),
        ("mask == -1", "-1 does not fit in bv8 (0 to 255)", 9),
        ("mask & 0.5 == 0", "a bv8 value cannot meet a decimal", 8),
        ("mask & nibble == 0", "bit-vector widths differ: bv8 & bv4", 6),
        ("mask == x", "'==' cannot combine bv8 and int", 6),
        ("1 & 2 == 0", "'&' needs a bit-vector variable on one side to fix the width", 3),
        ("a & b", "'&' works on bit-vectors; use 'and'/'or' for bools", 3),
        ("x & 1 == 1", "'&' works on bit-vectors only, found int", 3),
        ("a < b", "'<' cannot order true/false values", 3),
        ("-a", "'-' needs a number, found bool", 1),
        ("x and a", "'and' needs true/false operands, found int", 1),
        ("a or 1", "'or' needs true/false operands, found int", 6),
        ("not x", "'not' needs true/false operands, found int", 5),
    ],
)
def test_type_errors_say_what_and_where(text: str, message: str, column: int) -> None:
    with pytest.raises(RubricError) as exc:
        check_condition(text, SORTS)
    (diagnostic,) = exc.value.diagnostics
    assert (diagnostic.message, diagnostic.line, diagnostic.column) == (message, 1, column)


def test_unknown_variable_without_a_close_match_gives_no_hint() -> None:
    with pytest.raises(RubricError) as exc:
        check_condition("zzzz > 1", SORTS)
    assert exc.value.diagnostics[0].message == "unknown variable 'zzzz'"


@given(token_soup)
def test_token_soup_type_checks_or_raises_rubric_error(text: str) -> None:
    with contextlib.suppress(RubricError):
        assert check_condition(text, SORTS).sort == BOOL
