"""Tokenizer for condition expressions such as ``net_margin >= 0.18 and not flagged``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from rubric_prover.errors import RubricError

MAX_EXPRESSION_LENGTH = 10_000

KEYWORDS = frozenset({"and", "or", "not", "implies", "true", "false"})


class Kind(Enum):
    NAME = "name"
    INT = "integer"
    DECIMAL = "decimal"
    KEYWORD = "keyword"
    OP = "operator"
    END = "end of input"


@dataclass(frozen=True, slots=True)
class Token:
    kind: Kind
    text: str
    start: int
    end: int

    def describe(self) -> str:
        return "end of input" if self.kind is Kind.END else f"'{self.text}'"


_TWO_CHAR_OPERATORS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPERATORS = "<>+-*&|^()"

# Spellings from other languages, with the fix. Two-character ones are tried first.
_MISTAKES = {
    "&&": "'&&' is not an operator; use 'and'",
    "||": "'||' is not an operator; use 'or'",
    "=>": "'=>' is not an operator; use 'implies'",
    "->": "'->' is not an operator; use 'implies'",
    "**": "'**' is not supported; write the multiplication out",
    "=": "'=' is not an operator; use '==' to compare",
    "!": "'!' is not an operator; use 'not'",
    "/": "division is not supported",
    "%": "the remainder operator is not supported",
}

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(
    r"0[xX][0-9A-Fa-f]+(?:_[0-9A-Fa-f]+)*"
    r"|0[bB][01]+(?:_[01]+)*"
    r"|(?P<int>[0-9]+(?:_[0-9]+)*)(?P<frac>\.[0-9]+(?:_[0-9]+)*)?"
)
_LITERAL_TAIL = re.compile(r"[A-Za-z0-9_.]*")
_WHITESPACE = " \t\r\n"


def tokenize(text: str) -> list[Token]:
    """Split ``text`` into tokens, ending with an END token. Raises RubricError."""
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise RubricError.single(
            f"expression is {len(text)} characters long; the limit is {MAX_EXPRESSION_LENGTH}"
        )
    tokens: list[Token] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char in _WHITESPACE:
            i += 1
            continue
        if char.isascii() and (char.isalpha() or char == "_"):
            match = _NAME.match(text, i)
            assert match is not None
            word = match.group()
            kind = Kind.KEYWORD if word in KEYWORDS else Kind.NAME
            tokens.append(Token(kind, word, i, match.end()))
            i = match.end()
            continue
        if char.isascii() and char.isdigit():
            tokens.append(_number(text, i))
            i = tokens[-1].end
            continue
        pair = text[i : i + 2]
        if pair in _TWO_CHAR_OPERATORS:
            tokens.append(Token(Kind.OP, pair, i, i + 2))
            i += 2
            continue
        if pair in _MISTAKES:
            raise RubricError.single(_MISTAKES[pair], text=text, span=(i, i + 2))
        if char in _ONE_CHAR_OPERATORS:
            tokens.append(Token(Kind.OP, char, i, i + 1))
            i += 1
            continue
        if char in _MISTAKES:
            raise RubricError.single(_MISTAKES[char], text=text, span=(i, i + 1))
        shown = char if char.isprintable() else repr(char)[1:-1]
        raise RubricError.single(f"unexpected character '{shown}'", text=text, span=(i, i + 1))
    tokens.append(Token(Kind.END, "", len(text), len(text)))
    return tokens


def _number(text: str, start: int) -> Token:
    match = _NUMBER.match(text, start)
    assert match is not None  # called only at a digit
    end = match.end()
    tail = _LITERAL_TAIL.match(text, end)
    assert tail is not None
    if tail.end() > end:
        bad = text[start : tail.end()]
        raise RubricError.single(f"invalid number '{bad}'", text=text, span=(start, tail.end()))
    integer_part = match.group("int")
    if integer_part is not None and len(integer_part) > 1 and integer_part.startswith("0"):
        raise RubricError.single(
            f"leading zeros are not allowed in '{match.group()}'", text=text, span=(start, end)
        )
    kind = Kind.DECIMAL if match.group("frac") is not None else Kind.INT
    return Token(kind, match.group(), start, end)
