"""Stable dispatcher for FormulaGuard and canonical post-V4 aliases."""

from __future__ import annotations

from .localize import LocalizationResult, localize as _legacy_localize
from .v4_peer_fifth import v4_peer_fifth_scores
from .v4_static_allocator import v4_static_allocator_scores
from .v4_static_fifth import v4_static_fifth_scores
from .v4x import v4_1_scores, v4_3_scores
from .v5_core import v5_core_scores
from .v5_core_r2 import v5_core_r2_scores
from .v5_psl import SelectiveDiagnosis, diagnose_v5_psl, v5_psl_scores
from .v6 import v6_scores
from .workbook import WorkbookModel


def localize(model: WorkbookModel, method: str = "formulaguard", **kwargs) -> list[LocalizationResult]:
    normalized = method.lower().replace("-", "_")
    if normalized in {"v5_psl", "formulaguard_v5_psl", "v5_psl_dev1"}:
        config = kwargs.pop("config", None)
        ablation = kwargs.pop("ablation", None)
        if kwargs:
            raise TypeError(f"Unsupported V5-PSL arguments: {', '.join(sorted(kwargs))}")
        return v5_psl_scores(model, config=config, ablation=ablation)
    if normalized in {
        "formulaguard_v5_core_r2", "v5_core_r2", "v5_core_r2_full",
        "v5_core_r2_source", "v5_core_r2_placebo",
    }:
        stage = kwargs.pop(
            "stage",
            "source" if normalized.endswith("_source") else (
                "placebo" if normalized.endswith("_placebo") else "full"
            ),
        )
        config = kwargs.pop("config", None)
        candidate_limit = int(kwargs.pop("candidate_limit", 24))
        intervention_limit = int(kwargs.pop("intervention_limit", 4))
        matched_controls = int(kwargs.pop("matched_controls", 8))
        uncertainty_limit = int(kwargs.pop("uncertainty_limit", 12))
        ablation = kwargs.pop("ablation", None)
        candidate_keep_fraction = float(kwargs.pop("candidate_keep_fraction", 1.0))
        if kwargs:
            raise TypeError(f"Unsupported V5-Core R2 arguments: {', '.join(sorted(kwargs))}")
        return v5_core_r2_scores(
            model,
            stage=str(stage),
            config=config,
            candidate_limit=candidate_limit,
            intervention_limit=intervention_limit,
            matched_controls=matched_controls,
            uncertainty_limit=uncertainty_limit,
            ablation=ablation,
            candidate_keep_fraction=candidate_keep_fraction,
        )
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
    if normalized in {
        "v4_peer_fifth_experimental", "formulaguard_v4_peer_fifth",
    }:
        candidate_limit = int(kwargs.pop("candidate_limit", 15))
        if kwargs:
            raise TypeError(
                f"Unsupported V4 peer-fifth arguments: {', '.join(sorted(kwargs))}"
            )
        return v4_peer_fifth_scores(model, candidate_limit=candidate_limit)
    if normalized in {
        "v4_static_allocator_experimental", "formulaguard_v4_static_allocator",
    }:
        candidate_limit = int(kwargs.pop("candidate_limit", 15))
        if kwargs:
            raise TypeError(
                f"Unsupported V4 static-allocator arguments: {', '.join(sorted(kwargs))}"
            )
        return v4_static_allocator_scores(model, candidate_limit=candidate_limit)
    if normalized in {
        "v4_static_fifth_experimental", "formulaguard_v4_static_fifth",
    }:
        candidate_limit = int(kwargs.pop("candidate_limit", 15))
        if kwargs:
            raise TypeError(
                f"Unsupported V4 static-fifth arguments: {', '.join(sorted(kwargs))}"
            )
        return v4_static_fifth_scores(model, candidate_limit=candidate_limit)
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


def diagnose(model: WorkbookModel, method: str = "v5_psl", **kwargs) -> SelectiveDiagnosis:
    """Return a workbook-level selective decision plus the complete ranking."""
    normalized = method.lower().replace("-", "_")
    if normalized not in {"v5_psl", "formulaguard_v5_psl", "v5_psl_dev1"}:
        raise ValueError("Selective diagnosis is currently defined only for V5-PSL")
    config = kwargs.pop("config", None)
    ablation = kwargs.pop("ablation", None)
    if kwargs:
        raise TypeError(f"Unsupported V5-PSL arguments: {', '.join(sorted(kwargs))}")
    return diagnose_v5_psl(model, config=config, ablation=ablation)


__all__ = [
    "LocalizationResult", "SelectiveDiagnosis", "diagnose", "localize",
    "v4_1_scores", "v4_3_scores", "v4_peer_fifth_scores",
    "v4_static_allocator_scores", "v4_static_fifth_scores",
    "v5_core_scores", "v5_core_r2_scores",
    "v5_psl_scores", "v6_scores",
]
