from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from ptisprover import __version__
from ptisprover.cli import main
from ptisprover.errors import InternalError
from tests.conftest import ORIGINAL

LOOPHOLE = str(ORIGINAL / "loophole_volume.toml")
GOVCON = str(ORIGINAL / "govcon_quote.toml")
REDUNDANT = str(ORIGINAL / "redundant_latency.toml")


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_version_flag_reports_package_and_solver_versions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith(f"ptisprover {__version__} (z3 ")


@pytest.mark.parametrize(
    "argv",
    [[], ["check"], ["check", LOOPHOLE, "--budget", "0"], ["check", LOOPHOLE, "--budget", "x"]],
)
def test_usage_errors_exit_3_not_argparses_2(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 3
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("path", "code"),
    [(GOVCON, 0), (LOOPHOLE, 1), (str(ORIGINAL / "contradictory_pricing.toml"), 1)],
)
def test_exit_code_follows_the_verdict(
    capsys: pytest.CaptureFixture[str], path: str, code: int
) -> None:
    assert run(capsys, "check", path, "--color", "never")[0] == code


def test_inconclusive_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rubric = tmp_path / "fermat.toml"
    rubric.write_text(
        'id = "f"\nexploit_threshold = 1\n[variables]\n'
        'x = { type = "int", min = 1, max = 60 }\ny = { type = "int", min = 1, max = 60 }\n'
        'z = { type = "int", min = 1, max = 60 }\n'
        '[[criteria]]\nid = "c"\nweight = 1\nwhen = "x * x * x + y * y * y != z * z * z"\n',
        encoding="utf-8",
    )
    code, out, _ = run(capsys, "check", str(rubric), "--budget", "200_000", "--color", "never")
    assert code == 2
    assert out.startswith("f: INCONCLUSIVE")


def test_warnings_fail_only_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "check", REDUNDANT)[0] == 0
    assert run(capsys, "check", REDUNDANT, "--fail-on-warning")[0] == 1


def test_text_report(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "check", LOOPHOLE, "--color", "never")
    assert (code, err) == (1, "")
    assert out.splitlines()[0] == "loophole-volume: FAIL (2 failed, 6 passed)"
    assert "  FAIL       Reward hacking: breaking 'positive_margin' can still score 0.9" in out
    assert "             outcome: deal_volume_usd = 750000, quote_latency_ms = 100, " in out
    assert out.rstrip().endswith("per query).")
    assert "\033[" not in out


def test_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "check", LOOPHOLE, "--format", "json")
    assert code == 1
    assert json.loads(out)["verdict"] == "fail"


def test_html_report_to_a_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    target = tmp_path / "report.html"
    code, out, _ = run(capsys, "check", LOOPHOLE, "--format", "html", "-o", str(target))
    assert (code, out) == (1, "")
    html = target.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert '<p class="grade fail" aria-label="Verdict: fail">Fail</p>' in html


@pytest.mark.parametrize(
    ("argv", "env", "tty", "colored"),
    [
        (["--color", "always"], {}, False, True),
        (["--color", "never"], {}, True, False),
        ([], {}, True, True),
        ([], {"NO_COLOR": "1"}, True, False),
        ([], {}, False, False),
    ],
)
def test_color_rules(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    env: dict[str, str],
    tty: bool,
    colored: bool,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: tty)
    _, out, _ = run(capsys, "check", LOOPHOLE, *argv)
    assert ("\033[" in out) is colored


def test_color_is_off_when_writing_to_a_file(tmp_path: Path) -> None:
    target = tmp_path / "report.txt"
    main(["check", LOOPHOLE, "-o", str(target)])
    assert "\033[" not in target.read_text(encoding="utf-8")


def test_invalid_rubric_exits_3_with_located_errors(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    rubric = tmp_path / "bad.toml"
    rubric.write_text(
        'id = "b"\nexploit_threshold = 1\n[variables]\nx = "int"\n'
        '[[criteria]]\nid = "c"\nweight = 1\nwhen = "x >= = 1"\n',
        encoding="utf-8",
    )
    code, out, err = run(capsys, "check", str(rubric))
    assert (code, out) == (3, "")
    assert err.startswith(f"{rubric}: criteria[\"c\"].when:1:6: '=' is not an operator")


@pytest.mark.parametrize(
    ("name", "message"),
    [("missing.toml", "cannot read"), ("rubric.yaml", "unsupported file type '.yaml'")],
)
def test_unreadable_input_exits_3(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, name: str, message: str
) -> None:
    if name.endswith(".yaml"):
        (tmp_path / name).write_text("id: x", encoding="utf-8")
    code, _, err = run(capsys, "check", str(tmp_path / name))
    assert code == 3
    assert message in err


def test_internal_error_exits_4(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise InternalError("the evaluator and the solver disagree")

    monkeypatch.setattr("ptisprover.cli.run_checks", broken)
    code, out, err = run(capsys, "check", LOOPHOLE)
    assert (code, out) == (4, "")
    assert err == (
        "ptisprover: internal error, please report it: the evaluator and the solver disagree\n"
    )


def test_schema_command_prints_the_schema(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "schema")
    assert code == 0
    assert json.loads(out)["title"] == "PTisPROVER rubric"


def test_module_entry_point_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["ptisprover", "check", GOVCON, "--format", "json"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("ptisprover", run_name="__main__")
    assert exc.value.code == 0


def test_module_runs_in_a_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ptisprover", "check", LOOPHOLE, "--color", "never"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert result.stdout.startswith("loophole-volume: FAIL")


# ------------------------------------------------------------------ robustness


def write_ok_rubric(directory: Path) -> Path:
    rubric = directory / "ok.toml"
    rubric.write_text(
        'id = "ok"\nexploit_threshold = 1\n[variables]\nx = { type = "int", min = 0, max = 5 }\n'
        '[[criteria]]\nid = "c"\nweight = 1\nwhen = "x >= 3"\n',
        encoding="utf-8",
    )
    return rubric


def test_a_file_that_is_not_text_is_an_input_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    rubric = tmp_path / "binary.toml"
    rubric.write_bytes(bytes(range(128, 256)))
    code, _, err = run(capsys, "check", str(rubric))
    assert (code, err) == (3, f"{rubric}: the file is not UTF-8 text\n")


def test_a_byte_order_mark_is_accepted(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rubric = write_ok_rubric(tmp_path)
    rubric.write_bytes(b"\xef\xbb\xbf" + rubric.read_bytes())
    assert run(capsys, "check", str(rubric))[0] == 0


def test_unusable_output_locations_are_found_before_solving(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("the solver ran before the output location was checked")

    monkeypatch.setattr("ptisprover.cli.run_checks", must_not_run)
    rubric = str(write_ok_rubric(tmp_path))
    a_file = tmp_path / "file"
    a_file.write_text("", encoding="utf-8")
    for argv in (
        ["-o", str(tmp_path / "missing" / "report.txt")],
        ["-o", str(tmp_path)],
        ["--emit-smt2", str(a_file)],
    ):
        code, out, err = run(capsys, "check", rubric, *argv)
        assert (code, out) == (3, "")
        assert err.startswith("cannot write to ")
        assert "Traceback" not in err


def test_a_failed_write_is_an_input_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(path: Path, text: str) -> None:
        raise OSError(28, "No space left on device", str(path))

    monkeypatch.setattr("ptisprover.cli._write", disk_full)
    target = tmp_path / "report.txt"
    code, _, err = run(capsys, "check", str(write_ok_rubric(tmp_path)), "-o", str(target))
    assert (code, err) == (3, f"cannot write to {target}: No space left on device\n")


def test_budget_above_what_z3_can_count_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["check", LOOPHOLE, "--budget", str(2**32)])
    assert exc.value.code == 3
    assert "must be between 1 and 4,294,967,295" in capsys.readouterr().err


def test_an_unexpected_exception_exits_4_not_1(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr("ptisprover.cli.run_checks", broken)
    code, out, err = run(capsys, "check", LOOPHOLE)
    assert (code, out) == (4, "")
    assert "RuntimeError: something nobody planned for" in err
    assert err.endswith("ptisprover: internal error (traceback above), please report it\n")


def test_fail_on_warning_says_why_it_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "check", REDUNDANT, "--fail-on-warning", "--color", "never")
    assert code == 1
    assert out.startswith("redundant-latency: PASS")
    assert err == "ptisprover: exit 1: --fail-on-warning is set and there are 1 warning(s)\n"


def test_html_to_a_console_that_is_not_utf8() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ptisprover", "check", GOVCON, "--format", "html"],
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert result.returncode == 0, result.stderr
    assert "\u2713" in result.stdout.decode("utf-8")


def test_installed_console_script() -> None:
    script = Path(sys.executable).parent / "ptisprover"
    result = subprocess.run([str(script), "--version"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"ptisprover {__version__} ")
