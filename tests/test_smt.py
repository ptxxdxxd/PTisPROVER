"""The Z3 encoding must mean what the reference evaluator computes."""

from __future__ import annotations

from fractions import Fraction

import pytest
import z3
from hypothesis import given
from hypothesis import strategies as st

from rubric_prover import ir
from rubric_prover.evaluate import evaluate
from rubric_prover.model import Condition, Criterion, Rubric, Variable
from rubric_prover.smt import Answer, Encoding, Session
from rubric_prover.sorts import BOOL, INT, REAL, BitVecSort, Sort
from tests.strategies import typed_exprs, values_of

SORTS: list[Sort] = [BOOL, INT, REAL, BitVecSort(4)]


def rubric_over(variables: list[Variable]) -> Rubric:
    always = Condition("true", ir.Const(BOOL, True))
    return Rubric("t", tuple(variables), (Criterion("c", Fraction(1), always),), Fraction(1))


def python_value(term: z3.ExprRef) -> ir.Value:
    if z3.is_true(term) or z3.is_false(term):
        return bool(z3.is_true(term))
    if z3.is_int_value(term) or z3.is_bv_value(term):
        return int(term.as_long())
    assert z3.is_rational_value(term), term
    return Fraction(term.numerator_as_long(), term.denominator_as_long())


@given(st.data())
def test_encoding_agrees_with_the_reference_evaluator(data: st.DataObject) -> None:
    sorts = data.draw(st.lists(st.sampled_from(SORTS), min_size=1, max_size=4))
    variables = [Variable(f"v{i}", sort) for i, sort in enumerate(sorts)]
    env = tuple((v.name, v.sort) for v in variables)
    result_sort = data.draw(st.sampled_from(SORTS))
    expr = data.draw(typed_exprs(result_sort, env, 3))
    assignment = {v.name: data.draw(values_of(v.sort)) for v in variables}

    encoding = Encoding(rubric_over(variables))
    substitutions = [
        (encoding.variables[name], encoding.term(ir.Const(sort, assignment[name])))
        for name, sort in env
    ]
    term = z3.simplify(z3.substitute(encoding.term(expr), *substitutions))
    assert python_value(term) == evaluate(expr, assignment)


def test_bounds_are_named_after_their_field() -> None:
    variables = [
        Variable("x", INT, -2, 5),
        Variable("r", REAL, Fraction(-1, 2), None),
        Variable("m", BitVecSort(8), 1, 200),
    ]
    encoding = Encoding(rubric_over(variables))
    assert [(r.path, r.requires) for r in encoding.bounds] == [
        ("variables.x.min", "x >= -2"),
        ("variables.x.max", "x <= 5"),
        ("variables.r.min", "r >= -0.5"),
        ("variables.m.min", "m >= 1"),
        ("variables.m.max", "m <= 200"),
    ]


def test_bit_vector_bounds_are_unsigned() -> None:
    encoding = Encoding(rubric_over([Variable("m", BitVecSort(8), 100, None)]))
    session = Session(encoding, 10_000)
    # Read as signed 8-bit, 200 would be -56 and fail 'm >= 100'; unsigned it passes.
    result = session.ask(
        "can m be 200",
        [*(r.formula for r in encoding.bounds), encoding.variables["m"] == 200],
    )
    assert result.answer is Answer.SAT


def test_session_logs_queries_and_counts_work() -> None:
    encoding = Encoding(rubric_over([Variable("x", INT, 0, 3)]))
    session = Session(encoding, 1_000_000, keep_smt2=True)
    x = encoding.variables["x"]
    first = session.ask("x is 2", [x == 2])
    second = session.ask("x is 9", [*(r.formula for r in encoding.bounds), x == 9])
    assert (first.answer, second.answer) == (Answer.SAT, Answer.UNSAT)
    assert first.model == {"x": 2}
    assert [q.label for q in session.queries] == ["x is 2", "x is 9"]
    assert session.work == sum(q.work for q in session.queries) > 0
    assert all(q.smt2 is not None and "(check-sat)" in q.smt2 for q in session.queries)


def test_session_rejects_a_non_positive_budget() -> None:
    encoding = Encoding(rubric_over([Variable("x", INT)]))
    with pytest.raises(ValueError, match="budget must be a positive number"):
        Session(encoding, 0)


def test_unsat_core_comes_back_as_requirement_paths_in_order() -> None:
    encoding = Encoding(rubric_over([Variable("x", INT, 5, 3)]))
    result = Session(encoding, 10_000).ask("bounds", tracked=encoding.bounds)
    assert result.answer is Answer.UNSAT
    assert result.core == ("variables.x.min", "variables.x.max")


def test_irrational_models_are_flagged() -> None:
    encoding = Encoding(rubric_over([Variable("r", REAL)]))
    r = encoding.variables["r"]
    result = Session(encoding, 1_000_000).ask("r squared is 2", [r * r == 2, r > 0])
    assert result.answer is Answer.SAT
    assert result.irrational
    assert result.model == {}
