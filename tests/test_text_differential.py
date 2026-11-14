"""The whole pipeline against an evaluator that shares no code with it.

Each condition is generated twice: as rubric text, and as an equivalent, fully
parenthesised Python expression. The rubric text goes through the real loader, parser,
type checker and solver. The Python text is evaluated with ``eval`` over every outcome,
and the score is recomputed here from the definition. The two must agree on every finding.

This is the check on what test_differential.py cannot see: operator precedence, literal
coercion, bound handling and the loader, none of which are shared with this file.
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rubric_prover.loader import rubric_from_dict
from rubric_prover.prover import prove
from tests.compare import Truth, assert_report_matches

EXAMPLES = int(os.environ.get("DIFFERENTIAL_EXAMPLES", "300"))

Pair = tuple[str, str]  # (rubric expression, equivalent Python expression)
COMPARISONS = ["==", "!=", "<", "<=", ">", ">="]


@dataclass(frozen=True)
class Var:
    name: str
    kind: str  # "bool", "int" or "bvN"
    low: int | None = None
    high: int | None = None

    @property
    def width(self) -> int:
        return int(self.kind[2:])

    def values(self) -> list[bool] | list[int]:
        if self.kind == "bool":
            return [False, True]
        if self.kind == "int":
            assert self.low is not None
            assert self.high is not None
            return list(range(self.low, self.high + 1))
        low = 0 if self.low is None else self.low
        high = 2**self.width - 1 if self.high is None else self.high
        return list(range(low, high + 1))

    def declaration(self) -> dict[str, Any]:
        spec: dict[str, Any] = {"type": self.kind}
        if self.low is not None:
            spec["min"] = self.low
        if self.high is not None:
            spec["max"] = self.high
        return spec


@st.composite
def variables(draw: st.DrawFn) -> list[Var]:
    result = []
    for index in range(draw(st.integers(1, 3))):
        name = f"v{index}"
        kind = draw(st.sampled_from(["bool", "int", "bv2", "bv3"]))
        if kind == "bool":
            result.append(Var(name, kind))
        elif kind == "int":
            low = draw(st.integers(-3, 1))
            result.append(Var(name, kind, low, low + draw(st.integers(0, 4))))
        else:
            top = 2 ** int(kind[2:]) - 1
            floor = draw(st.one_of(st.none(), st.integers(0, top)))
            ceiling = draw(st.one_of(st.none(), st.integers(floor or 0, top)))
            result.append(Var(name, kind, floor, ceiling))
    return result


@st.composite
def atoms(draw: st.DrawFn, env: list[Var]) -> Pair:
    """A comparison or a bool variable, in both languages."""
    var = draw(st.sampled_from(env))
    op = draw(st.sampled_from(COMPARISONS))
    if var.kind == "bool":
        return draw(
            st.sampled_from(
                [
                    (var.name, var.name),
                    (f"{var.name} == false", f"({var.name} == False)"),
                    (f"{var.name} != true", f"({var.name} != True)"),
                ]
            )
        )
    if var.kind == "int":
        k = draw(st.integers(-4, 6))
        others = [v.name for v in env if v.kind == "int"]
        other = draw(st.sampled_from(others))
        forms = [
            (f"{var.name} {op} {k}", f"({var.name} {op} {k})"),
            # A decimal on the right widens the int on the left.
            (f"{var.name} {op} {k}.5", f"({var.name} {op} Fraction('{k}.5'))"),
            (f"{k} {op} -{var.name}", f"({k} {op} (-{var.name}))"),
            (f"{var.name} + {other} * 2 {op} {k}", f"(({var.name} + ({other} * 2)) {op} {k})"),
            (f"{var.name} - {other} - 1 {op} {k}", f"((({var.name} - {other}) - 1) {op} {k})"),
            (f"{var.name} * {other} {op} {k}", f"(({var.name} * {other}) {op} {k})"),
        ]
        return draw(st.sampled_from(forms))
    top = 2**var.width - 1
    k, mask = draw(st.integers(0, top)), draw(st.integers(0, top))
    same_width = [v.name for v in env if v.kind == var.kind]
    other = draw(st.sampled_from(same_width))
    bit_op = draw(st.sampled_from(["&", "|", "^"]))
    forms = [
        (f"{var.name} {op} {k}", f"({var.name} {op} {k})"),  # unsigned
        (f"{var.name} & {mask} == {k}", f"(({var.name} & {mask}) == {k})"),
        (f"{var.name} {bit_op} {other} != {k}", f"(({var.name} {bit_op} {other}) != {k})"),
        # & binds tighter than ^, which binds tighter than |.
        (
            f"{var.name} | {mask} ^ {other} & {k} == {k}",
            f"(({var.name} | ({mask} ^ ({other} & {k}))) == {k})",
        ),
    ]
    return draw(st.sampled_from(forms))


@st.composite
def conditions(draw: st.DrawFn, env: list[Var]) -> Pair:
    """Atoms joined without parentheses on the rubric side, so precedence is on trial."""
    a, pa = draw(atoms(env))
    b, pb = draw(atoms(env))
    c, pc = draw(atoms(env))
    shapes = [
        (a, pa),
        (f"not {a}", f"(not {pa})"),
        (f"{a} and {b}", f"({pa} and {pb})"),
        (f"{a} or {b}", f"({pa} or {pb})"),
        (f"{a} implies {b}", f"((not {pa}) or {pb})"),
        (f"{a} or {b} and {c}", f"({pa} or ({pb} and {pc}))"),
        (f"{a} and {b} or {c}", f"(({pa} and {pb}) or {pc})"),
        (f"not {a} and {b}", f"((not {pa}) and {pb})"),
        (f"not {a} or {b}", f"((not {pa}) or {pb})"),
        (f"{a} implies {b} implies {c}", f"((not {pa}) or ((not {pb}) or {pc}))"),
        (f"{a} or {b} implies {c}", f"((not ({pa} or {pb})) or {pc})"),
        (f"{a} implies {b} and {c}", f"((not {pa}) or ({pb} and {pc}))"),
        (f"({a} or {b}) and {c}", f"(({pa} or {pb}) and {pc})"),
        (f"not ({a} implies {b})", f"(not ((not {pa}) or {pb}))"),
    ]
    return draw(st.sampled_from(shapes))


WEIGHTS = [
    ["1"],
    ["0.5", "0.5"],
    ["0.25", "0.75"],
    ["0.2", "0.3", "0.5"],
    ["0.1", "0.2", "0.3", "0.4"],
]
DEDUCTIONS = [None, "0.05", "0.25", "0.5", "1"]  # None: zero the score
THRESHOLDS = ["0.05", "0.3", "0.5", "0.75", "1"]


@dataclass(frozen=True)
class Case:
    data: dict[str, Any]  # what the loader is given
    env: list[Var]
    criteria: list[tuple[str, Fraction, str]]  # id, weight, Python condition
    penalties: list[tuple[str, Fraction | None, str]]
    invariants: list[tuple[str, str]]
    assumptions: list[str]
    threshold: Fraction


@st.composite
def cases(draw: st.DrawFn) -> Case:
    env = draw(variables())
    condition = conditions(env)
    weights = draw(st.sampled_from(WEIGHTS))
    criteria = [(f"c{i}", w, *draw(condition)) for i, w in enumerate(weights)]
    penalties = [
        (f"p{i}", draw(st.sampled_from(DEDUCTIONS)), *draw(condition))
        for i in range(draw(st.integers(0, 2)))
    ]
    invariants = [(f"i{i}", *draw(condition)) for i in range(draw(st.integers(0, 2)))]
    assumptions = [draw(condition) for _ in range(draw(st.integers(0, 1)))]
    threshold = draw(st.sampled_from(THRESHOLDS))
    data = {
        "id": "generated",
        "exploit_threshold": Decimal(threshold),
        "assume": [text for text, _ in assumptions],
        "variables": {v.name: v.declaration() for v in env},
        "criteria": [
            {"id": ident, "weight": Decimal(w), "when": text} for ident, w, text, _ in criteria
        ],
        "penalties": [
            {"id": ident, "when": text, **({"zero": True} if d is None else {"deduct": Decimal(d)})}
            for ident, d, text, _ in penalties
        ],
        "invariants": [{"id": ident, "holds": text} for ident, text, _ in invariants],
    }
    return Case(
        data=data,
        env=env,
        criteria=[(ident, Fraction(w), py) for ident, w, _, py in criteria],
        penalties=[
            (ident, None if d is None else Fraction(d), py) for ident, d, _, py in penalties
        ],
        invariants=[(ident, py) for ident, _, py in invariants],
        assumptions=[py for _, py in assumptions],
        threshold=Fraction(threshold),
    )


def truth_by_python(case: Case) -> Truth:
    """Score every outcome from the definition in docs/semantics.md, using Python's own eval."""

    def holds(python: str, outcome: dict[str, Any]) -> bool:
        value = eval(python, {"__builtins__": {}, "Fraction": Fraction}, outcome)
        assert isinstance(value, bool)
        return value

    scored = []
    names = [v.name for v in case.env]
    for values in itertools.product(*(v.values() for v in case.env)):
        outcome = dict(zip(names, values, strict=True))
        if not all(holds(assumption, outcome) for assumption in case.assumptions):
            continue
        paying = frozenset(ident for ident, _, py in case.criteria if holds(py, outcome))
        firing = frozenset(ident for ident, _, py in case.penalties if holds(py, outcome))
        broken = frozenset(ident for ident, py in case.invariants if not holds(py, outcome))
        if any(d is None for ident, d, _ in case.penalties if ident in firing):
            score = Fraction(0)
        else:
            earned = sum((w for ident, w, _ in case.criteria if ident in paying), Fraction(0))
            deducted = sum(
                (d for ident, d, _ in case.penalties if ident in firing and d is not None),
                Fraction(0),
            )
            score = max(Fraction(0), earned - deducted)
        scored.append((score, paying, firing, broken))
    return Truth.from_outcomes(
        scored,
        [ident for ident, _, _ in case.criteria],
        [ident for ident, _, _ in case.penalties],
        [ident for ident, _ in case.invariants],
    )


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cases())
def test_rubric_text_agrees_with_an_independent_evaluator(case: Case) -> None:
    report = prove(rubric_from_dict(case.data))
    assert_report_matches(
        report,
        truth_by_python(case),
        criteria=[ident for ident, _, _ in case.criteria],
        penalties=[ident for ident, _, _ in case.penalties],
        invariants=[ident for ident, _ in case.invariants],
        threshold=case.threshold,
    )
