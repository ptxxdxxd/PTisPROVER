from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ptisprover.exact import decimal_to_fraction, format_number


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0, "0"),
        (-5, "-5"),
        (Fraction(10, 1), "10"),
        (Fraction(7, 20), "0.35"),
        (Fraction(-3, 25), "-0.12"),
        (Fraction(1, 8), "0.125"),
        (Fraction(-1, 2), "-0.5"),
        (Fraction(1, 3), "1/3"),
        (Fraction(-2, 7), "-2/7"),
        (Fraction(3, 1_000_000), "0.000003"),
    ],
)
def test_format_number(value: int | Fraction, text: str) -> None:
    assert format_number(value) == text


@given(st.fractions())
def test_format_number_is_exact(value: Fraction) -> None:
    assert Fraction(format_number(value)) == value


def test_format_number_rejects_bool() -> None:
    with pytest.raises(TypeError):
        format_number(True)


def test_decimal_to_fraction() -> None:
    assert decimal_to_fraction(Decimal("0.35")) == Fraction(7, 20)
    with pytest.raises(ValueError, match="not a finite number"):
        decimal_to_fraction(Decimal("NaN"))
