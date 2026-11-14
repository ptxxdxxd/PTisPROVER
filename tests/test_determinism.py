"""The same rubric gives byte-identical reports, in this process and in fresh ones."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ptisprover.loader import load_rubric
from ptisprover.prover import prove
from tests.conftest import ORIGINAL

SCRIPT = (
    "import sys; from ptisprover import load_rubric; from ptisprover.prover import prove; "
    "sys.stdout.write(prove(load_rubric(sys.argv[1])).to_json())"
)


def report_in_fresh_process(path: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize("path", sorted(ORIGINAL.glob("*.toml")), ids=lambda p: p.stem)
def test_reports_are_identical_across_processes(path: Path) -> None:
    here = prove(load_rubric(path)).to_json()
    assert report_in_fresh_process(path) == here
    assert report_in_fresh_process(path) == here
