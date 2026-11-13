from __future__ import annotations

import json
from fractions import Fraction

from rubric_prover.loader import load_rubric
from rubric_prover.prover import prove
from rubric_prover.report import (
    Check,
    Finding,
    Status,
    json_value,
    verdict_of,
)
from tests.conftest import ORIGINAL


def finding(status: Status) -> Finding:
    return Finding(Check.CRITERION, status, ("c",), "m")


def test_verdict_precedence() -> None:
    assert verdict_of(()) is Status.PASS
    assert verdict_of((finding(Status.PASS), finding(Status.WARN))) is Status.PASS
    assert verdict_of((finding(Status.WARN), finding(Status.INCONCLUSIVE))) is Status.INCONCLUSIVE
    assert verdict_of((finding(Status.INCONCLUSIVE), finding(Status.FAIL))) is Status.FAIL
    assert verdict_of((finding(Status.SKIPPED),)) is Status.PASS


def test_json_values_are_exact() -> None:
    assert json_value(True) is True
    assert json_value(-3) == -3
    assert json_value(Fraction(-3, 25)) == "-0.12"
    assert json_value(Fraction(1, 3)) == "1/3"


def test_report_json_for_the_loophole_fixture() -> None:
    report = prove(load_rubric(ORIGINAL / "loophole_volume.toml"))
    data = json.loads(report.to_json())
    assert list(data) == ["rubric", "verdict", "counts", "solver", "findings"]
    assert data["rubric"] == "loophole-volume"
    assert data["verdict"] == "fail"
    assert data["counts"] == {"pass": 6, "warn": 0, "fail": 2, "inconclusive": 0, "skipped": 0}
    assert set(data["solver"]) == {"name", "budget_per_query", "queries", "work"}
    exploit = data["findings"][2]
    assert exploit == {
        "check": "exploit",
        "status": "fail",
        "subjects": ["positive_margin"],
        "message": "breaking 'positive_margin' can still score 0.9, at or above the threshold "
        "0.85; nothing that breaks it scores higher",
        "max_score": "0.9",
        "max_proven": True,
        "example": {
            "outcome": {
                "deal_volume_usd": "750000",
                "quote_latency_ms": 100,
                "net_margin": "-0.12",
                "uncapped_liability": 1,
            },
            "score": "0.9",
            "paying": ["volume", "speed"],
            "firing": ["weak_risk_deduction"],
            "broken": ["positive_margin", "no_uncapped_liability"],
        },
    }


def test_report_json_includes_conflicts() -> None:
    data = json.loads(prove(load_rubric(ORIGINAL / "contradictory_pricing.toml")).to_json())
    perfect = data["findings"][1]
    assert perfect["status"] == "fail"
    assert perfect["conflict"] == {
        "minimal": True,
        "items": [
            {"path": "assume[0]", "requires": "margin + discount <= 0.50"},
            {"path": 'criteria["high_margin"]', "requires": "margin >= 0.25"},
            {"path": 'criteria["aggressive_discount"]', "requires": "discount >= 0.30"},
        ],
    }
