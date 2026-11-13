"""Command-line entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import z3

from rubric_prover import __version__


def _version_line() -> str:
    return f"rubric-prover {__version__} (z3 {z3.get_version_string()})"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rubric-prover",
        description="Check a grading rubric for reward hacks, dead criteria and contradictions.",
    )
    parser.add_argument("--version", action="version", version=_version_line())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
