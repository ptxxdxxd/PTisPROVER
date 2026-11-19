"""Read rubric files (TOML or JSON) into a validated ``Rubric``.

Numbers are read as exact decimals and stored as fractions, so ``0.1 + 0.2 + 0.7``
sums to exactly 1. Every problem found is reported, not just the first.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, TypeVar

from ptisprover.errors import Diagnostic, RubricError
from ptisprover.exact import TOO_LARGE, format_number, within_limits
from ptisprover.lexer import KEYWORDS
from ptisprover.model import Condition, Criterion, Invariant, Penalty, Rubric, Variable
from ptisprover.parser import parse_expression
from ptisprover.sorts import BoolSort, IntSort, RealSort, Sort, parse_sort
from ptisprover.typecheck import check_condition

TOP_LEVEL_KEYS = frozenset(
    {
        "id",
        "description",
        "exploit_threshold",
        "assume",
        "variables",
        "criteria",
        "penalties",
        "invariants",
    }
)
REQUIRED_TOP_LEVEL_KEYS = frozenset({"id", "exploit_threshold", "variables", "criteria"})
VARIABLE_KEYS = frozenset({"type", "min", "max", "description"})
CRITERION_KEYS = frozenset({"id", "weight", "when", "description"})
PENALTY_KEYS = frozenset({"id", "when", "deduct", "zero", "description"})
INVARIANT_KEYS = frozenset({"id", "holds", "description"})

ID_PATTERN = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}"
NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
_ID = re.compile(ID_PATTERN)
_NAME = re.compile(NAME_PATTERN)

_T = TypeVar("_T")


def load_rubric(path: str | os.PathLike[str]) -> Rubric:
    """Load a ``.toml`` or ``.json`` rubric file."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise RubricError.single("the file is not UTF-8 text") from None
    suffix = file.suffix.lower()
    if suffix == ".toml":
        return loads_toml(text)
    if suffix == ".json":
        return loads_json(text)
    raise RubricError.single(f"unsupported file type '{file.suffix}'; use .toml or .json")


def loads_toml(text: str) -> Rubric:
    try:
        document = tomllib.loads(text, parse_float=Decimal)
    except tomllib.TOMLDecodeError as exc:
        raise RubricError.single(f"invalid TOML: {exc}") from None
    except ValueError:  # Python refuses to read integers of several thousand digits
        raise RubricError.single(f"invalid TOML: {TOO_LARGE}") from None
    except RecursionError:
        raise RubricError.single("invalid TOML: values are nested too deeply") from None
    return rubric_from_dict(document)


def loads_json(text: str) -> Rubric:
    try:
        document = json.loads(
            text,
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise RubricError.single(
            f"invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from None
    except _JsonContentError as exc:
        raise RubricError.single(f"invalid JSON: {exc}") from None
    except ValueError:  # Python refuses to read integers of several thousand digits
        raise RubricError.single(f"invalid JSON: {TOO_LARGE}") from None
    except RecursionError:
        raise RubricError.single("invalid JSON: values are nested too deeply") from None
    if not isinstance(document, dict):
        raise RubricError.single(f"the top level must be an object, found {_kind(document)}")
    return rubric_from_dict(document)


def rubric_from_dict(document: Mapping[str, Any]) -> Rubric:
    """Validate parsed rubric document. Numbers must be int or Decimal; floats are refused."""
    return _Builder().build(document)


class _JsonContentError(ValueError):
    pass


def _reject_constant(name: str) -> Any:
    raise _JsonContentError(f"{name} is not a valid number here")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    members: dict[str, Any] = {}
    for key, value in pairs:
        if key in members:
            raise _JsonContentError(f"duplicate key '{key}'")
        members[key] = value
    return members


def _kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, int | Decimal | float):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, Mapping):
        return "a table"
    if isinstance(value, Sequence):
        return "a list"
    if isinstance(value, datetime | date | time):
        return "a date/time"
    return type(value).__name__


class _Builder:
    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []

    def _error(self, path: str, message: str) -> None:
        self._diagnostics.append(Diagnostic(message, path=path))

    def build(self, document: Mapping[str, Any]) -> Rubric:
        if not isinstance(document, Mapping):
            raise RubricError.single(f"the top level must be a table, found {_kind(document)}")
        self._unknown_keys(document, TOP_LEVEL_KEYS, "")
        for key in sorted(REQUIRED_TOP_LEVEL_KEYS - document.keys()):
            self._error(key, "required")

        rubric_id = self._id(document.get("id"), "id") if "id" in document else None
        description = self._text(document.get("description", ""), "description")
        threshold = None
        if "exploit_threshold" in document:
            threshold = self._fraction_in_unit_interval(
                document["exploit_threshold"], "exploit_threshold"
            )

        variables = self._variables(document.get("variables"))
        sorts = None if variables is None else {v.name: v.sort for v in variables}

        assumptions = tuple(
            c
            for index, entry in enumerate(self._list(document.get("assume", []), "assume"))
            if (c := self._condition(entry, f"assume[{index}]", sorts)) is not None
        )
        criteria = self._entries(document.get("criteria"), "criteria", sorts, self._criterion)
        penalties = self._entries(document.get("penalties", []), "penalties", sorts, self._penalty)
        invariants = self._entries(
            document.get("invariants", []), "invariants", sorts, self._invariant
        )
        if isinstance(document.get("criteria"), list | tuple) and not document["criteria"]:
            self._error("criteria", "at least one criterion is required")
        self._check_weights(criteria)
        self._check_unique_ids(document)

        if self._diagnostics:
            raise RubricError(self._diagnostics)
        assert rubric_id is not None
        assert threshold is not None
        assert variables is not None
        return Rubric(
            id=rubric_id,
            description=description,
            variables=variables,
            assumptions=assumptions,
            criteria=tuple(c for c in criteria if c is not None),
            penalties=tuple(p for p in penalties if p is not None),
            invariants=tuple(i for i in invariants if i is not None),
            exploit_threshold=threshold,
        )

    # None when any declaration is invalid. Conditions are then not type-checked, so one
    # bad variable does not also show up as an unknown name in every condition.
    def _variables(self, raw: Any) -> tuple[Variable, ...] | None:
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            self._error("variables", f"expected a table of name = type, found {_kind(raw)}")
            return None
        if not raw:
            self._error("variables", "at least one variable is required")
            return None
        before = len(self._diagnostics)
        variables: list[Variable] = []
        for name, spec in raw.items():
            variable = self._variable(name, spec)
            if variable is not None:
                variables.append(variable)
        return tuple(variables) if len(self._diagnostics) == before else None

    def _variable(self, name: Any, spec: Any) -> Variable | None:
        path = f"variables.{name}"
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in KEYWORDS:
            self._error(
                path,
                "variable names start with a letter or '_', use only letters, digits and '_' "
                "(64 characters at most), and cannot be a keyword",
            )
            return None
        if isinstance(spec, str):
            spec = {"type": spec}
        if not isinstance(spec, Mapping):
            self._error(path, f"expected a type name or a table, found {_kind(spec)}")
            return None
        self._unknown_keys(spec, VARIABLE_KEYS, path)
        type_name = spec.get("type")
        if not isinstance(type_name, str):
            self._error(f"{path}.type", "required: one of bool, int, real, bv1 ... bv64")
            return None
        sort = parse_sort(type_name)
        if sort is None:
            self._error(
                f"{path}.type", f"unknown type '{type_name}'; use bool, int, real or bv1 ... bv64"
            )
            return None
        lower = self._bound(spec, "min", sort, path)
        upper = self._bound(spec, "max", sort, path)
        if lower is not None and upper is not None and lower > upper:
            self._error(
                path,
                f"min ({format_number(lower)}) is greater than max ({format_number(upper)})",
            )
        return Variable(
            name=name,
            sort=sort,
            lower=lower,
            upper=upper,
            description=self._text(spec.get("description", ""), f"{path}.description"),
        )

    def _bound(
        self, spec: Mapping[str, Any], key: str, sort: Sort, path: str
    ) -> int | Fraction | None:
        if key not in spec:
            return None
        value = spec[key]
        where = f"{path}.{key}"
        if isinstance(sort, BoolSort):
            self._error(where, "bool variables have no bounds")
            return None
        if isinstance(sort, RealSort):
            return self._number(value, where)
        if isinstance(value, bool) or not isinstance(value, int):
            self._error(where, f"{sort} bounds must be whole numbers, found {_show(value)}")
            return None
        if not within_limits(value):
            self._error(where, TOO_LARGE)
            return None
        if isinstance(sort, IntSort):
            return value
        if not 0 <= value <= sort.max_value:
            self._error(where, f"must be between 0 and {sort.max_value} for {sort}")
            return None
        return value

    # One slot per entry; None marks an entry that had errors.
    def _entries(
        self,
        raw: Any,
        section: str,
        sorts: Mapping[str, Sort] | None,
        build: Callable[[Mapping[str, Any], str, Mapping[str, Sort] | None], _T | None],
    ) -> list[_T | None]:
        built: list[_T | None] = []
        for index, entry in enumerate(self._list(raw, section)):
            path = self._entry_path(section, index, entry)
            if not isinstance(entry, Mapping):
                self._error(path, f"expected a table, found {_kind(entry)}")
                built.append(None)
                continue
            built.append(build(entry, path, sorts))
        return built

    @staticmethod
    def _entry_path(section: str, index: int, entry: Any) -> str:
        if (
            isinstance(entry, Mapping)
            and isinstance(entry.get("id"), str)
            and _ID.fullmatch(entry["id"])
        ):
            return f'{section}["{entry["id"]}"]'
        return f"{section}[{index}]"

    def _criterion(
        self, entry: Mapping[str, Any], path: str, sorts: Mapping[str, Sort] | None
    ) -> Criterion | None:
        self._unknown_keys(entry, CRITERION_KEYS, path)
        ident = self._required_id(entry, path)
        weight = None
        if "weight" not in entry:
            self._error(f"{path}.weight", "required")
        else:
            weight = self._fraction_in_unit_interval(entry["weight"], f"{path}.weight")
        when = self._required_condition(entry, "when", path, sorts)
        description = self._text(entry.get("description", ""), f"{path}.description")
        if ident is None or weight is None or when is None:
            return None
        return Criterion(ident, weight, when, description)

    def _penalty(
        self, entry: Mapping[str, Any], path: str, sorts: Mapping[str, Sort] | None
    ) -> Penalty | None:
        self._unknown_keys(entry, PENALTY_KEYS, path)
        ident = self._required_id(entry, path)
        when = self._required_condition(entry, "when", path, sorts)
        description = self._text(entry.get("description", ""), f"{path}.description")
        has_deduct, has_zero = "deduct" in entry, "zero" in entry
        deduction: Fraction | None = None
        valid = True
        if has_deduct and has_zero:
            self._error(path, "set either 'deduct' or 'zero', not both")
            valid = False
        elif has_deduct:
            deduction = self._fraction_in_unit_interval(entry["deduct"], f"{path}.deduct")
            valid = deduction is not None
        elif has_zero:
            if entry["zero"] is not True:
                self._error(f"{path}.zero", "must be true (leave it out for a deduction)")
                valid = False
        else:
            self._error(path, "a penalty needs 'deduct = <amount>' or 'zero = true'")
            valid = False
        if ident is None or when is None or not valid:
            return None
        return Penalty(ident, when, deduction, description)

    def _invariant(
        self, entry: Mapping[str, Any], path: str, sorts: Mapping[str, Sort] | None
    ) -> Invariant | None:
        self._unknown_keys(entry, INVARIANT_KEYS, path)
        ident = self._required_id(entry, path)
        holds = self._required_condition(entry, "holds", path, sorts)
        description = self._text(entry.get("description", ""), f"{path}.description")
        if ident is None or holds is None:
            return None
        return Invariant(ident, holds, description)

    def _check_weights(self, criteria: list[Criterion | None]) -> None:
        built = [c for c in criteria if c is not None]
        if not built or len(built) != len(criteria):
            return  # a broken criterion was already reported; the sum would mislead
        total = sum((c.weight for c in built), Fraction(0))
        if total != 1:
            self._error(
                "criteria", f"weights must sum to exactly 1, they sum to {format_number(total)}"
            )

    def _check_unique_ids(self, document: Mapping[str, Any]) -> None:
        seen: dict[str, str] = {}
        for section in ("criteria", "penalties", "invariants"):
            entries = document.get(section)
            if not isinstance(entries, list | tuple):
                continue
            for index, entry in enumerate(entries):
                if not isinstance(entry, Mapping):
                    continue
                ident = entry.get("id")
                if not isinstance(ident, str):
                    continue
                path = f"{section}[{index}].id"
                if ident in seen:
                    self._error(path, f"id '{ident}' is already used at {seen[ident]}")
                else:
                    seen[ident] = path

    def _unknown_keys(self, entry: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
        for key in entry:
            if key not in allowed:
                where = f"{path}.{key}" if path else str(key)
                self._error(where, f"unknown key; expected one of: {', '.join(sorted(allowed))}")

    def _list(self, raw: Any, path: str) -> list[Any]:
        if raw is None:
            return []
        if not isinstance(raw, list | tuple):
            self._error(path, f"expected a list, found {_kind(raw)}")
            return []
        return list(raw)

    def _required_id(self, entry: Mapping[str, Any], path: str) -> str | None:
        if "id" not in entry:
            self._error(f"{path}.id", "required")
            return None
        return self._id(entry["id"], f"{path}.id")

    def _id(self, value: Any, path: str) -> str | None:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            self._error(
                path,
                "ids use letters, digits, '_', '.' and '-' (64 characters at most), "
                f"found {_show(value)}",
            )
            return None
        return value

    def _text(self, value: Any, path: str) -> str:
        if not isinstance(value, str):
            self._error(path, f"expected text, found {_kind(value)}")
            return ""
        return value

    def _required_condition(
        self, entry: Mapping[str, Any], key: str, path: str, sorts: Mapping[str, Sort] | None
    ) -> Condition | None:
        if key not in entry:
            self._error(f"{path}.{key}", "required")
            return None
        return self._condition(entry[key], f"{path}.{key}", sorts)

    def _condition(
        self, value: Any, path: str, sorts: Mapping[str, Sort] | None
    ) -> Condition | None:
        if not isinstance(value, str):
            self._error(path, f"expected an expression as text, found {_kind(value)}")
            return None
        try:
            if sorts is None:
                parse_expression(value)  # still report syntax errors
                return None
            return Condition(value, check_condition(value, sorts))
        except RubricError as exc:
            self._diagnostics.extend(d.at(path) for d in exc.diagnostics)
            return None

    def _number(self, value: Any, path: str) -> Fraction | None:
        if isinstance(value, bool):
            self._error(path, "expected a number, found true/false")
            return None
        if isinstance(value, int | Decimal):
            if isinstance(value, Decimal) and not value.is_finite():
                self._error(path, f"must be a finite number, found {value}")
                return None
            if not within_limits(value):
                self._error(path, TOO_LARGE)
                return None
            return Fraction(value)
        if isinstance(value, float):
            self._error(
                path,
                f"floats are not exact; use Decimal('{value!r}') or an int (found {value!r})",
            )
            return None
        self._error(path, f"expected a number, found {_kind(value)}")
        return None

    def _fraction_in_unit_interval(self, value: Any, path: str) -> Fraction | None:
        number = self._number(value, path)
        if number is None:
            return None
        if not 0 < number <= 1:
            self._error(
                path, f"must be greater than 0 and at most 1, found {format_number(number)}"
            )
            return None
        return number


def _show(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and not within_limits(value):
        return "a very large number"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, Decimal):
        return str(value)
    return _kind(value) if isinstance(value, Mapping | list) else repr(value)
