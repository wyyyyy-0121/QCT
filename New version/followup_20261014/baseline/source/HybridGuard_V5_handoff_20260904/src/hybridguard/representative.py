"""Fast FormulaGuard-based validation for representatives of systemic groups."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from formulaguard.a1 import iter_rect
from formulaguard.formula import Range, Ref, edit_cost, iter_refs, parse_formula
from formulaguard.workbook import WorkbookModel

from .hybrid import GroupEvidence


@dataclass(frozen=True)
class RepresentativeValidation:
    group_id: str
    cell: str
    candidate_formula: str
    parse_valid: bool
    reference_quality: float
    actual_evaluation_valid: bool
    candidate_evaluation_valid: bool
    actual_value: object
    candidate_value: object
    relative_output_change: float
    impact_observed: bool
    edit_cost: float
    accepted: bool
    validation_score: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GroupValidation:
    group_id: str
    representative_count: int
    accepted_count: int
    accepted: bool
    validation_score: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def representative_rows(group: GroupEvidence) -> list[int]:
    """Return deterministic start/middle/end representatives for a group."""
    if group.size <= 1:
        return [group.start_row]
    middle = (group.start_row + group.end_row) // 2
    return sorted({group.start_row, middle, group.end_row})


def _references(formula: str, current_sheet: str) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for item in iter_refs(parse_formula(formula)):
        if isinstance(item, Ref):
            output.append((item.sheet or current_sheet, item.address.a1.replace("$", "")))
        elif isinstance(item, Range):
            sheet = item.start.sheet or item.end.sheet or current_sheet
            output.extend(
                (sheet, address)
                for address in iter_rect(item.start.address, item.end.address)
            )
    return output


def _safe_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_group_representatives(
    model: WorkbookModel,
    groups: Sequence[GroupEvidence],
    group_by_cell: Mapping[str, GroupEvidence],
) -> tuple[list[RepresentativeValidation], dict[str, GroupValidation]]:
    """Validate cross-sheet repair candidates without exhaustive interventions.

    The cross-sheet majority proposes a candidate. FormulaGuard supplies its
    parser, reference model, edit distance and evaluator as a bounded safety
    gate on only start/middle/end representatives.
    """
    representatives: list[RepresentativeValidation] = []
    by_group: dict[str, list[RepresentativeValidation]] = {}
    populated = set(model.cells) | set(model.formulas)

    for group in groups:
        current: list[RepresentativeValidation] = []
        for row in representative_rows(group):
            address = f"{group.column}{row}"
            label = f"{group.sheet}!{address}"
            key = (group.sheet, address)
            evidence = group_by_cell[label]
            candidate = evidence.consensus_formula
            actual = model.formulas[key]

            try:
                refs = _references(candidate, group.sheet)
                parse_valid = True
            except Exception:
                refs = []
                parse_valid = False
            reference_quality = (
                sum(ref in populated for ref in refs) / len(refs)
                if refs else (1.0 if parse_valid else 0.0)
            )

            actual_values, actual_errors = model.evaluate(targets=[key])
            candidate_values, candidate_errors = model.evaluate(
                {key: candidate}, targets=[key]
            )
            actual_valid = key not in actual_errors
            candidate_valid = key not in candidate_errors
            actual_value = actual_values.get(key)
            candidate_value = candidate_values.get(key)
            left = _safe_number(actual_value)
            right = _safe_number(candidate_value)
            relative_change = (
                abs(right - left) / max(1.0, abs(left))
                if left is not None and right is not None else 0.0
            )
            distance = edit_cost(actual, candidate) if parse_valid else math.inf
            formula_changed = actual != candidate
            impact_observed = relative_change > 1e-9
            accepted = (
                parse_valid
                and reference_quality >= 0.80
                and actual_valid
                and candidate_valid
                and formula_changed
            )
            score = (
                0.25 * float(parse_valid)
                + 0.25 * reference_quality
                + 0.20 * float(actual_valid and candidate_valid)
                + 0.20 * min(1.0, relative_change / 0.05)
                + 0.10 * (1.0 / (1.0 + distance) if math.isfinite(distance) else 0.0)
            )
            item = RepresentativeValidation(
                group_id=group.group_id,
                cell=label,
                candidate_formula=candidate,
                parse_valid=parse_valid,
                reference_quality=reference_quality,
                actual_evaluation_valid=actual_valid,
                candidate_evaluation_valid=candidate_valid,
                actual_value=actual_value,
                candidate_value=candidate_value,
                relative_output_change=relative_change,
                impact_observed=impact_observed,
                edit_cost=distance,
                accepted=accepted,
                validation_score=score,
            )
            representatives.append(item)
            current.append(item)
        by_group[group.group_id] = current

    group_results: dict[str, GroupValidation] = {}
    for group_id, rows in by_group.items():
        accepted_count = sum(row.accepted for row in rows)
        required = len(rows) // 2 + 1
        group_results[group_id] = GroupValidation(
            group_id=group_id,
            representative_count=len(rows),
            accepted_count=accepted_count,
            accepted=accepted_count >= required,
            validation_score=sum(row.validation_score for row in rows) / len(rows),
        )
    return representatives, group_results
