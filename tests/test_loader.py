from __future__ import annotations

import contextlib
import copy
import tomllib
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rubric_prover.errors import RubricError
from rubric_prover.loader import load_rubric, loads_json, loads_toml, rubric_from_dict
from rubric_prover.sorts import BOOL, INT, REAL, BitVecSort
from tests.conftest import ORIGINAL
from tests.strategies import plausible_rubrics, rubric_like_dicts

BASE_TOML = """
id = "base"
exploit_threshold = 0.85

[variables]
x = { type = "int", min = 0, max = 10 }
flag = "bool"

[[criteria]]
id = "c1"
weight = 1
when = "x >= 5"
"""


def base() -> dict[str, Any]:
    return tomllib.loads(BASE_TOML, parse_float=Decimal)


def problems(data: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(RubricError) as exc:
        rubric_from_dict(data)
    return [(d.path, d.message) for d in exc.value.diagnostics]


def with_changes(path: list[Any], value: Any) -> dict[str, Any]:
    """Copy of the base rubric with one nested key set (or deleted when value is ...)."""
    data = copy.deepcopy(base())
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    if value is ...:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


def test_base_rubric_loads() -> None:
    rubric = rubric_from_dict(base())
    assert rubric.id == "base"
    assert rubric.exploit_threshold == Fraction(17, 20)
    assert [(v.name, v.sort, v.lower, v.upper) for v in rubric.variables] == [
        ("x", INT, 0, 10),
        ("flag", BOOL, None, None),
    ]
    assert rubric.criteria[0].weight == 1
    assert rubric.criteria[0].when.source == "x >= 5"


@pytest.mark.parametrize("path", sorted(ORIGINAL.glob("*.toml")), ids=lambda p: p.stem)
def test_original_fixtures_load(path: Path) -> None:
    rubric = load_rubric(path)
    assert sum(c.weight for c in rubric.criteria) == 1


def test_json_and_toml_versions_of_a_rubric_are_identical() -> None:
    assert load_rubric(ORIGINAL / "redundant_latency.json") == load_rubric(
        ORIGINAL / "redundant_latency.toml"
    )


def test_decimals_are_exact_where_floats_would_not_be() -> None:
    # Plain float addition misses 1 here on every supported Python version.
    assert 0.3 + 0.6 + 0.1 == 0.9999999999999999
    data = base()
    data["criteria"] = [
        {"id": "a", "weight": Decimal("0.3"), "when": "x > 1"},
        {"id": "b", "weight": Decimal("0.6"), "when": "x > 2"},
        {"id": "c", "weight": Decimal("0.1"), "when": "x > 3"},
    ]
    weights = [c.weight for c in rubric_from_dict(data).criteria]
    assert weights == [Fraction(3, 10), Fraction(3, 5), Fraction(1, 10)]
    assert sum(weights) == 1


def test_variable_sorts_and_bounds() -> None:
    rubric = loads_toml(
        """
        id = "sorts"
        exploit_threshold = 1
        [variables]
        r = { type = "real", min = -0.5, max = 2 }
        bits = { type = "bv12", min = 1, max = 4095 }
        n = "int"
        [[criteria]]
        id = "c"
        weight = 1
        when = "r > 0 and bits > 1 and n > 0"
        """
    )
    r, bits, n = rubric.variables
    assert (r.sort, r.lower, r.upper) == (REAL, Fraction(-1, 2), 2)
    assert (bits.sort, bits.lower, bits.upper) == (BitVecSort(12), 1, 4095)
    assert (n.sort, n.lower, n.upper) == (INT, None, None)


def test_penalties_and_invariants() -> None:
    data = base()
    data["penalties"] = [
        {"id": "p1", "deduct": Decimal("0.25"), "when": "flag"},
        {"id": "p2", "zero": True, "when": "x == 0", "description": "hard stop"},
    ]
    data["invariants"] = [{"id": "i1", "holds": "not flag"}]
    data["assume"] = ["x != 3"]
    rubric = rubric_from_dict(data)
    assert [(p.id, p.deduction, p.zeroes_score) for p in rubric.penalties] == [
        ("p1", Fraction(1, 4), False),
        ("p2", None, True),
    ]
    assert rubric.penalties[1].description == "hard stop"
    assert [i.id for i in rubric.invariants] == ["i1"]
    assert [a.source for a in rubric.assumptions] == ["x != 3"]


REQUIRED = "required"
UNIT = "must be greater than 0 and at most 1"


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (["id"], ..., [("id", REQUIRED)]),
        (
            ["id"],
            "has space",
            [
                (
                    "id",
                    "ids use letters, digits, '_', '.' and '-' "
                    "(64 characters at most), found 'has space'",
                )
            ],
        ),
        (["exploit_threshold"], Decimal(0), [("exploit_threshold", f"{UNIT}, found 0")]),
        (["exploit_threshold"], Decimal("1.5"), [("exploit_threshold", f"{UNIT}, found 1.5")]),
        (["exploit_threshold"], "high", [("exploit_threshold", "expected a number, found text")]),
        (
            ["exploit_threshold"],
            True,
            [("exploit_threshold", "expected a number, found true/false")],
        ),
        (
            ["exploit_threshold"],
            0.85,
            [
                (
                    "exploit_threshold",
                    "floats are not exact; use Decimal('0.85') or an int (found 0.85)",
                )
            ],
        ),
        (
            ["exploit_threshold"],
            Decimal("NaN"),
            [("exploit_threshold", "must be a finite number, found NaN")],
        ),
        (["variables"], {}, [("variables", "at least one variable is required")]),
        (["variables"], ["x"], [("variables", "expected a table of name = type, found a list")]),
        (
            ["variables", "x", "type"],
            "float",
            [("variables.x.type", "unknown type 'float'; use bool, int, real or bv1 ... bv64")],
        ),
        (
            ["variables", "x", "type"],
            "bv65",
            [("variables.x.type", "unknown type 'bv65'; use bool, int, real or bv1 ... bv64")],
        ),
        (
            ["variables", "x", "type"],
            ...,
            [("variables.x.type", "required: one of bool, int, real, bv1 ... bv64")],
        ),
        (["variables", "x", "min"], 11, [("variables.x", "min (11) is greater than max (10)")]),
        (
            ["variables", "x", "min"],
            Decimal("1.5"),
            [("variables.x.min", "int bounds must be whole numbers, found 1.5")],
        ),
        (
            ["variables", "x", "maximum"],
            3,
            [("variables.x.maximum", "unknown key; expected one of: description, max, min, type")],
        ),
        (
            ["variables", "flag"],
            {"type": "bool", "min": 0},
            [("variables.flag.min", "bool variables have no bounds")],
        ),
        (
            ["variables", "flag"],
            {"type": "bv8", "max": 300},
            [("variables.flag.max", "must be between 0 and 255 for bv8")],
        ),
        (
            ["variables", "flag"],
            3,
            [("variables.flag", "expected a type name or a table, found a number")],
        ),
        (["criteria"], [], [("criteria", "at least one criterion is required")]),
        (["criteria"], "c1", [("criteria", "expected a list, found text")]),
        (["criteria", 0], "c1", [("criteria[0]", "expected a table, found text")]),
        (["criteria", 0, "weight"], ..., [('criteria["c1"].weight', REQUIRED)]),
        (
            ["criteria", 0, "weight"],
            Decimal("1.2"),
            [('criteria["c1"].weight', f"{UNIT}, found 1.2")],
        ),
        (
            ["criteria", 0, "weight"],
            Decimal("0.9"),
            [("criteria", "weights must sum to exactly 1, they sum to 0.9")],
        ),
        (["criteria", 0, "when"], ..., [('criteria["c1"].when', REQUIRED)]),
        (
            ["criteria", 0, "when"],
            5,
            [('criteria["c1"].when', "expected an expression as text, found a number")],
        ),
        (["criteria", 0, "id"], ..., [("criteria[0].id", REQUIRED)]),
        (
            ["criteria", 0, "points"],
            3,
            [
                (
                    'criteria["c1"].points',
                    "unknown key; expected one of: description, id, weight, when",
                )
            ],
        ),
        (
            ["exploit_treshold"],
            Decimal("0.85"),
            [
                (
                    "exploit_treshold",
                    "unknown key; expected one of: assume, criteria, description, "
                    "exploit_threshold, id, invariants, penalties, variables",
                )
            ],
        ),
        (["assume"], "x > 1", [("assume", "expected a list, found text")]),
        (["description"], 7, [("description", "expected text, found a number")]),
    ],
)
def test_schema_errors_name_the_field(path: list[Any], value: Any, expected: list[Any]) -> None:
    assert problems(with_changes(path, value)) == expected


def test_missing_required_sections() -> None:
    assert problems({"id": "x"}) == [
        ("criteria", REQUIRED),
        ("exploit_threshold", REQUIRED),
        ("variables", REQUIRED),
    ]


@pytest.mark.parametrize(
    ("penalty", "expected"),
    [
        (
            {"id": "p", "when": "flag", "deduct": Decimal("0.1"), "zero": True},
            [('penalties["p"]', "set either 'deduct' or 'zero', not both")],
        ),
        (
            {"id": "p", "when": "flag"},
            [('penalties["p"]', "a penalty needs 'deduct = <amount>' or 'zero = true'")],
        ),
        (
            {"id": "p", "when": "flag", "zero": False},
            [('penalties["p"].zero', "must be true (leave it out for a deduction)")],
        ),
        ({"id": "p", "when": "flag", "deduct": 0}, [('penalties["p"].deduct', f"{UNIT}, found 0")]),
        ({"id": "p", "deduct": Decimal("0.1")}, [('penalties["p"].when', REQUIRED)]),
    ],
)
def test_penalty_errors(penalty: dict[str, Any], expected: list[Any]) -> None:
    data = base()
    data["penalties"] = [penalty]
    assert problems(data) == expected


def test_invariant_errors() -> None:
    data = base()
    data["invariants"] = [{"id": "i1"}, {"holds": "flag"}]
    assert problems(data) == [('invariants["i1"].holds', REQUIRED), ("invariants[1].id", REQUIRED)]


def test_ids_are_unique_across_sections() -> None:
    data = base()
    data["invariants"] = [{"id": "c1", "holds": "flag"}]
    assert problems(data) == [("invariants[0].id", "id 'c1' is already used at criteria[0].id")]


@pytest.mark.parametrize("name", ["1x", "and", "has space", "x" * 65])
def test_variable_name_rules(name: str) -> None:
    data = base()
    data["variables"][name] = "int"
    ((path, message),) = problems(data)
    assert path == f"variables.{name}"
    assert message.startswith("variable names start with a letter or '_'")


def test_condition_errors_carry_the_expression_position() -> None:
    data = base()
    data["criteria"][0]["when"] = "x >=\n  flag + 1"
    with pytest.raises(RubricError) as exc:
        rubric_from_dict(data)
    (diagnostic,) = exc.value.diagnostics
    assert diagnostic.path == 'criteria["c1"].when'
    assert (diagnostic.line, diagnostic.column) == (2, 8)
    assert diagnostic.message == "'+' cannot combine bool and a number"
    assert str(exc.value) == (
        "criteria[\"c1\"].when:2:8: '+' cannot combine bool and a number\n"
        "      flag + 1\n"
        "           ^"
    )


def test_assumption_errors_are_located_by_index() -> None:
    data = base()
    data["assume"] = ["x > 1", "y > 1"]
    assert problems(data) == [("assume[1]", "unknown variable 'y'")]


def test_broken_variable_declarations_do_not_cascade() -> None:
    """A bad declaration suppresses type checking, so 'x' is not also 'unknown'."""
    data = base()
    data["variables"]["x"]["type"] = "integer"
    data["criteria"][0]["when"] = "x >= 5"
    data["invariants"] = [{"id": "i", "holds": "x >"}]  # syntax errors are still reported
    assert problems(data) == [
        ("variables.x.type", "unknown type 'integer'; use bool, int, real or bv1 ... bv64"),
        ('invariants["i"].holds', "expected an expression, found end of input"),
    ]


def test_every_problem_is_reported_at_once() -> None:
    data = base()
    data["exploit_threshold"] = Decimal(2)
    data["criteria"][0]["when"] = "x >"
    data["penalties"] = [{"id": "p", "when": "flag"}]
    assert len(problems(data)) == 3


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"id": "a", "id": "b"}', "invalid JSON: duplicate key 'id'"),
        ('{"exploit_threshold": NaN}', "invalid JSON: NaN is not a valid number here"),
        ('{"exploit_threshold": Infinity}', "invalid JSON: Infinity is not a valid number here"),
        ("[1, 2]", "the top level must be an object, found a list"),
        ('{"id": "a",\n "x": }', "invalid JSON: Expecting value (line 2, column 7)"),
    ],
)
def test_json_input_errors(text: str, message: str) -> None:
    with pytest.raises(RubricError) as exc:
        loads_json(text)
    assert [d.message for d in exc.value.diagnostics] == [message]


def test_toml_syntax_errors_are_reported() -> None:
    with pytest.raises(RubricError) as exc:
        loads_toml("id = \nx")
    assert exc.value.diagnostics[0].message.startswith("invalid TOML: ")


def test_toml_special_floats_are_refused() -> None:
    with pytest.raises(RubricError) as exc:
        loads_toml(BASE_TOML.replace("exploit_threshold = 0.85", "exploit_threshold = nan"))
    assert [d.message for d in exc.value.diagnostics] == ["must be a finite number, found NaN"]


@pytest.mark.parametrize(
    ("toml_value", "found"),
    [("2026-11-12", "a date/time"), ("[1]", "a list"), ("{ a = 1 }", "a table")],
)
def test_wrong_kinds_of_value_are_named(toml_value: str, found: str) -> None:
    text = BASE_TOML.replace("exploit_threshold = 0.85", f"exploit_threshold = {toml_value}")
    with pytest.raises(RubricError) as exc:
        loads_toml(text)
    assert [d.message for d in exc.value.diagnostics] == [f"expected a number, found {found}"]


def test_json_null_is_named_null() -> None:
    with pytest.raises(RubricError) as exc:
        loads_json(
            '{"id": "x", "exploit_threshold": null, "variables": {"x": "int"}, '
            '"criteria": [{"id": "c", "weight": 1, "when": "x > 0"}]}'
        )
    assert [d.message for d in exc.value.diagnostics] == ["expected a number, found null"]


def test_top_level_must_be_a_table() -> None:
    with pytest.raises(RubricError) as exc:
        rubric_from_dict([])  # type: ignore[arg-type]
    assert exc.value.diagnostics[0].message == "the top level must be a table, found a list"


def test_load_rubric_by_suffix(tmp_path: Path) -> None:
    (tmp_path / "r.toml").write_text(BASE_TOML, encoding="utf-8")
    assert load_rubric(tmp_path / "r.toml").id == "base"
    (tmp_path / "r.yaml").write_text("id: base", encoding="utf-8")
    with pytest.raises(RubricError, match=r"unsupported file type '\.yaml'"):
        load_rubric(tmp_path / "r.yaml")


# Fuzz tests: any exception other than RubricError escapes and fails the test.


@given(rubric_like_dicts)
def test_arbitrary_data_loads_or_raises_rubric_error(data: dict[str, Any]) -> None:
    with contextlib.suppress(RubricError):
        rubric_from_dict(data)


@given(plausible_rubrics)
def test_rubric_shaped_data_loads_or_raises_rubric_error(data: dict[str, Any]) -> None:
    with contextlib.suppress(RubricError):
        rubric = rubric_from_dict(data)
        assert sum(c.weight for c in rubric.criteria) == 1


@given(st.text(max_size=300))
def test_arbitrary_text_as_toml_or_json_raises_only_rubric_error(text: str) -> None:
    with contextlib.suppress(RubricError):
        loads_toml(text)
    with contextlib.suppress(RubricError):
        loads_json(text)


def test_values_of_unexpected_python_types_are_named() -> None:
    data = base()
    data["exploit_threshold"] = {0.5}
    assert problems(data) == [("exploit_threshold", "expected a number, found set")]
