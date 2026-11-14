"""The author's tag.

It signs the project where a person would sign: the README and ``--help``. It is never added
to reports, the JSON Schema or exported SMT-LIB2, which are output about someone else's rubric
and stay free of decoration.

``tests/test_signature.py`` keeps the copy in README.md identical to this one.
"""

from __future__ import annotations

AUTHOR = "PTisDEV"

TAG = r"""
   .-------.
  /         \
 |  ()   ()  |
 |     ^     |
  \  |||||  /
   '-.___.-'
    PTisDEV
""".strip("\n")
