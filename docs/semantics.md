# Semantics

What a rubric means, and the exact question behind each check.

## Outcomes

A rubric declares variables. An **outcome** gives every variable a value of its type:

| Type | Values |
|---|---|
| `bool` | true, false |
| `int` | mathematical integers |
| `real` | mathematical reals (rationals in every counterexample that is reported) |
| `bvN` | integers from 0 to 2^N − 1, compared as unsigned |

An outcome is **admissible** when it is within every `min` and `max` and satisfies every
condition in `assume`. All checks quantify over admissible outcomes only. Write *D* for
"the outcome is admissible".

## Score

For an outcome, a criterion **pays** when its `when` condition is true and a penalty **fires**
when its `when` condition is true.

```text
score = 0                                   if any penalty with zero = true fires
score = max(0, earned − deducted)           otherwise

earned   = sum of the weights of the criteria that pay
deducted = sum of the deductions of the penalties that fire
```

Weights are greater than 0 and sum to exactly 1, and deductions are greater than 0, so the
score lies in [0, 1], and it equals 1 exactly when every criterion pays and no penalty fires.

All arithmetic is exact: numbers in a rubric file are read as decimals and held as fractions.

## Expressions

Loosest to tightest: `implies` (right-associative), `or`, `and`, `not`, comparisons
(`== != < <= > >=`, which cannot be chained), `|`, `^`, `&`, `+ -`, `*`, unary `-`.
This is Python's order, so `flags & 3 == 3` means `(flags & 3) == 3`.

Typing rules:

- `and`, `or`, `not`, `implies` take bools.
- `+ - *` and unary `-` take `int` or `real`. An `int` meeting a `real` is widened; a `real`
  is never narrowed.
- `& | ^` take bit-vectors of one width. There is no arithmetic on bit-vectors, because it
  would wrap around silently.
- An integer literal takes the type of the operand it meets, and must fit if that is a
  bit-vector. A decimal literal is a `real`.
- There is no division.
- An expression can be at most 10,000 characters long, with at most 200 levels of nested or
  chained operators (a chain such as `a or b or c` counts one level per operator) and number
  literals of at most 100 characters.

## Checks

Each question below is one solver query: "is there an outcome such that …". The solver
answers **sat** (with an outcome), **unsat** (a proof that none exists) or **unknown** (the
budget ran out). Before an outcome is reported or used to settle a question, it is re-scored
by the reference evaluator, which must agree that the outcome is admissible, that it has the
property asked for, and on its score. The one sat answer used without this replay is inside
conflict shrinking (below), where it only decides that an item stays in the conflict.

An outcome found for one question can settle a later "is there an outcome such that …"
question without another query, if it happens to have the property asked for.

### Possible outcomes

Query: *D*.

- sat: pass.
- unsat: fail, with a conflict (see below). Every other check is skipped, since any statement
  about "every admissible outcome" would be true for the wrong reason.

### Perfect score

Query: *D*, and every criterion pays, and no penalty fires.

- sat: pass.
- unsat: fail, with a conflict.

### Reward hacking

For each invariant *I*, with threshold *t* = `exploit_threshold`:

1. Query: *D* and not *I*. If unsat, *I* cannot be broken: pass.
2. Otherwise let *s* be the score of the outcome found. Query: *D* and not *I* and
   score > *s*. While this is sat, replace *s* with the new outcome's score and ask again.
3. When the query is unsat, *s* is the highest score any outcome breaking *I* can get.

The loop ends because a score is determined by which criteria pay and which penalties fire,
so only finitely many scores exist, and each step is strictly higher. It is also capped at
64 steps.

- *s* ≥ *t*: fail, whether or not the maximum was proven. The outcome shown reaches *s*.
- *s* < *t* and the maximum is proven: pass.
- *s* < *t* and the search stopped for any other reason (an unknown answer, an irrational
  outcome, or the step cap): inconclusive, and the message says which.

With no invariants this check has nothing to ask. That is reported as a warning, not a pass.

### Criterion range

For each criterion *c*, two queries: *D* and *c* pays; *D* and *c* does not pay.

- The first is unsat: fail, *c* can never pay.
- The second is unsat: fail, *c* pays for every admissible outcome (free reward).

### Overlapping criteria

For each ordered pair (*a*, *b*) of criteria that passed the range check, query: *D* and *a*
pays and *b* does not.

- unsat: whenever *a* pays, *b* pays. Warning.
- unsat in both directions: *a* and *b* pay for exactly the same outcomes. Warning.

These are warnings because graded tiers ("at least 1 step", "at least 3 steps") are a
legitimate design, and the tool cannot tell a tier from an accident.

### Penalty range

For each penalty *p*, two queries: *D* and *p* fires; *D* and *p* does not fire.

- The second is unsat: fail, *p* fires for every admissible outcome.
- The first is unsat: warning, *p* never fires.

## Conflicts

When a query is unsat, the solver names a subset of the requirements that already conflict.
That subset is then shrunk: each item is removed in turn, and stays removed if the rest still
conflict. The result is **irreducible**: removing any single item makes the rest satisfiable.
It is not guaranteed to be the conflict with the fewest items. If a removal query comes back
unknown, the item is kept and the conflict is marked as possibly not minimal.

Items are named by where they come from in the rubric file: `variables.x.max`, `assume[0]`,
`criteria["c"]`, `penalties["p"]`.

## Undecided questions

A question that comes back unknown is never counted as passed. Its status follows the problem
it could be hiding:

- If the hidden problem would be a failure (a dead or free criterion, an unreachable perfect
  score, an exploit, a penalty that always fires), the finding is **inconclusive**, and so is
  the verdict unless something else failed.
- If it would only be a warning (an overlap, a penalty that never fires), the finding is a
  warning that says the question was not decided.

A question can be left undecided for three reasons, and the message names the one that
applied: the budget ran out; the solver's outcome has an irrational value (possible with
nonlinear real arithmetic), which cannot be re-scored exactly and so is not used; or the
exploit search reached its step cap.

## Budgets and reproducibility

Each query runs on a fresh Z3 solver with a limit on Z3's resource counter (`rlimit`). The
counter measures solver work, not time, so the same rubric with the same Z3 build gives the
same answers, and the same report byte for byte, on any machine. `z3-solver` is pinned to an
exact version for this reason: a different build may count work differently, and a query near
the budget could change from decided to unknown.

`--budget` accepts 1 to 4,294,967,295, the range of Z3's counter. Raising it can decide a
question that was undecided for lack of budget. It does not help with the other two causes
above, and it cannot change a decided result.

Reproducibility has been checked on Linux x86-64 with Python 3.11, 3.12 and 3.13. Whether
Z3's builds for other platforms count work identically is untested.

## Verdict and exit code

| Verdict | When | Exit code |
|---|---|---|
| fail | any finding failed | 1 |
| inconclusive | no failures, at least one inconclusive finding | 2 |
| pass | otherwise (warnings allowed unless `--fail-on-warning`) | 0 |
