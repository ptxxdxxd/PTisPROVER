from __future__ import annotations

import pytest

from rubric_prover.errors import Diagnostic, RubricError, position


@pytest.mark.parametrize(
    ("text", "offset", "expected"),
    [("abc", 0, (1, 1)), ("abc", 3, (1, 4)), ("a\nbc", 2, (2, 1)), ("a\nbc", 3, (2, 2))],
)
def test_position(text: str, offset: int, expected: tuple[int, int]) -> None:
    assert position(text, offset) == expected


def test_render_without_a_position() -> None:
    assert Diagnostic("required", path="id").render() == "id: required"
    assert Diagnostic("oops").render() == "oops"
    assert Diagnostic("oops", text="x", start=0).render() == "<expression>:1:1: oops\n    x\n    ^"
    assert Diagnostic("oops").line is None
    assert Diagnostic("oops").column is None


def test_render_points_at_the_span() -> None:
    diagnostic = Diagnostic("bad", path="p", text="a +\n  bb + c", start=6, end=8)
    assert (diagnostic.line, diagnostic.column) == (2, 3)
    assert diagnostic.render() == "p:2:3: bad\n      bb + c\n      ^^"


def test_caret_is_clamped_to_the_line_and_never_empty() -> None:
    at_end = Diagnostic("eof", text="ab", start=2, end=2)
    assert at_end.render() == "<expression>:1:3: eof\n    ab\n      ^"
    spanning = Diagnostic("multi", text="ab\ncd", start=1, end=5)
    assert spanning.render().splitlines()[-1] == "     ^"


def test_rubric_error_needs_a_diagnostic() -> None:
    with pytest.raises(ValueError, match="at least one diagnostic"):
        RubricError([])


def test_rubric_error_message_lists_every_diagnostic() -> None:
    error = RubricError([Diagnostic("one", path="a"), Diagnostic("two", path="b")])
    assert str(error) == "a: one\nb: two"
    assert Diagnostic("x").at("criteria[0]").path == "criteria[0]"


def test_long_lines_are_shown_as_a_window_around_the_problem() -> None:
    text = "a + " * 100 + "$" + " + a" * 100
    rendered = Diagnostic("bad", text=text, start=400, end=401).render().splitlines()
    assert rendered[0] == "<expression>:1:401: bad"
    assert len(rendered[1]) == len("    ") + 100
    assert rendered[1][rendered[2].index("^")] == "$"
    assert rendered[2].count("^") == 1


def test_control_characters_are_not_echoed() -> None:
    rendered = Diagnostic("bad", text="x == \x1b[31m 1", start=5, end=6).render()
    assert "\x1b" not in rendered
    assert rendered.splitlines()[1:] == ["    x == ?[31m 1", "         ^"]
