"""The JSON Schema for rubric files, shipped with the package."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


def rubric_schema_text() -> str:
    return files("rubric_prover").joinpath("rubric.schema.json").read_text(encoding="utf-8")


def rubric_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(rubric_schema_text())
    return schema
