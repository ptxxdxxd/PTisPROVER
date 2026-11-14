"""The shipped JSON Schema and the loader must agree on structure."""

from __future__ import annotations

import json
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ptisprover import loader
from ptisprover.errors import RubricError
from ptisprover.lexer import KEYWORDS
from ptisprover.schema import rubric_schema_text
from tests.repo_paths import ORIGINAL

SCHEMA: dict[str, Any] = json.loads(rubric_schema_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def read(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        return tomllib.loads(text, parse_float=Decimal)
    data: dict[str, Any] = json.loads(text, parse_float=Decimal)
    return data


def test_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("path", sorted(ORIGINAL.iterdir()), ids=lambda p: p.name)
def test_fixtures_satisfy_the_schema(path: Path) -> None:
    errors = [e.message for e in VALIDATOR.iter_errors(read(path))]
    assert errors == []


def test_schema_and_loader_accept_the_same_keys() -> None:
    defs = SCHEMA["$defs"]
    assert set(SCHEMA["properties"]) == loader.TOP_LEVEL_KEYS
    assert set(SCHEMA["required"]) == loader.REQUIRED_TOP_LEVEL_KEYS
    assert set(defs["variable"]["properties"]) == loader.VARIABLE_KEYS
    assert set(defs["criterion"]["properties"]) == loader.CRITERION_KEYS
    assert set(defs["penalty"]["properties"]) == loader.PENALTY_KEYS
    assert set(defs["invariant"]["properties"]) == loader.INVARIANT_KEYS


def test_schema_and_loader_use_the_same_name_rules() -> None:
    names = SCHEMA["properties"]["variables"]["propertyNames"]
    assert names["pattern"] == f"^{loader.NAME_PATTERN}$"
    assert set(names["not"]["enum"]) == KEYWORDS
    assert SCHEMA["$defs"]["id"]["pattern"] == f"^{loader.ID_PATTERN}$"


def _base() -> dict[str, Any]:
    return read(ORIGINAL / "redundant_latency.toml")


def _set(data: dict[str, Any], path: list[Any], value: Any) -> dict[str, Any]:
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    if value is ...:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["id"], ...),
        (["id"], "has space"),
        (["exploit_threshold"], Decimal(0)),
        (["exploit_threshold"], Decimal("1.01")),
        (["variables"], {}),
        (["variables", "accuracy"], "float"),
        (["variables", "accuracy"], "bv65"),
        (["variables", "accuracy", "unit"], "pct"),
        (["variables", "and"], "bool"),
        (["criteria"], []),
        (["criteria", 0, "weight"], Decimal(0)),
        (["criteria", 0, "when"], ""),
        (["criteria", 0, "note"], "x"),
        (["invariants", 0, "holds"], ...),
        (["penalties"], [{"id": "p", "when": "accuracy > 0"}]),
        (["penalties"], [{"id": "p", "when": "accuracy > 0", "zero": True, "deduct": 1}]),
        (["penalties"], [{"id": "p", "when": "accuracy > 0", "zero": False}]),
        (["typo"], 1),
    ],
)
def test_structural_errors_are_rejected_by_both(path: list[Any], value: Any) -> None:
    data = _set(_base(), path, value)
    assert not VALIDATOR.is_valid(data)
    with pytest.raises(RubricError):
        loader.rubric_from_dict(data)
