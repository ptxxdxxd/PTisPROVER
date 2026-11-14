"""Z3 encoding of a rubric. The only module that imports z3.

Each question is its own query on a fresh solver, budgeted in Z3 resource
units (``rlimit``) rather than seconds, so the same input gets the same answer
on any machine with the same Z3 build.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction

import z3

from ptisprover import ir
from ptisprover.exact import format_number
from ptisprover.model import Rubric, Variable
from ptisprover.sorts import BOOL, INT, REAL, BitVecSort

DEFAULT_BUDGET = 5_000_000
# Z3 reads rlimit as an unsigned 32-bit number: 2**32 would mean "no limit" and 2**32 + 1
# would mean 1.
MAX_BUDGET = 2**32 - 1


class Answer(Enum):
    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Query:
    """One solver call: what it asked, what came back, and the work it used."""

    label: str
    answer: Answer
    work: int
    smt2: str | None = None


@dataclass(frozen=True, slots=True)
class Result:
    """A query's answer. On SAT: the outcome found and the score Z3 gives it."""

    answer: Answer
    model: dict[str, ir.Value] | None = None
    score: Fraction | None = None
    core: tuple[str, ...] = ()
    irrational: bool = False


@dataclass(frozen=True, slots=True)
class Requirement:
    """A named constraint that can appear in a conflict set."""

    path: str
    requires: str
    formula: z3.BoolRef = field(compare=False)


def solver_name() -> str:
    return f"z3 {z3.get_version_string()}"


class Encoding:
    """Z3 terms for one rubric, in one private Context."""

    def __init__(self, rubric: Rubric) -> None:
        self.rubric = rubric
        self.ctx = z3.Context()
        self.variables: dict[str, z3.ExprRef] = {v.name: self._declare(v) for v in rubric.variables}
        self.bounds: list[Requirement] = [
            requirement for v in rubric.variables for requirement in self._bounds(v)
        ]
        self.assumptions: list[Requirement] = [
            Requirement(f"assume[{i}]", a.source, self.formula(a.expr))
            for i, a in enumerate(rubric.assumptions)
        ]
        self.criteria = {c.id: self.formula(c.when.expr) for c in rubric.criteria}
        self.penalties = {p.id: self.formula(p.when.expr) for p in rubric.penalties}
        self.invariants = {i.id: self.formula(i.holds.expr) for i in rubric.invariants}
        self.score = self._score()

    @property
    def domain(self) -> list[Requirement]:
        """What every admissible outcome satisfies: bounds, then assumptions."""
        return self.bounds + self.assumptions

    def criterion_pays(self, criterion_id: str) -> Requirement:
        criterion = next(c for c in self.rubric.criteria if c.id == criterion_id)
        return Requirement(
            f'criteria["{criterion_id}"]', criterion.when.source, self.criteria[criterion_id]
        )

    def penalty_stays_off(self, penalty_id: str) -> Requirement:
        penalty = next(p for p in self.rubric.penalties if p.id == penalty_id)
        return Requirement(
            f'penalties["{penalty_id}"]',
            f"not ({penalty.when.source})",
            z3.Not(self.penalties[penalty_id], self.ctx),
        )

    def rational(self, value: Fraction) -> z3.ArithRef:
        return z3.RatVal(value.numerator, value.denominator, self.ctx)

    def formula(self, expr: ir.Expr) -> z3.BoolRef:
        term = self.term(expr)
        assert z3.is_bool(term)
        return term

    def term(self, expr: ir.Expr) -> z3.ExprRef:
        ctx = self.ctx
        if isinstance(expr, ir.Var):
            return self.variables[expr.name]
        if isinstance(expr, ir.Const):
            return self._constant(expr)
        if isinstance(expr, ir.ToReal):
            return z3.ToReal(self.term(expr.arg))
        if isinstance(expr, ir.Neg):
            return -self.term(expr.arg)
        if isinstance(expr, ir.Not):
            return z3.Not(self.term(expr.arg), ctx)
        if isinstance(expr, ir.Logic):
            left, right = self.term(expr.left), self.term(expr.right)
            if expr.op == "and":
                return z3.And(left, right, ctx)
            if expr.op == "or":
                return z3.Or(left, right, ctx)
            return z3.Implies(left, right, ctx)
        left, right = self.term(expr.left), self.term(expr.right)
        if isinstance(expr, ir.Arith):
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            return left * right
        if isinstance(expr, ir.BitOp):
            if expr.op == "&":
                return left & right
            if expr.op == "|":
                return left | right
            return left ^ right
        unsigned = isinstance(expr.left.sort, BitVecSort)
        if expr.op == "==":
            return left == right
        if expr.op == "!=":
            return left != right
        if expr.op == "<":
            return z3.ULT(left, right) if unsigned else left < right
        if expr.op == "<=":
            return z3.ULE(left, right) if unsigned else left <= right
        if expr.op == ">":
            return z3.UGT(left, right) if unsigned else left > right
        return z3.UGE(left, right) if unsigned else left >= right

    def _constant(self, const: ir.Const) -> z3.ExprRef:
        value, sort = const.value, const.sort
        if sort == BOOL:
            return z3.BoolVal(value, self.ctx)
        if sort == INT:
            return z3.IntVal(value, self.ctx)
        if sort == REAL:
            assert isinstance(value, Fraction)
            return self.rational(value)
        assert isinstance(sort, BitVecSort)
        return z3.BitVecVal(value, sort.width, self.ctx)

    def _declare(self, variable: Variable) -> z3.ExprRef:
        # The prefix keeps a variable called "let", "div" or "_" from colliding with a
        # reserved word when a query is exported for another solver.
        sort, name, ctx = variable.sort, f"var.{variable.name}", self.ctx
        if sort == BOOL:
            return z3.Bool(name, ctx)
        if sort == INT:
            return z3.Int(name, ctx)
        if sort == REAL:
            return z3.Real(name, ctx)
        assert isinstance(sort, BitVecSort)
        return z3.BitVec(name, sort.width, ctx)

    def _bounds(self, variable: Variable) -> list[Requirement]:
        symbol = self.variables[variable.name]
        requirements: list[Requirement] = []
        for key, bound in (("min", variable.lower), ("max", variable.upper)):
            if bound is None:
                continue
            operator = ">=" if key == "min" else "<="
            text = f"{variable.name} {operator} {format_number(bound)}"
            if isinstance(variable.sort, BitVecSort):
                constant = z3.BitVecVal(int(bound), variable.sort.width, self.ctx)
                formula = z3.UGE(symbol, constant) if key == "min" else z3.ULE(symbol, constant)
            else:
                constant = (
                    z3.IntVal(int(bound), self.ctx)
                    if variable.sort == INT
                    else self.rational(Fraction(bound))
                )
                formula = symbol >= constant if key == "min" else symbol <= constant
            requirements.append(Requirement(f"variables.{variable.name}.{key}", text, formula))
        return requirements

    def _score(self) -> z3.ArithRef:
        zero = self.rational(Fraction(0))
        earned = _total(
            [
                z3.If(self.criteria[c.id], self.rational(c.weight), zero)
                for c in self.rubric.criteria
            ]
        )
        deductions = [
            z3.If(self.penalties[p.id], self.rational(p.deduction), zero)
            for p in self.rubric.penalties
            if p.deduction is not None
        ]
        net = earned - _total(deductions) if deductions else earned
        floored = z3.If(net < zero, zero, net)
        zeroing = [self.penalties[p.id] for p in self.rubric.penalties if p.deduction is None]
        if not zeroing:
            return floored
        return z3.If(z3.Or(*zeroing, self.ctx), zero, floored)


def _total(terms: Sequence[z3.ArithRef]) -> z3.ArithRef:
    """Sum of one or more terms. z3.Sum would print a single term as ``(+ x)``,
    which is not valid SMT-LIB and which cvc5 refuses to parse."""
    total = terms[0]
    for term in terms[1:]:
        total = total + term
    return total


class Session:
    """Runs budgeted queries against one encoding and keeps a log of them."""

    def __init__(self, encoding: Encoding, budget: int, *, keep_smt2: bool = False) -> None:
        if not 0 < budget <= MAX_BUDGET:
            raise ValueError(f"budget must be between 1 and {MAX_BUDGET} Z3 resource units")
        self.encoding = encoding
        self.budget = budget
        self.keep_smt2 = keep_smt2
        self.queries: list[Query] = []
        self._work_so_far = 0

    @property
    def work(self) -> int:
        return self._work_so_far

    def ask(
        self,
        label: str,
        constraints: Sequence[z3.BoolRef] = (),
        tracked: Sequence[Requirement] = (),
    ) -> Result:
        """Is there an outcome satisfying everything given? Tracked requirements form the core."""
        ctx = self.encoding.ctx
        solver = z3.Solver(ctx=ctx)
        solver.set("rlimit", self.budget)
        trackers: dict[str, str] = {}
        for index, requirement in enumerate(tracked):
            tracker = z3.Bool(f"req!{index}", ctx)
            trackers[str(tracker)] = requirement.path
            solver.assert_and_track(requirement.formula, tracker)
        for constraint in constraints:
            solver.add(constraint)
        smt2 = self._export([r.formula for r in tracked] + list(constraints))
        verdict = solver.check()
        # Z3 counts resource units per Context, cumulatively across solvers.
        total = int(solver.statistics().get_key_value("rlimit count"))
        work, self._work_so_far = total - self._work_so_far, total
        if verdict == z3.sat:
            answer = Answer.SAT
        elif verdict == z3.unsat:
            answer = Answer.UNSAT
        else:
            answer = Answer.UNKNOWN
        self.queries.append(Query(label, answer, work, smt2))
        if answer is Answer.UNSAT:
            core = tuple(trackers[str(t)] for t in solver.unsat_core() if str(t) in trackers)
            order = [r.path for r in tracked]
            return Result(answer, core=tuple(sorted(core, key=order.index)))
        if answer is Answer.UNKNOWN:
            return Result(answer)
        z3_model = solver.model()
        model, irrational = self._read_model(z3_model)
        score = z3_model.eval(self.encoding.score, model_completion=True)
        assert z3.is_rational_value(score)
        return Result(
            answer,
            model=model,
            score=Fraction(score.numerator_as_long(), score.denominator_as_long()),
            irrational=irrational,
        )

    def _export(self, formulas: Sequence[z3.BoolRef]) -> str | None:
        """The query as SMT-LIB2, for other solvers.

        Written from a second solver with every formula asserted plainly: Z3
        exports a tracked assertion as ``tracker => formula``, which any other
        solver can satisfy by setting the tracker to false.
        """
        if not self.keep_smt2:
            return None
        plain = z3.Solver(ctx=self.encoding.ctx)
        plain.add(*formulas)
        return "(set-logic ALL)\n" + str(plain.to_smt2())

    def _read_model(self, model: z3.ModelRef) -> tuple[dict[str, ir.Value], bool]:
        values: dict[str, ir.Value] = {}
        irrational = False
        for name, symbol in self.encoding.variables.items():
            value = model.eval(symbol, model_completion=True)
            if z3.is_true(value) or z3.is_false(value):
                values[name] = z3.is_true(value)
            elif z3.is_int_value(value) or z3.is_bv_value(value):
                values[name] = value.as_long()
            elif z3.is_rational_value(value):
                values[name] = Fraction(value.numerator_as_long(), value.denominator_as_long())
            else:
                irrational = True  # an algebraic number; not exactly representable
        return values, irrational
