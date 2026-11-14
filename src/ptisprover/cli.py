"""Command-line interface.

Exit codes: 0 pass, 1 fail, 2 inconclusive, 3 invalid input or usage,
4 internal error (the solver and the reference evaluator disagreed).
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import z3

from ptisprover import __version__
from ptisprover.errors import InternalError, RubricError
from ptisprover.loader import load_rubric
from ptisprover.prover import run_checks
from ptisprover.render import render_html, render_text
from ptisprover.report import Status
from ptisprover.schema import rubric_schema_text
from ptisprover.signature import TAG
from ptisprover.smt import DEFAULT_BUDGET, MAX_BUDGET

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INCONCLUSIVE = 2
EXIT_INPUT = 3
EXIT_INTERNAL = 4


class _Parser(argparse.ArgumentParser):
    """argparse exits with 2 on bad usage, which here means 'inconclusive'. Use 3."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT, f"{self.prog}: error: {message}\n")


def _positive_int(text: str) -> int:
    try:
        value = int(text.replace("_", ""))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if not 0 < value <= MAX_BUDGET:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_BUDGET:,}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="ptisprover",
        description="Check a grading rubric for reward hacks, dead criteria and contradictions.",
        epilog="Exit codes: 0 pass, 1 fail, 2 inconclusive, 3 bad input, 4 internal error.\n\n"
        + TAG,
        # Keeps the line breaks of the epilog; the description is a single line either way.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ptisprover {__version__} (z3 {z3.get_version_string()})",
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    check = commands.add_parser("check", help="check a rubric file (.toml or .json)")
    check.add_argument("rubric", type=Path, help="path to the rubric file")
    check.add_argument(
        "--format", choices=("text", "json", "html"), default="text", help="report format"
    )
    check.add_argument("-o", "--output", type=Path, help="write the report here, not to stdout")
    check.add_argument(
        "--budget",
        type=_positive_int,
        default=DEFAULT_BUDGET,
        help=f"Z3 resource units per solver query (default {DEFAULT_BUDGET:,})",
    )
    check.add_argument(
        "--emit-smt2",
        type=Path,
        metavar="DIR",
        help="also write every solver query to DIR as SMT-LIB2 (replaces query-*.smt2 there)",
    )
    check.add_argument(
        "--fail-on-warning", action="store_true", help="exit 1 if there are warnings"
    )
    check.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colour the text report (auto: only on a terminal, and not if NO_COLOR is set)",
    )

    commands.add_parser("schema", help="print the JSON Schema for rubric files")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "schema":
        sys.stdout.write(rubric_schema_text())
        return EXIT_PASS
    try:
        return _check(args)
    except Exception:
        # Anything unexpected is a bug in this tool. It must not exit 1, which means
        # "the rubric fails".
        traceback.print_exc()
        sys.stderr.write("ptisprover: internal error (traceback above), please report it\n")
        return EXIT_INTERNAL


def _check(args: argparse.Namespace) -> int:
    path: Path = args.rubric
    try:
        rubric = load_rubric(path)
    except OSError as exc:
        return _input_error(f"cannot read {path}: {exc.strerror or exc}")
    except RubricError as exc:
        return _input_error("\n".join(f"{path}: {d.render()}" for d in exc.diagnostics))
    # Find out that an output location is unusable before the solver runs, not after.
    if args.output is not None:
        if args.output.is_dir():
            return _input_error(f"cannot write to {args.output}: it is a directory")
        if not args.output.parent.is_dir():
            return _input_error(f"cannot write to {args.output}: no such directory")
    if args.emit_smt2 is not None:
        try:
            args.emit_smt2.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _input_error(f"cannot write to {args.emit_smt2}: {exc.strerror or exc}")

    try:
        proof = run_checks(rubric, budget=args.budget, keep_smt2=args.emit_smt2 is not None)
    except InternalError as exc:
        sys.stderr.write(f"ptisprover: internal error, please report it: {exc}\n")
        return EXIT_INTERNAL
    report = proof.report

    if args.format == "json":
        text = report.to_json()
    elif args.format == "html":
        text = render_html(report, rubric, __version__)
    else:
        text = render_text(report, __version__, color=_use_color(args.color, args.output))
    try:
        if args.emit_smt2 is not None:
            for stale in args.emit_smt2.glob("query-*.smt2"):
                stale.unlink()
            for name, query in proof.smt2_files().items():
                _write(args.emit_smt2 / name, query)
        if args.output is not None:
            _write(args.output, text)
    except OSError as exc:
        return _input_error(f"cannot write to {exc.filename}: {exc.strerror or exc}")
    if args.output is None:
        if args.format != "text" and isinstance(sys.stdout, io.TextIOWrapper):
            # JSON and HTML reports are UTF-8 whatever the console's own encoding is.
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)

    if report.verdict is Status.FAIL:
        return EXIT_FAIL
    if report.verdict is Status.INCONCLUSIVE:
        return EXIT_INCONCLUSIVE
    warnings = sum(1 for f in report.findings if f.status is Status.WARN)
    if args.fail_on_warning and warnings:
        sys.stderr.write(
            f"ptisprover: exit 1: --fail-on-warning is set and there are {warnings} warning(s)\n"
        )
        return EXIT_FAIL
    return EXIT_PASS


def _write(path: Path, text: str) -> None:
    """Write UTF-8 with \\n line endings on every platform, so reports are byte-identical."""
    path.write_text(text, encoding="utf-8", newline="\n")


def _input_error(message: str) -> int:
    sys.stderr.write(message.rstrip("\n") + "\n")
    return EXIT_INPUT


def _use_color(choice: str, output: Path | None) -> bool:
    if choice != "auto":
        return choice == "always"
    if output is not None or "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()
