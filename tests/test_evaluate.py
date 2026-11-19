from __future__ import annotations

from fractions import Fraction

import pytest

from ptisprover import ir
from ptisprover.evaluate import assess, evaluate, validate_assignment
from ptisprover.loader import load_rubric, loads_toml
from ptisprover.model import Rubric
from ptisprover.sorts import INT, REAL, BitVecSort, Sort
from ptisprover.typecheck import check_condition
from tests.repo_paths import ORIGINAL

F = Fraction


@pytest.fixture(scope="module")
def govcon() -> Rubric:
    return load_rubric(ORIGINAL / "govcon_quote.toml")


@pytest.fixture(scope="module")
def loophole() -> Rubric:
    return load_rubric(ORIGINAL / "loophole_volume.toml")


@pytest.fixture(scope="module")
def redundant() -> Rubric:
    return load_rubric(ORIGINAL / "redundant_latency.toml")


@pytest.fixture(scope="module")
def contradictory() -> Rubric:
    return load_rubric(ORIGINAL / "contradictory_pricing.toml")


def test_govcon_everything_pays(govcon: Rubric) -> None:
    assessment = assess(
        govcon,
        {
            "net_margin": F("0.20"),
            "delivery_days": 20,
            "compliance_bits": 0b111,
            "uncapped_liability": 0,
            "debarred_subcontractor": False,
        },
    )
    # 0.35 + 0.35 + 0.30 = 1.00
    assert assessment.score == 1
    assert assessment.paying == ("target_margin", "fast_delivery", "full_compliance")
    assert assessment.firing == ()
    assert assessment.broken == ()
    assert assessment.admissible


def test_govcon_partial_credit(govcon: Rubric) -> None:
    # margin 0.10 < 0.18 fails; 20 <= 30 pays 0.35; 0xFF & 0x07 == 0x07 pays 0.30
    # 0.35 + 0.30 = 0.65. Margin 0.10 also breaks the 0.12 floor.
    assessment = assess(
        govcon,
        {
            "net_margin": F("0.10"),
            "delivery_days": 20,
            "compliance_bits": 0xFF,
            "uncapped_liability": 0,
            "debarred_subcontractor": False,
        },
    )
    assert assessment.score == F("0.65")
    assert assessment.broken == ("margin_floor",)


def test_govcon_zeroing_penalty_overrides_full_credit(govcon: Rubric) -> None:
    # All three criteria pay (1.00), but a debarred subcontractor zeroes the score.
    assessment = assess(
        govcon,
        {
            "net_margin": F("0.20"),
            "delivery_days": 20,
            "compliance_bits": 0b111,
            "uncapped_liability": 0,
            "debarred_subcontractor": True,
        },
    )
    assert assessment.paying == ("target_margin", "fast_delivery", "full_compliance")
    assert assessment.firing == ("debarred_vendor",)
    assert assessment.score == 0


def test_govcon_assumption_and_bounds(govcon: Rubric) -> None:
    outcome: dict[str, ir.Value] = {
        "net_margin": F("-0.30"),  # inside [-0.50, 0.60] but below the assumed -0.25
        "delivery_days": 121,  # above max 120
        "compliance_bits": 0,
        "uncapped_liability": 0,
        "debarred_subcontractor": False,
    }
    assessment = assess(govcon, outcome)
    assert not assessment.in_bounds
    assert not assessment.assumptions_hold
    assert not assessment.admissible


def test_loophole_exploit_from_the_original_fixture(loophole: Rubric) -> None:
    # volume 750000 >= 500000 pays 0.55; latency 100 <= 250 pays 0.45; sum 1.00.
    # uncapped liability fires the 0.10 deduction: 1.00 - 0.10 = 0.90.
    assessment = assess(
        loophole,
        {
            "deal_volume_usd": 750000,
            "quote_latency_ms": 100,
            "net_margin": F("-0.12"),
            "uncapped_liability": 1,
        },
    )
    assert assessment.score == F("0.90")
    assert assessment.firing == ("weak_risk_deduction",)
    assert assessment.broken == ("positive_margin", "no_uncapped_liability")
    assert assessment.admissible


def test_redundant_latency_tiers(redundant: Rubric) -> None:
    # 40 <= 50 and 40 <= 100 and 0.95 >= 0.92: 0.40 + 0.30 + 0.30 = 1.00
    assert assess(redundant, {"response_latency_ms": 40, "accuracy": F("0.95")}).score == 1
    # 80 > 50 but 80 <= 100, accurate: 0.30 + 0.30 = 0.60
    assert assess(redundant, {"response_latency_ms": 80, "accuracy": F("0.95")}).score == F("0.60")
    # 80 <= 100 only: 0.30
    assert assess(redundant, {"response_latency_ms": 80, "accuracy": F("0.91")}).score == F("0.30")


def test_contradictory_pricing_boundary(contradictory: Rubric) -> None:
    # margin 0.25 >= 0.25 pays 0.50; discount 0.25 < 0.30 does not.
    # Assumption: 0.25 + 0.25 = 0.50 <= 0.50 holds.
    assessment = assess(contradictory, {"margin": F("0.25"), "discount": F("0.25")})
    assert assessment.score == F("0.50")
    assert assessment.admissible


def test_score_floors_at_zero() -> None:
    rubric = loads_toml(
        """
        id = "floor"
        exploit_threshold = 0.5
        [variables]
        x = "int"
        [[criteria]]
        id = "small"
        weight = 0.3
        when = "x > 0"
        [[criteria]]
        id = "rest"
        weight = 0.7
        when = "x > 100"
        [[penalties]]
        id = "big"
        deduct = 0.5
        when = "x > 0"
        """
    )
    # x = 1: 0.3 earned, 0.5 deducted, 0.3 - 0.5 = -0.2, floored to 0.
    assert assess(rubric, {"x": 1}).score == 0
    # x = 101: 0.3 + 0.7 - 0.5 = 0.5
    assert assess(rubric, {"x": 101}).score == F("0.5")


EVALUATION_SORTS: dict[str, Sort] = {"i": INT, "q": REAL, "m": BitVecSort(8), "p": INT}


@pytest.mark.parametrize(
    ("text", "env", "expected"),
    [
        ("i + q == 2.5", {"i": 2, "q": F(1, 2)}, True),
        ("i * i - 3 == 6", {"i": 3}, True),
        ("-i == 0 - i", {"i": 7}, True),
        ("q * 3 == 1", {"q": F(1, 3)}, True),
        ("i >= 0.5", {"i": 0}, False),
        ("m & 0x0F == 0x0A", {"m": 0xFA}, True),
        ("m | 0x01 == 0x01", {"m": 0}, True),
        ("m ^ 0xFF == 0", {"m": 0xFF}, True),
        ("m > 127", {"m": 200}, True),  # unsigned: 200 > 127
        ("i < p", {"i": 1, "p": 2}, True),
        ("i > p", {"i": 1, "p": 2}, False),
        ("i <= p and i != p", {"i": 1, "p": 2}, True),
        ("i > 0 implies p > 0", {"i": 0, "p": -1}, True),
        ("i > 0 implies p > 0", {"i": 1, "p": -1}, False),
        ("i > 0 or p > 0", {"i": 0, "p": 0}, False),
        ("not (i == p)", {"i": 0, "p": 0}, False),
    ],
)
def test_operators(text: str, env: dict[str, ir.Value], expected: bool) -> None:
    full: dict[str, ir.Value] = {"i": 0, "q": F(0), "m": 0, "p": 0, **env}
    assert evaluate(check_condition(text, EVALUATION_SORTS), full) is expected


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"response_latency_ms": 40}, "no value for: accuracy"),
        ({"response_latency_ms": True, "accuracy": F(1)}, "response_latency_ms: True is not"),
        ({"response_latency_ms": 40, "accuracy": 0.5}, "accuracy: 0.5 is not a valid real"),
        ({"response_latency_ms": "40", "accuracy": F(1)}, "response_latency_ms: '40' is not"),
    ],
)
def test_malformed_assignments_are_programming_errors(
    redundant: Rubric, env: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_assignment(redundant, env)  # type: ignore[arg-type]  # wrong on purpose


def test_assignment_type_checks_for_bool_and_bitvectors(govcon: Rubric) -> None:
    good = {
        "net_margin": 0,  # an int is accepted for a real and stored as a Fraction
        "delivery_days": 1,
        "compliance_bits": 255,
        "uncapped_liability": 1,
        "debarred_subcontractor": False,
    }
    checked = validate_assignment(govcon, good)
    assert checked["net_margin"] == F(0)
    assert isinstance(checked["net_margin"], Fraction)
    for name, bad in [
        ("debarred_subcontractor", 0),
        ("compliance_bits", 256),
        ("uncapped_liability", -1),
        ("compliance_bits", True),
    ]:
        with pytest.raises(ValueError, match=name):
            validate_assignment(govcon, {**good, name: bad})


def test_evaluator_rejects_values_of_the_wrong_kind() -> None:
    with pytest.raises(TypeError, match="expected a bool"):
        evaluate(ir.Not(ir.Const(INT, 1)), {})
    with pytest.raises(TypeError, match="expected a number"):
        evaluate(ir.Neg(ir.Var("b", INT)), {"b": True})
    with pytest.raises(TypeError, match="expected a bit-vector value"):
        evaluate(
            ir.BitOp("&", ir.Var("m", BitVecSort(8)), ir.Const(BitVecSort(8), 1)), {"m": F(1, 2)}
        )


def test_bit_vector_bounds_are_enforced_on_both_sides() -> None:
    rubric = loads_toml(
        'id = "b"\nexploit_threshold = 1\n'
        '[variables]\nlevel = { type = "bv8", min = 10, max = 200 }\n'
        '[[criteria]]\nid = "c"\nweight = 1\nwhen = "level > 0"\n'
    )
    assert [assess(rubric, {"level": v}).in_bounds for v in (9, 10, 200, 201)] == [
        False,
        True,
        True,
        False,
    ]
