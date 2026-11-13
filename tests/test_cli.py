from __future__ import annotations

import runpy
import subprocess
import sys

import pytest

from rubric_prover import __version__
from rubric_prover.cli import main


def test_version_flag_reports_package_and_solver_versions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith(f"rubric-prover {__version__} (z3 ")
    assert out.endswith(")")


def test_no_arguments_exits_cleanly() -> None:
    assert main([]) == 0


def test_module_entry_point_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["rubric-prover"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("rubric_prover", run_name="__main__")
    assert exc.value.code == 0


def test_module_entry_point_in_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "rubric_prover", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("rubric-prover ")
