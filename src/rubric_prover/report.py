"""Results of checking a rubric, and their JSON form."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Any

from rubric_prover import ir
from rubric_prover.exact import format_number


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"


class Check(StrEnum):
    OUTCOMES = "outcomes-exist"
    PERFECT_SCORE = "perfect-score"
    EXPLOIT = "exploit"
    CRITERION = "criterion-range"
    OVERLAP = "criterion-overlap"
    PENALTY = "penalty-range"


@dataclass(frozen=True, slots=True)
class Example:
    """A concrete outcome, as scored by the reference evaluator."""

    assignment: Mapping[str, ir.Value]
    score: Fraction
    paying: tuple[str, ...]
    firing: tuple[str, ...]
    broken: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConflictItem:
    path: str
    requires: str


@dataclass(frozen=True, slots=True)
class Conflict:
    """Requirements that cannot all hold. ``minimal``: dropping any one makes them satisfiable."""

    items: tuple[ConflictItem, ...]
    minimal: bool


@dataclass(frozen=True, slots=True)
class Finding:
    check: Check
    status: Status
    subjects: tuple[str, ...]
    message: str
    example: Example | None = None
    conflict: Conflict | None = None
    max_score: Fraction | None = None
    max_proven: bool | None = None


@dataclass(frozen=True, slots=True)
class SolverStats:
    solver: str
    budget_per_query: int
    queries: int
    work: int


@dataclass(frozen=True, slots=True)
class Report:
    rubric_id: str
    verdict: Status
    findings: tuple[Finding, ...]
    solver: SolverStats

    def counts(self) -> dict[Status, int]:
        return {s: sum(1 for f in self.findings if f.status is s) for s in Status}

    def to_dict(self) -> dict[str, Any]:
        return {
            "rubric": self.rubric_id,
            "verdict": str(self.verdict),
            "counts": {str(s): n for s, n in self.counts().items()},
            "solver": {
                "name": self.solver.solver,
                "budget_per_query": self.solver.budget_per_query,
                "queries": self.solver.queries,
                "work": self.solver.work,
            },
            "findings": [_finding(f) for f in self.findings],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"


def verdict_of(findings: tuple[Finding, ...]) -> Status:
    """FAIL if anything failed; else INCONCLUSIVE if anything is undecided; else PASS."""
    statuses = {f.status for f in findings}
    if Status.FAIL in statuses:
        return Status.FAIL
    if Status.INCONCLUSIVE in statuses:
        return Status.INCONCLUSIVE
    return Status.PASS


def json_value(value: ir.Value) -> bool | int | str:
    """Exact JSON form: bools and integers as is, reals as decimal or 'p/q' text."""
    if isinstance(value, bool | int):
        return value
    return format_number(value)


def _finding(finding: Finding) -> dict[str, Any]:
    out: dict[str, Any] = {
        "check": str(finding.check),
        "status": str(finding.status),
        "subjects": list(finding.subjects),
        "message": finding.message,
    }
    if finding.max_score is not None:
        out["max_score"] = format_number(finding.max_score)
        out["max_proven"] = finding.max_proven
    if finding.conflict is not None:
        out["conflict"] = {
            "minimal": finding.conflict.minimal,
            "items": [{"path": i.path, "requires": i.requires} for i in finding.conflict.items],
        }
    if finding.example is not None:
        example = finding.example
        out["example"] = {
            "outcome": {name: json_value(v) for name, v in example.assignment.items()},
            "score": format_number(example.score),
            "paying": list(example.paying),
            "firing": list(example.firing),
            "broken": list(example.broken),
        }
    return out
