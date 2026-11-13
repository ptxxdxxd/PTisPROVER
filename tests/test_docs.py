"""The README's measured parts are current, and its constants match the code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rubric_prover import cli, lexer, parser, prover
from rubric_prover.smt import DEFAULT_BUDGET

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_generated_parts_of_the_readme_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_readme.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_readme_states_the_default_budget() -> None:
    assert f"(default {DEFAULT_BUDGET:,})" in README


def test_readme_exit_code_table_matches_the_cli() -> None:
    for code, meaning in [
        (cli.EXIT_PASS, "pass"),
        (cli.EXIT_FAIL, "fail"),
        (cli.EXIT_INCONCLUSIVE, "inconclusive"),
        (cli.EXIT_INPUT, "the rubric file or the command line is invalid"),
        (cli.EXIT_INTERNAL, "internal error"),
    ]:
        assert f"| {code} | {meaning}" in README


def test_readme_error_example_is_what_the_loader_prints(tmp_path: Path) -> None:
    rubric = tmp_path / "rubric.toml"
    rubric.write_text(
        'id = "r"\nexploit_threshold = 1\n[variables]\ntests_passed = "real"\n'
        '[[criteria]]\nid = "tests_pass"\nweight = 1\nwhen = "tests_passed = 1"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "rubric_prover", "check", "rubric.toml"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == cli.EXIT_INPUT
    assert result.stderr.rstrip("\n") in README


def test_readme_python_example_runs() -> None:
    start = README.index("from rubric_prover import load_rubric")
    snippet = README[start : README.index("```", start)]
    result = subprocess.run(
        [sys.executable, "-c", snippet], capture_output=True, text=True, check=False, cwd=ROOT
    )
    assert (result.returncode, result.stdout) == (0, "fail\n"), result.stderr


def test_semantics_document_states_the_limits_in_the_code() -> None:
    semantics = (ROOT / "docs" / "semantics.md").read_text(encoding="utf-8")
    assert f"capped at\n{prover.MAX_STRENGTHENING_STEPS} steps" in semantics
    assert (
        f"at most {lexer.MAX_EXPRESSION_LENGTH:,} characters long and "
        f"{parser.MAX_DEPTH} levels deep" in semantics
    )
