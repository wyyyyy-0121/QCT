"""FormulaGuard research prototype."""

from .api import LocalizationResult, localize
from .v4x import VERSION_ALIASES, V42Decision, v4_1_scores, v4_2_review, v4_3_scores
from .v5_core import v5_core_scores
from .v5_core_r2 import v5_core_r2_scores
from .v6 import v6_scores
from .workbook import WorkbookModel

__all__ = [
    "WorkbookModel", "LocalizationResult", "localize", "VERSION_ALIASES",
    "V42Decision", "v4_1_scores", "v4_2_review", "v4_3_scores",
    "v5_core_scores", "v5_core_r2_scores", "v6_scores",
]
__version__ = "0.1.0"
