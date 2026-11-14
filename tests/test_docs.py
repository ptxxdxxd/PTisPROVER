"""The README's measured parts are current, and its constants match the code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ptisprover import cli, exact, lexer, parser, prover, smt
from ptisprover.smt import DEFAULT_BUDGET

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_generated_parts_of_the_readme_are_current() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_readme.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_readme_states_the_default_budget() -> None:
    assert f"(default {DEFAULT_BUDGET:,})" in README


def test_readme_exit_code_table_matches_the_cli() -> None:
    for code, meaning in [
        (cli.EXIT_PASS, "pass"),
        (cli.EXIT_FAIL, "fail"),
        (cli.EXIT_INCONCLUSIVE, "inconclusive"),
        (cli.EXIT_INPUT, "the rubric file or the command line is invalid"),
        (cli.EXIT_INTERNAL, "internal error: a bug in this tool"),
    ]:
        assert f"| {code} | {meaning}" in README


def test_readme_error_example_is_what_the_loader_prints(tmp_path: Path) -> None:
    rubric = tmp_path / "rubric.toml"
    rubric.write_text(
        'id = "r"\nexploit_threshold = 1\n[variables]\ntests_passed = "real"\n'
        '[[criteria]]\nid = "tests_pass"\nweight = 1\nwhen = "tests_passed = 1"\n',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-m", "ptisprover", "check", "rubric.toml"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert completed.returncode == cli.EXIT_INPUT
    assert completed.stderr.rstrip("\n") in README


def test_readme_python_example_runs() -> None:
    start = README.index("from ptisprover import load_rubric")
    snippet = README[start : README.index("```", start)]
    completed = subprocess.run(
        [sys.executable, "-c", snippet], capture_output=True, text=True, check=False, cwd=ROOT
    )
    assert (completed.returncode, completed.stdout) == (0, "fail\n"), completed.stderr


def test_semantics_document_states_the_limits_in_the_code() -> None:
    semantics = (ROOT / "docs" / "semantics.md").read_text(encoding="utf-8")
    assert f"capped at\n{prover.MAX_STRENGTHENING_STEPS} steps" in semantics
    assert f"at most {lexer.MAX_EXPRESSION_LENGTH:,} characters long" in semantics
    assert f"at most {parser.MAX_DEPTH} levels of nested" in semantics
    assert f"literals of at most {exact.MAX_DIGITS} characters" in semantics
    assert f"accepts 1 to {smt.MAX_BUDGET:,}" in semantics
