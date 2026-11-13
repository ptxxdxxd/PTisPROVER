from __future__ import annotations

import pytest

from rubric_prover.errors import RubricError
from rubric_prover.lexer import MAX_EXPRESSION_LENGTH, Kind, tokenize


def kinds_and_texts(text: str) -> list[tuple[Kind, str]]:
    return [(t.kind, t.text) for t in tokenize(text)]


def test_tokens_of_a_typical_condition() -> None:
    assert kinds_and_texts("net_margin >= 0.18 and not flag") == [
        (Kind.NAME, "net_margin"),
        (Kind.OP, ">="),
        (Kind.DECIMAL, "0.18"),
        (Kind.KEYWORD, "and"),
        (Kind.KEYWORD, "not"),
        (Kind.NAME, "flag"),
        (Kind.END, ""),
    ]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("42", Kind.INT),
        ("1_000_000", Kind.INT),
        ("0", Kind.INT),
        ("0x0F", Kind.INT),
        ("0b1010_0101", Kind.INT),
        ("3.25", Kind.DECIMAL),
        ("0.000_5", Kind.DECIMAL),
    ],
)
def test_number_literals(text: str, kind: Kind) -> None:
    token = tokenize(text)[0]
    assert (token.kind, token.text, token.start, token.end) == (kind, text, 0, len(text))


def test_two_character_operators_win_over_one_character_ones() -> None:
    assert [t.text for t in tokenize("a<=b>=c==d!=e<f>g")][1:-1:2] == [
        "<=", ">=", "==", "!=", "<", ">"
    ]  # fmt: skip


def test_end_token_sits_at_the_end_of_the_text() -> None:
    end = tokenize("a  ")[-1]
    assert (end.kind, end.start, end.end) == (Kind.END, 3, 3)


@pytest.mark.parametrize(
    ("text", "message", "line", "column"),
    [
        ("a = 1", "'=' is not an operator; use '==' to compare", 1, 3),
        ("a && b", "'&&' is not an operator; use 'and'", 1, 3),
        ("a || b", "'||' is not an operator; use 'or'", 1, 3),
        ("a => b", "'=>' is not an operator; use 'implies'", 1, 3),
        ("a -> b", "'->' is not an operator; use 'implies'", 1, 3),
        ("!a", "'!' is not an operator; use 'not'", 1, 1),
        ("a / 2", "division is not supported", 1, 3),
        ("a % 2", "the remainder operator is not supported", 1, 3),
        ("a ** 2", "'**' is not supported; write the multiplication out", 1, 3),
        ("a $ b", "unexpected character '$'", 1, 3),
        ("a\n\tb ~", "unexpected character '~'", 2, 4),
        ("x == é", "unexpected character 'é'", 1, 6),
        ("x == \x00", "unexpected character '\\x00'", 1, 6),
        ("x == 12abc", "invalid number '12abc'", 1, 6),
        ("x == 1.", "invalid number '1.'", 1, 6),
        ("x == 1.5.2", "invalid number '1.5.2'", 1, 6),
        ("x == 0x", "invalid number '0x'", 1, 6),
        ("x == 0x1g", "invalid number '0x1g'", 1, 6),
        ("x == 1_", "invalid number '1_'", 1, 6),
        ("x == 1e5", "invalid number '1e5'", 1, 6),
        ("x == 007", "leading zeros are not allowed in '007'", 1, 6),
        ("x == 00.5", "leading zeros are not allowed in '00.5'", 1, 6),
    ],
)
def test_lexical_errors_say_what_and_where(text: str, message: str, line: int, column: int) -> None:
    with pytest.raises(RubricError) as exc:
        tokenize(text)
    (diagnostic,) = exc.value.diagnostics
    assert (diagnostic.message, diagnostic.line, diagnostic.column) == (message, line, column)


def test_overlong_expression_is_refused_before_tokenizing() -> None:
    with pytest.raises(RubricError) as exc:
        tokenize("a" * (MAX_EXPRESSION_LENGTH + 1))
    (diagnostic,) = exc.value.diagnostics
    assert diagnostic.message == (
        f"expression is {MAX_EXPRESSION_LENGTH + 1} characters long; "
        f"the limit is {MAX_EXPRESSION_LENGTH}"
    )
    assert diagnostic.line is None


def test_expression_at_the_length_limit_is_accepted() -> None:
    assert len(tokenize("a" * MAX_EXPRESSION_LENGTH)) == 2
