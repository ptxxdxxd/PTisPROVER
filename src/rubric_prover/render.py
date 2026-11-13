"""Human-readable reports: terminal text and a self-contained HTML page."""

from __future__ import annotations

import base64
import hashlib
from html import escape

from rubric_prover import ir
from rubric_prover.exact import format_number
from rubric_prover.model import Rubric
from rubric_prover.report import Check, Example, Finding, Report, Status

CHECK_NAMES: dict[Check, str] = {
    Check.OUTCOMES: "Possible outcomes",
    Check.PERFECT_SCORE: "Perfect score",
    Check.EXPLOIT: "Reward hacking",
    Check.CRITERION: "Criterion range",
    Check.OVERLAP: "Overlapping criteria",
    Check.PENALTY: "Penalty range",
}

_VERDICT_WORDS = {Status.PASS: "Pass", Status.FAIL: "Fail", Status.INCONCLUSIVE: "Undecided"}


def show_value(value: ir.Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return format_number(value)


def summary(report: Report) -> str:
    """'2 failed, 1 warning, 6 passed' (zero counts left out)."""
    counts = report.counts()
    parts = []
    for status, singular, plural in (
        (Status.FAIL, "failed", "failed"),
        (Status.INCONCLUSIVE, "undecided", "undecided"),
        (Status.WARN, "warning", "warnings"),
        (Status.PASS, "passed", "passed"),
        (Status.SKIPPED, "skipped", "skipped"),
    ):
        n = counts[status]
        if n:
            parts.append(f"{n} {singular if n == 1 else plural}")
    return ", ".join(parts)


def solver_line(report: Report, version: str) -> str:
    stats = report.solver
    return (
        f"Checked by rubric-prover {version} with {stats.solver}: {stats.queries} solver "
        f"queries used {stats.work:,} work units (budget {stats.budget_per_query:,} per query)."
    )


def _sentence(message: str) -> str:
    """Capitalise a message that starts with a word; never touch a quoted identifier."""
    return message[:1].upper() + message[1:] if message[:1].islower() else message


def conflict_note(minimal: bool) -> str:
    if minimal:
        return "removing any one of these removes the conflict"
    return "the solver could not confirm that this set is minimal"


def _score_rows(example: Example) -> list[tuple[str, str]]:
    rows = [("Score", format_number(example.score))]
    for label, ids in (
        ("Pays", example.paying),
        ("Fires", example.firing),
        ("Breaks", example.broken),
    ):
        if ids:
            rows.append((label, ", ".join(ids)))
    return rows


def _scores_line(example: Example) -> str:
    parts = [f"scores {format_number(example.score)}"]
    if example.paying:
        parts.append("pays " + ", ".join(example.paying))
    if example.firing:
        parts.append("fires " + ", ".join(example.firing))
    if example.broken:
        parts.append("breaks " + ", ".join(example.broken))
    return "; ".join(parts)


# ---------------------------------------------------------------- terminal

_ANSI = {
    Status.PASS: "\033[32m",
    Status.WARN: "\033[33m",
    Status.FAIL: "\033[1;31m",
    Status.INCONCLUSIVE: "\033[35m",
    Status.SKIPPED: "\033[2m",
}
_RESET = "\033[0m"
_LABELS = {
    Status.PASS: "pass",
    Status.WARN: "warn",
    Status.FAIL: "FAIL",
    Status.INCONCLUSIVE: "undecided",
    Status.SKIPPED: "skipped",
}


def render_text(report: Report, version: str, *, color: bool = False) -> str:
    def paint(status: Status, text: str) -> str:
        return f"{_ANSI[status]}{text}{_RESET}" if color else text

    lines = [
        f"{report.rubric_id}: {paint(report.verdict, report.verdict.upper())} ({summary(report)})",
        "",
    ]
    indent = " " * 13
    for finding in report.findings:
        label = paint(finding.status, f"{_LABELS[finding.status]:<10}")
        lines.append(f"  {label} {CHECK_NAMES[finding.check]}: {finding.message}")
        if finding.status is Status.PASS:
            continue
        if finding.example is not None:
            outcome = ", ".join(
                f"{k} = {show_value(v)}" for k, v in finding.example.assignment.items()
            )
            lines.append(f"{indent}outcome: {outcome}")
            lines.append(f"{indent}{_scores_line(finding.example)}")
        if finding.conflict is not None:
            lines.append(f"{indent}conflict ({conflict_note(finding.conflict.minimal)}):")
            width = max(len(item.path) for item in finding.conflict.items)
            lines.extend(
                f"{indent}  {item.path:<{width}}  {item.requires}"
                for item in finding.conflict.items
            )
    lines += ["", solver_line(report, version), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML

_CSS = """
:root {
  --paper: #fbfcfe; --ink: #1f2a37; --soft: #5a6676; --rule: #e4e9f0;
  --margin: #e8b4ae; --fail: #b3261e; --pass: #2e6b34; --warn: #8a5000;
  --undecided: #5b3fa0; --skipped: #7a8491; --code-bg: #eef2f7;
  --text: "Charter", "Bitstream Charter", "Sitka Text", Cambria, Georgia, serif;
  --code: ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, monospace;
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #1f2a27; --ink: #e9ede6; --soft: #aab5ae; --rule: #33413c;
    --margin: #6e3b38; --fail: #ff9a8f; --pass: #9fd4a4; --warn: #f2c27a;
    --undecided: #c3b2f0; --skipped: #8d9a94; --code-bg: #2a3833;
  }
}
* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); }
body { margin: 0; font: 17px/1.6 var(--text); }
main {
  max-width: 54rem; margin: 0 auto; padding: 2.5rem 1.5rem 3rem 5rem;
  border-left: 2px solid var(--margin); min-height: 100vh;
}
header { display: flex; gap: 2rem; align-items: flex-start; justify-content: space-between; }
h1 { font-size: 2rem; line-height: 1.2; margin: 0 0 .4rem; font-weight: 700; }
h2 { font-size: 1.15rem; margin: 2.5rem 0 .75rem; font-weight: 700; }
p { margin: 0 0 .5rem; max-width: 72ch; }
.description, .tally, footer { color: var(--soft); }
.grade {
  flex: none; margin: .25rem 0 0; padding: .3em .85em; font-size: 2.3rem; font-style: italic;
  font-weight: 700; line-height: 1; border: 3px solid currentColor; border-radius: 50%;
  transform: rotate(-6deg);
}
.grade.pass { color: var(--pass); }
.grade.fail { color: var(--fail); }
.grade.inconclusive { color: var(--undecided); }
.findings { list-style: none; margin: 0; padding: 0; }
.finding { position: relative; padding: .7rem 0; border-bottom: 1px solid var(--rule); }
.finding.pass { padding: .3rem 0; color: var(--soft); font-size: .95rem; }
.finding.pass .check { font-weight: 600; color: var(--ink); }
.finding.pass .mark { font-size: 1.1rem; }
.sr {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip-path: inset(50%); white-space: nowrap;
}
.mark {
  position: absolute; left: -3.6rem; width: 2.4rem; text-align: center;
  font-size: 1.35rem; line-height: 1.4; font-weight: 700;
}
.check { font-weight: 700; }
.status { font-size: .85rem; font-style: italic; margin-left: .35rem; }
.pass .mark, .pass .status { color: var(--pass); }
.fail .mark, .fail .status { color: var(--fail); }
.warn .mark, .warn .status { color: var(--warn); }
.inconclusive .mark, .inconclusive .status { color: var(--undecided); }
.skipped .mark, .skipped .status { color: var(--skipped); }
.evidence { margin: .5rem 0 .25rem; }
.evidence p { font-size: .95rem; }
.result th { color: var(--ink); }
.fail .result tr:first-child td { color: var(--fail); font-weight: 700; }
table { border-collapse: collapse; margin: .35rem 0 .75rem; font-size: .92rem; }
th, td { text-align: left; padding: .2rem 1.1rem .2rem 0; vertical-align: top; }
th { font-weight: 600; color: var(--soft); }
code, .value {
  font-family: var(--code); font-size: .86em; background: var(--code-bg);
  padding: .05em .3em; border-radius: 3px;
}
.weight { font-variant-numeric: tabular-nums; }
footer { margin-top: 3rem; font-size: .9rem; }
@media (max-width: 40rem) {
  main { padding: 1.5rem 1rem 2rem 2.6rem; }
  header { flex-direction: column-reverse; gap: .75rem; }
  .mark { left: -2.3rem; width: 1.8rem; }
  .grade { font-size: 1.8rem; }
}
@media print {
  html { background: #fff; color: #000; }
  main { border-left-color: #d9a39d; min-height: 0; }
  .finding { break-inside: avoid; }
}
"""

_MARKS = {
    Status.PASS: "\u2713",
    Status.WARN: "!",
    Status.FAIL: "\u2717",
    Status.INCONCLUSIVE: "?",
    Status.SKIPPED: "-",
}
_STATUS_WORDS = {
    Status.PASS: "passed",
    Status.WARN: "warning",
    Status.FAIL: "failed",
    Status.INCONCLUSIVE: "undecided",
    Status.SKIPPED: "skipped",
}


def style_hash() -> str:
    """The CSP source expression that allows exactly the inline stylesheet."""
    digest = hashlib.sha256(_CSS.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def render_html(report: Report, rubric: Rubric, version: str) -> str:
    verdict = report.verdict
    title = f"{rubric.id}: {_VERDICT_WORDS[verdict].lower()}"
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" '
        f"content=\"default-src 'none'; style-src {style_hash()}\">",
        f"<title>{escape(title)} (rubric-prover)</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<main>",
        "<header>",
        "<div>",
        f"<h1>{escape(rubric.id)}</h1>",
    ]
    if rubric.description:
        parts.append(f'<p class="description">{escape(rubric.description)}</p>')
    parts += [
        f'<p class="tally">{escape(summary(report).capitalize())}.</p>',
        "</div>",
        f'<p class="grade {verdict}" aria-label="Verdict: {_VERDICT_WORDS[verdict].lower()}">'
        f"{_VERDICT_WORDS[verdict]}</p>",
        "</header>",
        '<h2 id="findings">Findings</h2>',
        '<ul class="findings" aria-labelledby="findings">',
    ]
    parts += [_finding_html(f) for f in report.findings]
    parts += ["</ul>", *_rubric_html(rubric)]
    parts += [f"<footer><p>{escape(solver_line(report, version))}</p></footer>", "</main>"]
    parts += ["</body>", "</html>", ""]
    return "\n".join(parts)


def _finding_html(finding: Finding) -> str:
    status = finding.status
    mark = f'<span class="mark" aria-hidden="true">{_MARKS[status]}</span>'
    check = f'<span class="check">{escape(CHECK_NAMES[finding.check])}</span>'
    if status is Status.PASS:
        return (
            f'<li class="finding pass">{mark}<p>{check}'
            f'<span class="sr"> passed</span>: {escape(finding.message)}</p></li>'
        )
    html = [
        f'<li class="finding {status}">',
        mark,
        f'<p>{check}<span class="status">{_STATUS_WORDS[status]}</span></p>',
        f"<p>{escape(_sentence(finding.message))}</p>",
    ]
    if finding.example is not None:
        example = finding.example
        outcome = "".join(
            f'<tr><th scope="row">{escape(name)}</th>'
            f'<td><span class="value">{escape(show_value(value))}</span></td></tr>'
            for name, value in example.assignment.items()
        )
        scores = "".join(
            f'<tr><th scope="row">{label}</th><td>{escape(text)}</td></tr>'
            for label, text in _score_rows(example)
        )
        html += [
            '<div class="evidence">',
            "<p>For example, this outcome:</p>",
            f"<table>{outcome}</table>",
            f'<table class="result">{scores}</table>',
            "</div>",
        ]
    if finding.conflict is not None:
        rows = "".join(
            f'<tr><th scope="row">{escape(item.path)}</th>'
            f"<td><code>{escape(item.requires)}</code></td></tr>"
            for item in finding.conflict.items
        )
        html += [
            '<div class="evidence">',
            f"<p>{conflict_note(finding.conflict.minimal).capitalize()}:</p>",
            f"<table>{rows}</table>",
            "</div>",
        ]
    html.append("</li>")
    return "\n".join(html)


def _rubric_html(rubric: Rubric) -> list[str]:
    def table(caption_id: str, heading: str, header: str, rows: list[str]) -> list[str]:
        return [
            f'<h2 id="{caption_id}">{heading}</h2>',
            f'<table aria-labelledby="{caption_id}"><thead><tr>{header}</tr></thead>',
            "<tbody>",
            *rows,
            "</tbody></table>",
        ]

    out = table(
        "criteria",
        "Criteria",
        "<th>Criterion</th><th>Weight</th><th>Pays when</th>",
        [
            f'<tr><td>{escape(c.id)}</td><td class="weight">{format_number(c.weight)}</td>'
            f"<td><code>{escape(c.when.source)}</code></td></tr>"
            for c in rubric.criteria
        ],
    )
    if rubric.penalties:
        out += table(
            "penalties",
            "Penalties",
            "<th>Penalty</th><th>Effect</th><th>Fires when</th>",
            [
                f"<tr><td>{escape(p.id)}</td><td>"
                + (
                    "score set to 0"
                    if p.deduction is None
                    else f"minus {format_number(p.deduction)}"
                )
                + f"</td><td><code>{escape(p.when.source)}</code></td></tr>"
                for p in rubric.penalties
            ],
        )
    if rubric.invariants:
        out += table(
            "invariants",
            f"Invariants (threshold {format_number(rubric.exploit_threshold)})",
            "<th>Invariant</th><th>Must hold</th>",
            [
                f"<tr><td>{escape(i.id)}</td><td><code>{escape(i.holds.source)}</code></td></tr>"
                for i in rubric.invariants
            ],
        )
    if rubric.assumptions:
        out += [
            '<h2 id="assumptions">Assumed of every outcome</h2>',
            "<ul>",
            *(f"<li><code>{escape(a.source)}</code></li>" for a in rubric.assumptions),
            "</ul>",
        ]
    return out
