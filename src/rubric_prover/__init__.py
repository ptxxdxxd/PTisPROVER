"""Static checks for weighted grading rubrics, backed by an SMT solver."""

from importlib.metadata import version

from rubric_prover.errors import Diagnostic, RubricError
from rubric_prover.evaluate import Assessment, assess, evaluate, score
from rubric_prover.loader import load_rubric, loads_json, loads_toml, rubric_from_dict
from rubric_prover.model import Condition, Criterion, Invariant, Penalty, Rubric, Variable
from rubric_prover.parser import parse_expression
from rubric_prover.typecheck import check_condition

__version__ = version("rubric-prover")

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
