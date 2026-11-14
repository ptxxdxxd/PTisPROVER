"""Exact number handling: rubric files are read as decimals and computed as fractions."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

MAX_DIGITS = 100
_INTEGER_LIMIT = int("1" + "0" * MAX_DIGITS)
TOO_LARGE = f"numbers are limited to {MAX_DIGITS} digits on each side of the decimal point"


def format_number(value: int | Fraction) -> str:
    """Render a number exactly.

    Integers print as integers, fractions with a terminating decimal expansion
    print as decimals (``7/20`` -> ``0.35``) and the rest print as ``p/q``.
    Nothing is rounded.
    """
    if isinstance(value, bool):
        raise TypeError("format_number does not accept bool")
    if isinstance(value, int):
        return str(value)
    numerator, denominator = value.numerator, value.denominator
    if denominator == 1:
        return str(numerator)
    rest, twos, fives = denominator, 0, 0
    while rest % 2 == 0:
        rest //= 2
        twos += 1
    while rest % 5 == 0:
        rest //= 5
        fives += 1
    if rest != 1:
        return f"{numerator}/{denominator}"
    places = max(twos, fives)
    digits = str(abs(numerator) * 10**places // denominator).rjust(places + 1, "0")
    sign = "-" if numerator < 0 else ""
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def within_limits(value: int | Decimal) -> bool:
    """True if a number has at most MAX_DIGITS digits on each side of the decimal point.

    The limit keeps exact arithmetic cheap: without it, ``1e999999999`` in a rubric file
    would mean building a billion-digit integer.
    """
    if isinstance(value, int):
        return abs(value) < _INTEGER_LIMIT
    if not value.is_finite():
        return False
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)  # finite decimals have integer exponents
    leading_digit_position: int = value.adjusted()
    return exponent >= -MAX_DIGITS and leading_digit_position < MAX_DIGITS


def decimal_to_fraction(value: Decimal) -> Fraction:
    """Convert a Decimal within the size limits to the Fraction it denotes, exactly."""
    if not within_limits(value):
        raise ValueError(f"not a finite number within the size limits: {value}")
    return Fraction(value)
