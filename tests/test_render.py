from __future__ import annotations

import base64
import dataclasses
import hashlib
import re
from fractions import Fraction

import pytest

from ptisprover.loader import load_rubric
from ptisprover.model import Rubric
from ptisprover.prover import prove
from ptisprover.render import render_html, render_text, show_value, style_hash, summary
from ptisprover.report import (
    Check,
    Conflict,
    ConflictRequirement,
    Example,
    Finding,
    Report,
    SolverStats,
    Status,
)
from tests.conftest import ORIGINAL

STATS = SolverStats("z3 test", 1000, 3, 42)


def report_of(*findings: Finding, verdict: Status = Status.PASS) -> Report:
    return Report("r", verdict, findings, STATS)


@pytest.fixture(scope="module")
def loophole() -> Rubric:
    return load_rubric(ORIGINAL / "loophole_volume.toml")


def test_show_value() -> None:
    assert [show_value(v) for v in (True, False, 7, Fraction(-3, 25), Fraction(1, 3))] == [
        "true",
        "false",
        "7",
        "-0.12",
        "1/3",
    ]


def test_summary_pluralises_and_leaves_out_zeros() -> None:
    findings = (
        Finding(Check.CRITERION, Status.FAIL, (), "m"),
        Finding(Check.CRITERION, Status.WARN, (), "m"),
        Finding(Check.CRITERION, Status.WARN, (), "m"),
        Finding(Check.CRITERION, Status.INCONCLUSIVE, (), "m"),
        Finding(Check.CRITERION, Status.SKIPPED, (), "m"),
    )
    assert summary(report_of(*findings)) == "1 failed, 1 undecided, 2 warnings, 1 skipped"


def test_text_report_shows_conflicts_and_their_minimality() -> None:
    conflict = Conflict(
        (
            ConflictRequirement("assume[0]", "x > 1"),
            ConflictRequirement("variables.x.max", "x <= 0"),
        ),
        False,
    )
    finding = Finding(Check.OUTCOMES, Status.FAIL, (), "no outcome", conflict=conflict)
    text = render_text(report_of(finding, verdict=Status.FAIL), "9.9")
    assert text.splitlines()[:5] == [
        "r: FAIL (1 failed)",
        "",
        "  FAIL       Possible outcomes: no outcome",
        "             conflict (the solver could not confirm that this set is minimal):",
        "               assume[0]        x > 1",
    ]
    assert text.splitlines()[-1] == (
        "Checked by PTisPROVER 9.9 with z3 test: 3 solver queries used 42 work units "
        "(budget 1,000 per query)."
    )


def test_html_escapes_free_text(loophole: Rubric) -> None:
    hostile = dataclasses.replace(loophole, description="<script>alert(1)</script> & co")
    html = render_html(prove(hostile).report, hostile, "9.9")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html


def test_csp_hash_matches_the_stylesheet_that_ships(loophole: Rubric) -> None:
    html = render_html(prove(loophole).report, loophole, "9.9")
    (css,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)
    digest = base64.b64encode(hashlib.sha256(css.encode("utf-8")).digest()).decode("ascii")
    assert style_hash() == f"'sha256-{digest}'"
    assert f"content=\"default-src 'none'; style-src 'sha256-{digest}'\"" in html


@pytest.mark.parametrize(
    ("verdict", "word"),
    [(Status.PASS, "Pass"), (Status.FAIL, "Fail"), (Status.INCONCLUSIVE, "Undecided")],
)
def test_html_grade(loophole: Rubric, verdict: Status, word: str) -> None:
    html = render_html(report_of(verdict=verdict), loophole, "9.9")
    assert f'<p class="grade {verdict}" aria-label="Verdict: {word.lower()}">{word}</p>' in html


def test_html_messages_are_capitalised_but_identifiers_are_not(loophole: Rubric) -> None:
    findings = (
        Finding(Check.CRITERION, Status.FAIL, ("c",), "'within_limit' pays for every outcome"),
        Finding(Check.PERFECT_SCORE, Status.FAIL, (), "no outcome can score 1"),
    )
    html = render_html(report_of(*findings, verdict=Status.FAIL), loophole, "9.9")
    assert "<p>&#x27;within_limit&#x27; pays for every outcome</p>" in html
    assert "<p>No outcome can score 1</p>" in html


def test_html_lists_the_rubric(loophole: Rubric) -> None:
    html = render_html(prove(loophole).report, loophole, "9.9")
    assert '<td>volume</td><td class="weight">0.55</td>' in html
    assert "<td>weak_risk_deduction</td><td>minus 0.1</td>" in html
    assert "Invariants (threshold 0.85)" in html
    assert "Assumed of every outcome" in html


def test_html_names_zeroing_penalties() -> None:
    rubric = load_rubric(ORIGINAL / "govcon_quote.toml")
    assert "<td>uncapped_liability</td><td>score set to 0</td>" in render_html(
        prove(rubric).report, rubric, "9.9"
    )


def test_text_report_example_lines_leave_out_empty_parts() -> None:
    bare = Example({"x": 0}, Fraction(0), (), (), ())
    full = Example({"x": 5}, Fraction(1, 2), ("c",), ("p",), ("i",))
    findings = (
        Finding(Check.EXPLOIT, Status.WARN, ("i",), "bare", example=bare),
        Finding(Check.EXPLOIT, Status.FAIL, ("i",), "full", example=full),
    )
    lines = render_text(report_of(*findings, verdict=Status.FAIL), "9.9").splitlines()
    assert lines[3:5] == ["             outcome: x = 0", "             scores 0"]
    assert lines[6:8] == [
        "             outcome: x = 5",
        "             scores 0.5; pays c; fires p; breaks i",
    ]


def test_html_shows_conflicts() -> None:
    rubric = load_rubric(ORIGINAL / "contradictory_pricing.toml")
    html = render_html(prove(rubric).report, rubric, "9.9")
    assert "<p>Removing any one of these removes the conflict:</p>" in html
    assert (
        '<tr><th scope="row">assume[0]</th><td><code>margin + discount &lt;= 0.50</code></td></tr>'
        in html
    )


def test_html_score_table_leaves_out_empty_rows(loophole: Rubric) -> None:
    example = Example({"x": 0}, Fraction(0), (), (), ("i",))
    finding = Finding(Check.EXPLOIT, Status.WARN, ("i",), "m", example=example)
    html = render_html(report_of(finding), loophole, "9.9")
    assert '<table class="scores"><tr><th scope="row">Score</th><td>0</td></tr>' in html
    assert ">Pays<" not in html


def test_html_rubric_sections_appear_only_when_present() -> None:
    rubric = dataclasses.replace(
        load_rubric(ORIGINAL / "redundant_latency.toml"), invariants=(), assumptions=()
    )
    html = render_html(prove(rubric).report, rubric, "9.9")
    assert '<h2 id="criteria">Criteria</h2>' in html
    for heading in ("Penalties", "Invariants", "Assumed of every outcome"):
        assert heading not in html
