"""The JSON Schema for rubric files, shipped with the package."""

from __future__ import annotations

from importlib.resources import files


def rubric_schema_text() -> str:
    return files("ptisprover").joinpath("rubric.schema.json").read_text(encoding="utf-8")
