"""Group-aware fusion of StructuralGuard and FormulaGuard V5 evidence."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from structuralguard.formula import profile_formula, translate_formula


@dataclass(frozen=True)
class GroupEvidence:
    group_id: str
    sheet: str
    column: str
    start_row: int
    end_row: int
    size: int
    consensus_ratio: float
    group_score: float
    consensus_formula: str
    source_sheet: str


def _split_label(label: str) -> tuple[str, str, int, str]:
    sheet, cell = label.split("!", 1)
    index = 0
    while index < len(cell) and cell[index].isalpha():
        index += 1
    return sheet, cell, int(cell[index:]), cell[:index]


def build_parallel_group_evidence(
    formulas: Mapping[str, str],
    parallel_sheets: Sequence[str],
    *,
    minimum_consensus: int = 3,
) -> tuple[dict[str, GroupEvidence], list[GroupEvidence]]:
    """Find contiguous cells that disagree with a cross-sheet majority template.

    This bridge is intentionally group-level: StructuralGuard supplies normalized
    formula representations, while FormulaGuard later supplies impact/rank evidence.
    It does not use labels or the answer key.
    """
    by_position: dict[tuple[str, int], list[tuple[str, str, str]]] = defaultdict(list)
    sheet_set = set(parallel_sheets)
    for label, formula in formulas.items():
        sheet, cell, row, column = _split_label(label)
        if sheet not in sheet_set:
            continue
        try:
            shape = profile_formula(formula, cell, sheet).exact_shape
        except ValueError:
            continue
        by_position[(column, row)].append((sheet, shape, formula))

    mismatches: dict[tuple[str, str], list[tuple[int, float, str, str]]] = defaultdict(list)
    for (column, row), entries in by_position.items():
        if len(entries) != len(parallel_sheets):
            continue
        counts = Counter(shape for _, shape, _ in entries)
        consensus_shape, count = min(counts.items(), key=lambda item: (-item[1], item[0]))
        if count < minimum_consensus:
            continue
        consensus_ratio = count / len(entries)
        source_sheet, _, consensus_formula = min(
            (entry for entry in entries if entry[1] == consensus_shape),
            key=lambda entry: entry[0],
        )
        for sheet, shape, _ in entries:
            if shape != consensus_shape:
                mismatches[(sheet, column)].append(
                    (row, consensus_ratio, consensus_formula, source_sheet)
                )

    groups: list[GroupEvidence] = []
    by_cell: dict[str, GroupEvidence] = {}
    for (sheet, column), rows in sorted(mismatches.items()):
        rows.sort()
        runs: list[list[tuple[int, float, str, str]]] = []
        for item in rows:
            if not runs or item[0] != runs[-1][-1][0] + 1:
                runs.append([item])
            else:
                runs[-1].append(item)
        for run_index, run in enumerate(runs, 1):
            start_row, end_row = run[0][0], run[-1][0]
            size = len(run)
            consensus_ratio = sum(item[1] for item in run) / size
            run_strength = min(1.0, math.log1p(size) / math.log1p(300))
            group_score = min(1.0, 0.65 * consensus_ratio + 0.35 * run_strength)
            consensus_formula = run[0][2]
            source_sheet = run[0][3]
            group = GroupEvidence(
                group_id=f"{sheet}!{column}{start_row}:{column}{end_row}#{run_index}",
                sheet=sheet,
                column=column,
                start_row=start_row,
                end_row=end_row,
                size=size,
                consensus_ratio=consensus_ratio,
                group_score=group_score,
                consensus_formula=consensus_formula,
                source_sheet=source_sheet,
            )
            groups.append(group)
            for row, _, source_formula, source in run:
                target_cell = f"{column}{row}"
                source_cell = f"{column}{row}"
                candidate = translate_formula(source_formula, source_cell, target_cell)
                cell_group = GroupEvidence(
                    **{**group.__dict__, "consensus_formula": candidate, "source_sheet": source}
                )
                by_cell[f"{sheet}!{target_cell}"] = cell_group
    return by_cell, groups


def fuse_rankings(
    structural_rows: Sequence[Mapping[str, object]],
    formula_rows: Sequence[Mapping[str, object]],
    formulas: Mapping[str, str],
    parallel_sheets: Sequence[str],
) -> tuple[list[dict[str, object]], list[GroupEvidence]]:
    structural = {
        f"{row['sheet']}!{row['cell']}": row for row in structural_rows
    }
    formula = {str(row["cell"]): row for row in formula_rows}
    n = max(1, len(formula))
    group_by_cell, groups = build_parallel_group_evidence(formulas, parallel_sheets)
    output: list[dict[str, object]] = []
    for label in sorted(set(structural) | set(formula)):
        sg = structural.get(label, {})
        fg = formula.get(label, {})
        sg_score = float(sg.get("structural_score", 0.0))
        fg_rank = int(fg.get("rank", n))
        fg_percentile = 1.0 - (fg_rank - 1) / max(1, n - 1)
        group = group_by_cell.get(label)
        group_base = group.group_score if group else 0.0
        # FormulaGuard affects prioritization but cannot create group evidence alone.
        group_signal = group_base * (0.75 + 0.25 * fg_percentile)
        hybrid_score = 1.0 - (1.0 - sg_score) * (1.0 - group_signal)
        if group and sg_score >= 0.55:
            status = "local_and_systemic"
        elif group:
            status = "systemic_group"
        elif sg_score >= 0.55:
            status = "local_anomaly"
        else:
            status = "low_risk"
        output.append({
            "cell": label,
            "hybrid_score": hybrid_score,
            "status": status,
            "structural_score": sg_score,
            "formulaguard_rank": fg_rank,
            "formulaguard_percentile": fg_percentile,
            "group_id": group.group_id if group else None,
            "group_size": group.size if group else 0,
            "group_score": group_base,
            "suggested_formula": (
                group.consensus_formula if group
                else sg.get("suggested_formula")
            ),
            "suggestion_source": (
                f"parallel-sheet:{group.source_sheet}" if group
                else sg.get("suggestion_source")
            ),
        })
    output.sort(key=lambda row: (-float(row["hybrid_score"]), str(row["cell"])))
    for rank, row in enumerate(output, 1):
        row["rank"] = rank
    return output, groups


def fuse_hierarchical(
    structural_rows: Sequence[Mapping[str, object]],
    formula_rows: Sequence[Mapping[str, object]],
    formulas: Mapping[str, str],
    group_by_cell: Mapping[str, GroupEvidence],
    group_validations: Mapping[str, object],
) -> list[dict[str, object]]:
    """Fuse local scores with validated systemic groups, without full FG ranking."""
    structural = {f"{row['sheet']}!{row['cell']}": row for row in structural_rows}
    formula = {str(row["cell"]): row for row in formula_rows}
    output: list[dict[str, object]] = []
    for label in sorted(formulas):
        sg = structural.get(label, {})
        fg = formula.get(label, {})
        sg_score = float(sg.get("structural_score", 0.0))
        fg_score = float(fg.get("score", 0.0))
        local_signal = 1.0 - (1.0 - sg_score) * (1.0 - fg_score)
        group = group_by_cell.get(label)
        validation = group_validations.get(group.group_id) if group else None
        validated = bool(getattr(validation, "accepted", False))
        validation_score = float(getattr(validation, "validation_score", 0.0))
        group_signal = (
            group.group_score * (0.80 + 0.20 * validation_score)
            if group and validated else 0.0
        )
        hybrid_score = 1.0 - (1.0 - local_signal) * (1.0 - group_signal)
        if group and validated and local_signal >= 0.55:
            status = "validated_local_and_systemic"
        elif group and validated:
            status = "validated_systemic_group"
        elif group:
            status = "unvalidated_group_review"
        elif local_signal >= 0.55:
            status = "local_anomaly"
        else:
            status = "low_risk"
        output.append({
            "cell": label,
            "hybrid_score": hybrid_score,
            "status": status,
            "structural_score": sg_score,
            "formulaguard_v5_score": fg_score,
            "formulaguard_v5_rank": fg.get("rank"),
            "group_id": group.group_id if group else None,
            "group_size": group.size if group else 0,
            "group_score": group.group_score if group else 0.0,
            "representative_validation_score": validation_score,
            "group_validated": validated,
            "suggested_formula": (
                group.consensus_formula if group and validated
                else fg.get("candidate_formula") or sg.get("suggested_formula")
            ),
            "suggestion_source": (
                f"validated-parallel-sheet:{group.source_sheet}"
                if group and validated
                else ("formulaguard-v5" if fg.get("candidate_formula") else sg.get("suggestion_source"))
            ),
        })
    output.sort(key=lambda row: (-float(row["hybrid_score"]), str(row["cell"])))
    for rank, row in enumerate(output, 1):
        row["rank"] = rank
    return output
