"""The author's tag appears where a person signs, and nowhere a rubric's results appear."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ptisprover.cli import main
from ptisprover.signature import AUTHOR, TAG
from tests.repo_paths import ROOT

EXAMPLE = str(ROOT / "examples" / "coding_agent.toml")
# A line of the drawing that no report, schema or query could contain by accident.
MARK = "|  ()   ()  |"


def test_the_tag_carries_the_author_name() -> None:
    assert MARK in TAG
    assert TAG.splitlines()[-1].strip() == AUTHOR


def test_the_readme_copy_is_identical() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- signature:start -->\n```text\n(.*?)\n```\n<!-- signature:end -->\n\Z",
        readme,
        re.DOTALL,
    )
    assert match is not None, "README.md must end with the signature block"
    assert match.group(1) == TAG


def test_help_ends_with_the_tag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.rstrip("\n").endswith(TAG)


@pytest.mark.parametrize(
    "argv",
    [
        ["check", EXAMPLE],
        ["check", EXAMPLE, "--format", "json"],
        ["check", EXAMPLE, "--format", "html"],
        ["schema"],
    ],
    ids=["text", "json", "html", "schema"],
)
def test_output_about_a_rubric_is_unsigned(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    main(argv)
    out = capsys.readouterr().out
    assert out
    assert MARK not in out
    assert AUTHOR not in out


def test_exported_queries_are_unsigned(tmp_path: Path) -> None:
    main(["check", EXAMPLE, "--emit-smt2", str(tmp_path)])
    queries = sorted(tmp_path.glob("query-*.smt2"))
    assert queries
    for query in queries:
        text = query.read_text(encoding="utf-8")
        assert MARK not in text
        assert AUTHOR not in text
