"""Value sorts (types) of rubric variables and expressions."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_BITVEC_WIDTH = 64


@dataclass(frozen=True, slots=True)
class BoolSort:
    def __str__(self) -> str:
        return "bool"


@dataclass(frozen=True, slots=True)
class IntSort:
    def __str__(self) -> str:
        return "int"


@dataclass(frozen=True, slots=True)
class RealSort:
    def __str__(self) -> str:
        return "real"


@dataclass(frozen=True, slots=True)
class BitVecSort:
    """Unsigned fixed-width bit-vector. Values are integers in ``[0, 2**width)``."""

    width: int

    def __str__(self) -> str:
        return f"bv{self.width}"

    @property
    def max_value(self) -> int:
        return (1 << self.width) - 1


Sort = BoolSort | IntSort | RealSort | BitVecSort

BOOL = BoolSort()
INT = IntSort()
REAL = RealSort()

_BITVEC_NAME = re.compile(r"bv([1-9][0-9]*)")


def parse_sort(name: str) -> Sort | None:
    """Map a type name from a rubric file to a sort, or ``None`` if it is not one."""
    simple: dict[str, Sort] = {"bool": BOOL, "int": INT, "real": REAL}
    if name in simple:
        return simple[name]
    match = _BITVEC_NAME.fullmatch(name)
    if match is None:
        return None
    width = int(match.group(1))
    if width > MAX_BITVEC_WIDTH:
        return None
    return BitVecSort(width)


def is_numeric(sort: Sort) -> bool:
    return isinstance(sort, IntSort | RealSort)
