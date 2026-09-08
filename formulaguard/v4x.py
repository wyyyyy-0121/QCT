"""Canonical V4.x names for the post-V4 mechanism studies.

The original module names and evidence identifiers are immutable research
artifacts.  These wrappers expose the corrected scientific lineage without
changing the frozen V4, legacy V5/V5.2, or completed V6 implementations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .localize import LocalizationResult
from .v5 import v5_default_parameters, v5_scores
from .v6 import v6_default_parameters, v6_scores
from .v52 import RescueEvidence, V52Decision, v52_default_parameters, v52_scores
from .workbook import WorkbookModel

VERSION_ALIASES = {
    "v4.1": {
        "canonical_id": "v4.1-pcg-r1",
        "legacy_id": "v5-pcg-r1",
        "legacy_module": "formulaguard.v5",
        "role": "direct_pattern_counterfactual_reranking_experiment",
        "status": "rejected",
    },
    "v4.2": {
        "canonical_id": "v4.2-review-b",
        "legacy_id": "v5.2-b",
        "legacy_module": "formulaguard.v52",
        "role": "non_interfering_sixth_review_slot",
        "status": "frozen_auxiliary",
    },
    "v4.3": {
        "canonical_id": "v4.3-semantic-r1",
        "legacy_id": "v6-semantic-r1",
        "legacy_module": "formulaguard.v6",
        "role": "semantic_reranking_mechanism_experiment",
        "status": "rejected_for_main_freeze",
    },
    "v5": {
        "canonical_id": "v5-psl-dev1-rev1",
        "legacy_id": None,
        "legacy_module": None,
        "role": "static_anchor_repair_verified_selective_localization",
        "status": "rejected_public_pressure_revision",
    },
    "v5-core-cc": {
        "canonical_id": "v5-core-candidate-centric-dev",
        "legacy_id": None,
        "legacy_module": "formulaguard.v5_core",
        "role": "candidate_centric_core_reconstruction",
        "status": "rejected_locked_validation",
    },
    "v5-core-r2": {
        "canonical_id": "v5-core-r2-dnca-dev",
        "legacy_id": None,
        "legacy_module": "formulaguard.v5_core_r2",
        "role": "dual_null_causal_attribution_research_line",
        "status": "rejected_pressure_safety",
    },
}


def _relabel_results(
    results: Sequence[LocalizationResult],
    *,
    canonical_version: str,
) -> list[LocalizationResult]:
    relabeled = []
    for result in results:
        evidence = dict(result.evidence)
        legacy_version = str(evidence.get("model_version", ""))
        evidence.update({
            "legacy_model_version": legacy_version,
            "model_version": canonical_version,
            "canonical_model_version": canonical_version,
            "version_lineage": "post_v4_mechanism_study",
        })
        relabeled.append(LocalizationResult(
            cell=result.cell,
            score=result.score,
            candidate_formula=result.candidate_formula,
            evidence=evidence,
        ))
    return relabeled


def v4_1_default_parameters() -> dict[str, float | int | str]:
    parameters = dict(v5_default_parameters())
    parameters["legacy_model_version"] = str(parameters["model_version"])
    parameters["model_version"] = "v4.1-pcg-r1"
    parameters["version_lineage"] = "post_v4_direct_reranking_experiment"
    return parameters


def v4_1_scores(
    model: WorkbookModel,
    *,
    candidate_limit: int = 15,
) -> list[LocalizationResult]:
    """Canonical V4.1 alias for the rejected legacy V5 PCG experiment."""
    return _relabel_results(
        v5_scores(model, candidate_limit=candidate_limit),
        canonical_version="v4.1-pcg-r1",
    )


@dataclass(frozen=True)
class V42Decision:
    """Canonical V4.2 view of one legacy V5.2 review decision."""

    canonical_version: str
    legacy_model_version: str
    variant: str
    core_ranking: tuple[LocalizationResult, ...]
    rescue: RescueEvidence | None
    eligible: tuple[RescueEvidence, ...]
    status: str
    reason: str
    pattern_elite_limit: int

    @property
    def core_top5(self) -> tuple[LocalizationResult, ...]:
        return self.core_ranking[:5]

    @property
    def review_set(self) -> tuple[LocalizationResult, ...]:
        if self.rescue is None:
            return self.core_top5
        return self.core_top5 + (self.rescue.result,)


def _relabel_rescue(
    rescue: RescueEvidence,
    lookup: dict[tuple[str, str], LocalizationResult],
) -> RescueEvidence:
    return RescueEvidence(
        result=lookup[rescue.result.cell],
        v4_rank=rescue.v4_rank,
        formula_rank=rescue.formula_rank,
        irg=rescue.irg,
        delta=rescue.delta,
        repair_source_count=rescue.repair_source_count,
        repair_sources=rescue.repair_sources,
        reference_quality=rescue.reference_quality,
        repair_parseable=rescue.repair_parseable,
    )


def v4_2_default_parameters(variant: str = "b") -> dict[str, float | int | str]:
    parameters = dict(v52_default_parameters(variant))
    parameters["legacy_model_version"] = str(parameters["model_version"])
    parameters["model_version"] = f"v4.2-review-{variant.lower()}"
    parameters["version_lineage"] = "post_v4_non_interference_review_study"
    return parameters


def v4_2_review(
    model: WorkbookModel,
    *,
    variant: str = "b",
    candidate_limit: int = 15,
) -> V42Decision:
    """Return the canonical V4.2 review object without changing its decisions."""
    legacy: V52Decision = v52_scores(
        model,
        variant=variant,
        candidate_limit=candidate_limit,
    )
    core = tuple(_relabel_results(
        legacy.core_ranking,
        canonical_version=f"v4.2-review-{legacy.variant}",
    ))
    lookup = {item.cell: item for item in core}
    eligible = tuple(_relabel_rescue(item, lookup) for item in legacy.eligible)
    rescue = _relabel_rescue(legacy.rescue, lookup) if legacy.rescue is not None else None
    return V42Decision(
        canonical_version=f"v4.2-review-{legacy.variant}",
        legacy_model_version=f"v5.2-{legacy.variant}",
        variant=legacy.variant,
        core_ranking=core,
        rescue=rescue,
        eligible=eligible,
        status=legacy.status,
        reason=legacy.reason,
        pattern_elite_limit=legacy.pattern_elite_limit,
    )


def v4_3_default_parameters(variant: str = "c") -> dict[str, object]:
    parameters = dict(v6_default_parameters())
    parameters["legacy_model_version"] = str(parameters["model_version"])
    parameters["model_version"] = f"v4.3-semantic-{variant.lower()}"
    parameters["variant"] = variant.lower()
    parameters["version_lineage"] = "post_v4_semantic_reranking_study"
    return parameters


def v4_3_scores(
    model: WorkbookModel,
    *,
    variant: str = "c",
    base_candidate_limit: int = 15,
    semantic_candidate_limit: int = 25,
) -> list[LocalizationResult]:
    """Canonical V4.3 alias for the completed legacy V6 semantic study."""
    normalized = variant.lower()
    return _relabel_results(
        v6_scores(
            model,
            variant=normalized,
            base_candidate_limit=base_candidate_limit,
            semantic_candidate_limit=semantic_candidate_limit,
        ),
        canonical_version=f"v4.3-semantic-{normalized}",
    )


__all__ = [
    "VERSION_ALIASES",
    "V42Decision",
    "v4_1_default_parameters",
    "v4_1_scores",
    "v4_2_default_parameters",
    "v4_2_review",
    "v4_3_default_parameters",
    "v4_3_scores",
]
