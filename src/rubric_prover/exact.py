"""Exact number handling: rubric files are read as decimals and computed as fractions."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction


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


def decimal_to_fraction(value: Decimal) -> Fraction:
    """Convert a finite Decimal to the Fraction it denotes, exactly."""
    if not value.is_finite():
        raise ValueError(f"not a finite number: {value}")
    return Fraction(value)
