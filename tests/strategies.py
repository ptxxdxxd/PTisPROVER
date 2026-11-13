"""Hypothesis strategies shared by the property tests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypothesis import strategies as st

from rubric_prover import syntax

BINARY_OPS: list[syntax.BinaryOp] = [
    "implies", "or", "and", "==", "!=", "<", "<=", ">", ">=", "|", "^", "&", "+", "-", "*"
]  # fmt: skip
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
    "a", "x", "mask", "1", "0x0f", "0.5", "(", ")", "and", "or", "not", "implies",
    "true", "false", "==", "!=", "<", "<=", ">", ">=", "+", "-", "*", "&", "|", "^",
    " ", "\n",
]  # fmt: skip
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
    "id", "description", "exploit_threshold", "assume", "variables", "criteria",
    "penalties", "invariants", "weights",
]  # fmt: skip
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
