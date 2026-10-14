"""Target-masked integrity certificates for OOXML shared-formula regions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .a1 import num_to_col, parse_address
from .formula import (
    FormulaSyntaxError,
    normalized_formula,
    parse_formula,
    translate_formula,
)
from .workbook import CellKey, SharedFormulaRegion, WorkbookModel

PROTOCOL = "formulaguard_shared_formula_region_integrity_v1"
MIN_REGION_CELLS = 5
REVIEW_BUDGET = 5


@dataclass(frozen=True)
class SharedFormulaIntegrityCertificate:
    protocol: str
    sheet: str
    group_id: str
    master_cell: CellKey
    region_start: str
    region_end: str
    expected_member_count: int
    observed_member_count: int
    target_formula_cell: CellKey
    candidate_formula: str
    target_excluded: bool = True
    candidate_derived_without_observed_target: bool = True
    observed_target_used_for_comparison: bool = False
    can_identify_formula_error: bool = False


@dataclass(frozen=True)
class SharedFormulaIntegrityComparison:
    certificate: SharedFormulaIntegrityCertificate
    observed_formula: str
    candidate_formula: str
    observed_disagrees: bool
    comparison_supported: bool = True
    observed_target_used_for_comparison: bool = True
    automatic_edit_supported: bool = False


@dataclass(frozen=True)
class SharedFormulaIntegrityResult:
    protocol: str
    declared_region_count: int
    certificates: tuple[SharedFormulaIntegrityCertificate, ...]
    comparisons: tuple[SharedFormulaIntegrityComparison, ...]
    disagreement_cells: tuple[CellKey, ...]
    deterministic_candidate: SharedFormulaIntegrityComparison | None
    abstain_reason: str | None


def _region_cells(region: SharedFormulaRegion) -> tuple[CellKey, ...]:
    start = parse_address(region.start)
    end = parse_address(region.end)
    return tuple(
        (region.sheet, f"{num_to_col(column)}{row}")
        for row in range(start.row, end.row + 1)
        for column in range(start.col, end.col + 1)
    )


def _certificate_for_region(
    model: WorkbookModel,
    region: SharedFormulaRegion,
) -> SharedFormulaIntegrityCertificate | None:
    expected = _region_cells(region)
    if len(expected) < MIN_REGION_CELLS:
        return None
    expected_set = set(expected)
    members = set(region.members)
    if not members < expected_set or len(expected_set - members) != 1:
        return None
    if any(model.formula_kind(member) != "shared" for member in members):
        return None
    if any(
        other.group_id != region.group_id
        and expected_set.intersection(_region_cells(other))
        for other in model.shared_formula_regions
    ):
        return None
    target = next(iter(expected_set - members))
    if (
        target not in model.formulas
        or not model.is_visible(target)
        or model.is_merged(target)
        or model.formula_kind(target) != "normal"
        or model.shared_formula_group(target) is not None
    ):
        return None
    try:
        candidate = translate_formula(
            region.master_formula,
            region.master_cell[1],
            target[1],
        )
        parse_formula(candidate)
    except (FormulaSyntaxError, KeyError, TypeError, ValueError):
        return None
    return SharedFormulaIntegrityCertificate(
        protocol=PROTOCOL,
        sheet=region.sheet,
        group_id=region.group_id,
        master_cell=region.master_cell,
        region_start=region.start,
        region_end=region.end,
        expected_member_count=len(expected),
        observed_member_count=len(members),
        target_formula_cell=target,
        candidate_formula=candidate,
    )


def discover_shared_formula_integrity_certificates(
    model: WorkbookModel,
) -> tuple[SharedFormulaIntegrityCertificate, ...]:
    """Derive candidates from valid shared masters without reading target text."""

    certificates = tuple(
        certificate
        for region in model.shared_formula_regions
        for certificate in (_certificate_for_region(model, region),)
        if certificate is not None
    )
    return tuple(
        sorted(
            certificates,
            key=lambda item: (
                item.sheet,
                item.region_start,
                item.region_end,
                item.group_id,
            ),
        )
    )


def analyze_shared_formula_integrity(
    model: WorkbookModel,
) -> SharedFormulaIntegrityResult:
    certificates = discover_shared_formula_integrity_certificates(model)
    comparisons = tuple(
        SharedFormulaIntegrityComparison(
            certificate=certificate,
            observed_formula=model.formulas[certificate.target_formula_cell],
            candidate_formula=certificate.candidate_formula,
            observed_disagrees=(
                normalized_formula(
                    model.formulas[certificate.target_formula_cell]
                )
                != normalized_formula(certificate.candidate_formula)
            ),
        )
        for certificate in certificates
    )
    disagreements = tuple(
        comparison
        for comparison in comparisons
        if comparison.observed_disagrees
    )
    if len(disagreements) == 1:
        candidate = disagreements[0]
        abstain_reason = None
    elif disagreements:
        candidate = None
        abstain_reason = "multiple_schema_disagreements"
    else:
        candidate = None
        abstain_reason = (
            "no_schema_disagreement" if certificates else "no_eligible_region"
        )
    return SharedFormulaIntegrityResult(
        protocol=PROTOCOL,
        declared_region_count=len(model.shared_formula_regions),
        certificates=certificates,
        comparisons=comparisons,
        disagreement_cells=tuple(
            comparison.certificate.target_formula_cell
            for comparison in disagreements
        ),
        deterministic_candidate=candidate,
        abstain_reason=abstain_reason,
    )


def v4_sfri_fifth(
    model: WorkbookModel,
    v4_ranking: Sequence[CellKey],
) -> tuple[CellKey, ...]:
    """Apply the frozen V4 Top-4 plus one SFRI fifth-place adapter."""

    ranking = tuple(v4_ranking)
    if len(ranking) != len(set(ranking)) or set(ranking) != set(model.formula_cells):
        raise ValueError("V4 ranking must contain every formula cell exactly once")
    result = analyze_shared_formula_integrity(model)
    if result.deterministic_candidate is None:
        return ranking
    target = result.deterministic_candidate.certificate.target_formula_cell
    if target in ranking[:REVIEW_BUDGET] or len(ranking) <= REVIEW_BUDGET:
        return ranking
    return (*ranking[: REVIEW_BUDGET - 1], target, *(
        cell for cell in ranking[REVIEW_BUDGET - 1 :] if cell != target
    ))


__all__ = [
    "MIN_REGION_CELLS",
    "PROTOCOL",
    "REVIEW_BUDGET",
    "SharedFormulaIntegrityCertificate",
    "SharedFormulaIntegrityComparison",
    "SharedFormulaIntegrityResult",
    "analyze_shared_formula_integrity",
    "discover_shared_formula_integrity_certificates",
    "v4_sfri_fifth",
]
