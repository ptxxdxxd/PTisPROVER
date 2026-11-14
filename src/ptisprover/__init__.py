"""Static checks for weighted grading rubrics, backed by an SMT solver."""

from importlib.metadata import version

from ptisprover.errors import Diagnostic, RubricError
from ptisprover.evaluate import Assessment, assess, evaluate
from ptisprover.loader import load_rubric, loads_json, loads_toml, rubric_from_dict
from ptisprover.model import Condition, Criterion, Invariant, Penalty, Rubric, Variable
from ptisprover.parser import parse_expression
from ptisprover.prover import Proof, prove
from ptisprover.report import Check, Finding, Report, Status
from ptisprover.typecheck import check_condition

__version__ = version("ptisprover")

__all__ = [
    "Assessment",
    "Check",
    "Condition",
    "Criterion",
    "Diagnostic",
    "Finding",
    "Invariant",
    "Penalty",
    "Proof",
    "Report",
    "Rubric",
    "RubricError",
    "Status",
    "Variable",
    "__version__",
    "assess",
    "check_condition",
    "evaluate",
    "load_rubric",
    "loads_json",
    "loads_toml",
    "parse_expression",
    "prove",
    "rubric_from_dict",
]
