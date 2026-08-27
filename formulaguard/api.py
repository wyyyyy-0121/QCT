"""Stable dispatcher for FormulaGuard and canonical post-V4 aliases."""

from __future__ import annotations

from .localize import LocalizationResult, localize as _legacy_localize
from .v4x import v4_1_scores, v4_3_scores
from .v5_core import v5_core_scores
from .v6 import v6_scores
from .workbook import WorkbookModel


def localize(model: WorkbookModel, method: str = "formulaguard", **kwargs) -> list[LocalizationResult]:
    normalized = method.lower().replace("-", "_")
    if normalized in {
        "formulaguard_v5_core", "formulaguard_v5_core_rule", "v5_core", "v5_core_rule",
        "formulaguard_v5_core_learned", "v5_core_learned",
    }:
        head = kwargs.pop(
            "head",
            "learned" if normalized.endswith("_learned") else "rule",
        )
        config = kwargs.pop("config", None)
        candidate_limit = int(kwargs.pop("candidate_limit", 32))
        base_interventions = int(kwargs.pop("base_interventions", 2))
        deep_cell_limit = int(kwargs.pop("deep_cell_limit", 120))
        deep_candidate_limit = int(kwargs.pop("deep_candidate_limit", 8))
        if kwargs:
            raise TypeError(f"Unsupported V5-Core arguments: {', '.join(sorted(kwargs))}")
        return v5_core_scores(
            model,
            head=str(head),
            config=config,
            candidate_limit=candidate_limit,
            base_interventions=base_interventions,
            deep_cell_limit=deep_cell_limit,
            deep_candidate_limit=deep_candidate_limit,
        )
    if normalized in {"v4.1", "v4_1", "formulaguard_v4_1"}:
        candidate_limit = int(kwargs.pop("candidate_limit", 15))
        if kwargs:
            raise TypeError(f"Unsupported V4.1 arguments: {', '.join(sorted(kwargs))}")
        return v4_1_scores(model, candidate_limit=candidate_limit)
    if normalized in {
        "v4.3", "v4_3", "formulaguard_v4_3", "formulaguard_v4_3_a",
        "formulaguard_v4_3_b", "formulaguard_v4_3_c",
    }:
        variant = kwargs.pop(
            "variant",
            normalized[-1] if normalized[-2:] in {"_a", "_b", "_c"} else "c",
        )
        base_limit = int(kwargs.pop("base_candidate_limit", kwargs.pop("candidate_limit", 15)))
        semantic_limit = int(kwargs.pop("semantic_candidate_limit", 25))
        if kwargs:
            raise TypeError(f"Unsupported V4.3 arguments: {', '.join(sorted(kwargs))}")
        return v4_3_scores(
            model,
            variant=str(variant),
            base_candidate_limit=base_limit,
            semantic_candidate_limit=semantic_limit,
        )
    if normalized in {"v6", "formulaguard_v6", "formulaguard_v6_a", "formulaguard_v6_b", "formulaguard_v6_c"}:
        variant = kwargs.pop("variant", normalized[-1] if normalized[-2:] in {"_a", "_b", "_c"} else "c")
        base_limit = int(kwargs.pop("base_candidate_limit", kwargs.pop("candidate_limit", 15)))
        semantic_limit = int(kwargs.pop("semantic_candidate_limit", 25))
        if kwargs:
            raise TypeError(f"Unsupported V6 arguments: {', '.join(sorted(kwargs))}")
        return v6_scores(
            model,
            variant=variant,
            base_candidate_limit=base_limit,
            semantic_candidate_limit=semantic_limit,
        )
    return _legacy_localize(model, method, **kwargs)


__all__ = [
    "LocalizationResult", "localize", "v4_1_scores", "v4_3_scores",
    "v5_core_scores", "v6_scores",
]
