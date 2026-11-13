"""Errors raised for invalid rubrics, with positions precise enough to act on."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace


def position(text: str, offset: int) -> tuple[int, int]:
    """Return the 1-based (line, column) of a character offset in ``text``."""
    line = text.count("\n", 0, offset) + 1
    column = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, column


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One problem in a rubric.

    ``path`` locates the field (for example ``criteria["speed"].when``). When the
    problem is inside a condition expression, ``text`` holds that expression and
    ``start``/``end`` are character offsets into it.
    """

    message: str
    path: str = ""
    text: str | None = None
    start: int | None = None
    end: int | None = None

    @property
    def line(self) -> int | None:
        if self.text is None or self.start is None:
            return None
        return position(self.text, self.start)[0]

    @property
    def column(self) -> int | None:
        if self.text is None or self.start is None:
            return None
        return position(self.text, self.start)[1]

    def at(self, path: str) -> Diagnostic:
        """Return a copy located at ``path``."""
        return replace(self, path=path)

    def render(self) -> str:
        where = self.path or "<expression>"
        if self.text is None or self.start is None:
            return f"{where}: {self.message}"
        line, column = position(self.text, self.start)
        lines = self.text.split("\n")
        source_line = lines[line - 1]
        end = self.start + 1 if self.end is None else self.end
        width = max(1, min(end - self.start, len(source_line) - column + 1))
        caret = " " * (column - 1) + "^" * width
        return f"{where}:{line}:{column}: {self.message}\n    {source_line}\n    {caret}"


class RubricError(Exception):
    """A rubric (or a condition inside it) is invalid. Holds every problem found."""

    def __init__(self, diagnostics: Iterable[Diagnostic]) -> None:
        self.diagnostics: tuple[Diagnostic, ...] = tuple(diagnostics)
        if not self.diagnostics:
            raise ValueError("RubricError needs at least one diagnostic")
        super().__init__("\n".join(d.render() for d in self.diagnostics))

    @classmethod
    def single(
        cls,
        message: str,
        *,
        path: str = "",
        text: str | None = None,
        span: tuple[int, int] | None = None,
    ) -> RubricError:
        start, end = span if span is not None else (None, None)
        return cls([Diagnostic(message, path=path, text=text, start=start, end=end)])


class InternalError(Exception):
    """The solver and the reference evaluator disagree. Always a bug; never reported as a result."""
