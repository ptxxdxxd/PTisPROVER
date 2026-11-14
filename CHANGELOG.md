# Changelog

## Unreleased

First version, developed under the working name rubric-prover.

- Rubric files in TOML or JSON, with exact decimals and a JSON Schema.
- Condition expressions with a type checker; errors report the field, line and column.
- Checks: possible outcomes, perfect score (with an irreducible conflict), reward hacking
  (worst score while breaking each invariant), criterion range, overlapping criteria,
  penalty range.
- Results are pass, warn, fail, inconclusive or skipped. An undecided question is never a pass.
- Solver budgets in Z3 resource units, so reports are reproducible across machines.
- Every reported outcome is replayed through a separate reference evaluator.
- `ptisprover check` with text, JSON and HTML reports and CI exit codes;
  `ptisprover schema`.
- `--emit-smt2` and `scripts/cross_check.py` to re-solve every query with cvc5.
- Five example rubrics for grading model outputs.

Changed after an independent review of the first complete version:

- Invalid input no longer produces a traceback and exit code 1. Undecodable files, numbers
  beyond 100 digits, deeply nested data and unusable output paths are input errors (exit 3);
  anything unexpected is an internal error (exit 4).
- `--budget` is limited to the range Z3 can count (it used to wrap around above 2^32 - 1).
- Variables are prefixed in exported SMT-LIB2, so names such as `let` or `div` are valid there.
- A flat chain of operators is no longer reported as "nested"; the limit is 200 levels.
- Undecided findings say whether the cause was the budget, an irrational outcome or the
  step cap.
- Bit-vector bounds, the parser and the type checker are covered by a second differential
  test whose evaluator shares no code with the package.
