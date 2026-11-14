"""Static checks for weighted grading rubrics, backed by an SMT solver."""

from importlib.metadata import version

from ptisprover.errors import Diagnostic, RubricError
from ptisprover.evaluate import Assessment, assess, evaluate, score
from ptisprover.loader import load_rubric, loads_json, loads_toml, rubric_from_dict
from ptisprover.model import Condition, Criterion, Invariant, Penalty, Rubric, Variable
from ptisprover.parser import parse_expression
from ptisprover.typecheck import check_condition

__version__ = version("ptisprover")

__all__ = [
    "Assessment",
    "Condition",
    "Criterion",
    "Diagnostic",
    "Invariant",
    "Penalty",
    "Rubric",
    "RubricError",
    "Variable",
    "__version__",
    "assess",
    "check_condition",
    "evaluate",
    "load_rubric",
    "loads_json",
    "loads_toml",
    "parse_expression",
    "rubric_from_dict",
    "score",
]
