"""Where the repository keeps the files the tests read."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
ORIGINAL = ROOT / "tests" / "rubrics" / "original"
