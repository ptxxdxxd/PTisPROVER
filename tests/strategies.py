"""Hypothesis strategies shared by the property tests."""

from __future__ import annotations

import functools
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import strategies as st

from ptisprover import ir, syntax
from ptisprover.model import Condition, Criterion, Invariant, Penalty, Rubric, Variable
from ptisprover.sorts import BOOL, INT, REAL, BitVecSort, Sort

BINARY_OPS: list[syntax.BinaryOp] = [
    "implies",
    "or",
    "and",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "|",
    "^",
    "&",
    "+",
    "-",
    "*",
]
UNARY_OPS: list[syntax.UnaryOp] = ["-", "not"]

names = st.sampled_from(["a", "b", "x", "mask", "net_margin", "_t1"])
decimals = st.decimals(
    min_value=0, max_value=10**6, places=4, allow_nan=False, allow_infinity=False
).map(lambda d: d.copy_abs())

leaves: st.SearchStrategy[syntax.Node] = st.one_of(
    names.map(syntax.Name),
    st.integers(min_value=0, max_value=10**12).map(syntax.IntLiteral),
    decimals.map(syntax.DecimalLiteral),
    st.booleans().map(syntax.BoolLiteral),
)


def _extend(children: st.SearchStrategy[syntax.Node]) -> st.SearchStrategy[syntax.Node]:
    return st.one_of(
        st.builds(syntax.Unary, st.sampled_from(UNARY_OPS), children),
        st.builds(syntax.Binary, st.sampled_from(BINARY_OPS), children, children),
    )


syntax_trees = st.recursive(leaves, _extend, max_leaves=30)

# Strings built from the expression language's own tokens reach far more of the
# parser than arbitrary text does.
_TOKENS = [
    "a",
    "x",
    "mask",
    "1",
    "0x0f",
    "0.5",
    "(",
    ")",
    "and",
    "or",
    "not",
    "implies",
    "true",
    "false",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "+",
    "-",
    "*",
    "&",
    "|",
    "^",
    " ",
    "\n",
]
token_soup = st.lists(st.sampled_from(_TOKENS), max_size=40).map(" ".join)

# Arbitrary JSON-like data, plus Decimal as the loaders produce it.
json_values: st.SearchStrategy[Any] = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.decimals(allow_nan=True, allow_infinity=True),
        st.text(max_size=20),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=12), children, max_size=4),
    ),
    max_leaves=20,
)

_RUBRIC_KEYS = [
    "id",
    "description",
    "exploit_threshold",
    "assume",
    "variables",
    "criteria",
    "penalties",
    "invariants",
    "weights",
]
rubric_like_dicts = st.dictionaries(st.sampled_from(_RUBRIC_KEYS), json_values, max_size=8)

# Rubric-shaped data with plausible and implausible values mixed, so the fuzz
# test reaches the per-field validation rather than failing at the top level.
_numbers = st.one_of(
    st.integers(min_value=-3, max_value=3),
    st.decimals(min_value=-2, max_value=2, places=2),
    st.sampled_from([Decimal("NaN"), Decimal("Infinity"), 0.5, True, "0.5"]),
)
_type_names = st.sampled_from(["bool", "int", "real", "bv1", "bv8", "bv0", "bv65", "float", ""])
_variable_specs = st.one_of(
    _type_names,
    st.fixed_dictionaries(
        {"type": _type_names},
        optional={
            "min": _numbers,
            "max": _numbers,
            "description": json_values,
            "maximum": _numbers,
        },
    ),
    json_values,
)
_variable_names = st.sampled_from(["x", "y", "flag", "mask", "and", "1x", "has space", ""])
_conditions = st.one_of(
    token_soup, st.sampled_from(["x > 0", "flag", "mask & 1 == 1"]), json_values
)
_ids = st.one_of(st.sampled_from(["c1", "c2", "p1", "i1", "bad id", ""]), json_values)
_criteria = st.fixed_dictionaries(
    {}, optional={"id": _ids, "weight": _numbers, "when": _conditions, "extra": json_values}
)
_penalties = st.fixed_dictionaries(
    {}, optional={"id": _ids, "when": _conditions, "deduct": _numbers, "zero": json_values}
)
_invariants = st.fixed_dictionaries({}, optional={"id": _ids, "holds": _conditions})
plausible_rubrics = st.fixed_dictionaries(
    {},
    optional={
        "id": _ids,
        "exploit_threshold": _numbers,
        "variables": st.one_of(
            st.dictionaries(_variable_names, _variable_specs, max_size=4), json_values
        ),
        "assume": st.one_of(st.lists(_conditions, max_size=3), json_values),
        "criteria": st.one_of(st.lists(st.one_of(_criteria, json_values), max_size=4), json_values),
        "penalties": st.lists(st.one_of(_penalties, json_values), max_size=3),
        "invariants": st.lists(st.one_of(_invariants, json_values), max_size=3),
        "typo": json_values,
    },
)


_LOGIC_OPS: list[ir.LogicalOp] = ["and", "or", "implies"]
_ARITH_OPS: list[ir.ArithmeticOp] = ["+", "-", "*"]
_BIT_OPS: list[ir.BitwiseOp] = ["&", "|", "^"]
_EQUALITY_OPS: list[ir.CompareOp] = ["==", "!="]
_ALL_COMPARE_OPS: list[ir.CompareOp] = ["==", "!=", "<", "<=", ">", ">="]


def constants(sort: Sort) -> st.SearchStrategy[ir.Expr]:
    if sort == BOOL:
        values: st.SearchStrategy[ir.Value] = st.booleans()
    elif sort == INT:
        values = st.integers(-4, 4)
    elif sort == REAL:
        values = st.fractions(min_value=-4, max_value=4, max_denominator=4)
    else:
        assert isinstance(sort, BitVecSort)
        values = st.integers(0, sort.max_value)
    return values.map(lambda v: ir.Const(sort, v))


@functools.cache
def typed_exprs(
    sort: Sort, env: tuple[tuple[str, Sort], ...], depth: int
) -> st.SearchStrategy[ir.Expr]:
    """Well-typed expressions of ``sort`` over the variables in ``env``."""
    names = [name for name, s in env if s == sort]
    leaves = constants(sort)
    if names:
        leaves = st.one_of(leaves, st.sampled_from(names).map(lambda n: ir.Var(n, sort)))
    if depth == 0:
        return leaves

    def sub(s: Sort) -> st.SearchStrategy[ir.Expr]:
        return typed_exprs(s, env, depth - 1)

    options = [leaves]
    if sort == BOOL:
        # Variable-against-constant comparisons are what real criteria look like;
        # offering them twice keeps most generated criteria able to both pay and fail.
        atoms = _comparisons_with_constants(env)
        if atoms is not None:
            options += [atoms, atoms]
        options.append(st.builds(ir.Not, sub(BOOL)))
        options.append(st.builds(ir.Logic, st.sampled_from(_LOGIC_OPS), sub(BOOL), sub(BOOL)))
        options.append(st.builds(ir.Compare, st.sampled_from(_EQUALITY_OPS), sub(BOOL), sub(BOOL)))
        operand_sorts = sorted({s for _, s in env if s != BOOL} | {INT}, key=str)
        options.extend(
            st.builds(ir.Compare, st.sampled_from(_ALL_COMPARE_OPS), sub(s), sub(s))
            for s in operand_sorts
        )
    elif sort == INT:
        options.append(st.builds(ir.Neg, sub(INT)))
        options.append(st.builds(ir.Arith, st.sampled_from(_ARITH_OPS), sub(INT), sub(INT)))
    elif sort == REAL:
        options.append(st.builds(ir.Neg, sub(REAL)))
        options.append(st.builds(ir.Arith, st.sampled_from(_ARITH_OPS), sub(REAL), sub(REAL)))
        options.append(st.builds(ir.ToReal, sub(INT)))
    else:
        options.append(st.builds(ir.BitOp, st.sampled_from(_BIT_OPS), sub(sort), sub(sort)))
    return st.one_of(options)


def _comparisons_with_constants(
    env: tuple[tuple[str, Sort], ...],
) -> st.SearchStrategy[ir.Expr] | None:
    choices = [
        st.builds(
            ir.Compare,
            st.sampled_from(_EQUALITY_OPS if sort == BOOL else _ALL_COMPARE_OPS),
            st.just(ir.Var(name, sort)),
            constants(sort),
        )
        for name, sort in env
    ]
    return st.one_of(choices) if choices else None


def values_of(sort: Sort) -> st.SearchStrategy[ir.Value]:
    if sort == BOOL:
        return st.booleans()
    if sort == INT:
        return st.integers(-50, 50)
    if sort == REAL:
        return st.fractions(min_value=-50, max_value=50, max_denominator=12)
    assert isinstance(sort, BitVecSort)
    return st.integers(0, sort.max_value)


@st.composite
def finite_rubrics(draw: st.DrawFn) -> Rubric:
    """Small rubrics over bools, bit-vectors and bounded ints, so every outcome can be listed."""
    kinds = draw(st.lists(st.sampled_from(["bool", "bv2", "bv3", "int"]), min_size=1, max_size=3))
    variables = []
    for index, kind in enumerate(kinds):
        name = f"v{index}"
        if kind == "int":
            low = draw(st.integers(-3, 1))
            high = low + draw(st.integers(0, 4))
            variables.append(Variable(name, INT, low, high))
        elif kind == "bool":
            variables.append(Variable(name, BOOL))
        else:
            sort = BitVecSort(int(kind[2:]))
            lower = draw(st.one_of(st.none(), st.integers(0, sort.max_value)))
            upper = draw(st.one_of(st.none(), st.integers(lower or 0, sort.max_value)))
            variables.append(Variable(name, sort, lower, upper))
    env = tuple((v.name, v.sort) for v in variables)
    atoms = _comparisons_with_constants(env)
    assert atoms is not None
    conditions = st.one_of(
        atoms,
        st.builds(ir.Logic, st.sampled_from(_LOGIC_OPS), atoms, atoms),
        st.builds(ir.Not, atoms),
        typed_exprs(BOOL, env, 2),
    )

    def condition(label: str) -> Condition:
        return Condition(f"<{label}>", draw(conditions))

    shares = draw(st.lists(st.integers(1, 5), min_size=1, max_size=4))
    criteria = tuple(
        Criterion(f"c{i}", Fraction(k, sum(shares)), condition(f"c{i}"))
        for i, k in enumerate(shares)
    )
    penalties = tuple(
        Penalty(
            f"p{i}",
            condition(f"p{i}"),
            draw(st.one_of(st.none(), st.integers(1, 4).map(lambda k: Fraction(k, 4)))),
        )
        for i in range(draw(st.integers(0, 2)))
    )
    invariants = tuple(
        Invariant(f"i{i}", condition(f"i{i}")) for i in range(draw(st.integers(0, 2)))
    )
    assumptions = tuple(condition(f"a{i}") for i in range(draw(st.integers(0, 1))))
    return Rubric(
        id="generated",
        variables=tuple(variables),
        criteria=criteria,
        exploit_threshold=draw(
            st.sampled_from([Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1)])
        ),
        assumptions=assumptions,
        penalties=penalties,
        invariants=invariants,
    )
