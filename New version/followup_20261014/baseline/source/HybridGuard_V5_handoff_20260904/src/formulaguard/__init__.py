"""FormulaGuard research prototype."""

from .api import LocalizationResult, diagnose, localize
from .v4x import VERSION_ALIASES, V42Decision, v4_1_scores, v4_2_review, v4_3_scores
from .v5_core import v5_core_scores
from .v5_core_r2 import v5_core_r2_scores
from .v5_psl import DiagnosticState, PSLConfig, SelectiveDiagnosis, v5_psl_scores
from .v6 import v6_scores
from .v5_structural_guard import (
    MODEL_VERSION as V5_STRUCTURAL_GUARD_VERSION,
    v5_structural_guard_default_parameters,
    v5_structural_guard_scores,
)
from .model_discovery import (
    SignalAuditConfig,
    audit_workbook,
    validate_label_free_output,
)
from .workbook import WorkbookModel

__all__ = [
    "WorkbookModel", "LocalizationResult", "SelectiveDiagnosis", "DiagnosticState",
    "PSLConfig", "diagnose", "localize", "VERSION_ALIASES",
    "V42Decision", "v4_1_scores", "v4_2_review", "v4_3_scores",
    "v5_core_scores", "v5_core_r2_scores", "v5_psl_scores", "v6_scores",
    "SignalAuditConfig", "audit_workbook", "validate_label_free_output",
    "V5_STRUCTURAL_GUARD_VERSION", "v5_structural_guard_default_parameters",
    "v5_structural_guard_scores",
]
__version__ = "0.1.0"
