# rubric-prover

Find reward hacks, dead criteria and contradictions in a grading rubric before you train or evaluate with it.

**Status: under construction.** Nothing below the version flag works yet.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
ruff check . && ruff format --check . && mypy && pytest --cov
```
