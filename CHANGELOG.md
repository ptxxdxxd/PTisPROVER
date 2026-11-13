# Changelog

## Unreleased

First version.

- Rubric files in TOML or JSON, with exact decimals and a JSON Schema.
- Condition expressions with a type checker; errors report the field, line and column.
- Checks: possible outcomes, perfect score (with an irreducible conflict), reward hacking
  (worst score while breaking each invariant), criterion range, overlapping criteria,
  penalty range.
- Results are pass, warn, fail, inconclusive or skipped. An undecided question is never a pass.
- Solver budgets in Z3 resource units, so reports are reproducible across machines.
- Every solver outcome is replayed through a separate reference evaluator.
- `rubric-prover check` with text, JSON and HTML reports and CI exit codes;
  `rubric-prover schema`.
- `--emit-smt2` and `scripts/cross_check.py` to re-solve every query with cvc5.
- Five example rubrics for grading model outputs.
