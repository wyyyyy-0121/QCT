"""V5.1.2: candidate-specific structural evidence and atomic acceptance.

Scores are diagnostic scores, not calibrated correctness probabilities.
Row/column copy regions provide evidence independently of business headers.
Semantic proposals never authorize a repair without observed candidate anchors.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby

from .a1 import parse_address
from .formula import Binary, Func, Number, Range, Ref, Unary, parse_formula
from .localize import LocalizationResult
from .v5_1_1_development import _role_candidates
from .v5_1_development import _safe_translate, _signature
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5.1.2-development"


@dataclass(frozen=True)
class Parameters:
    min_support: int = 3
    min_dominance: float = 0.70
    min_candidate_margin: float = 0.20
    min_anchor_each_side: int = 2
    min_group_size: int = 3

    def __post_init__(self):
        for name in ("min_support", "min_anchor_each_side", "min_group_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("min_dominance", "min_candidate_margin"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")


def v5_1_2_development_default_parameters() -> dict:
    return {
        "model_version": MODEL_VERSION,
        **vars(Parameters()),
        "axes": ["row", "column"],
        "semantic_only_acceptance": False,
        "group_acceptance": "every_member_passes_candidate_specific_gate",
        "scores_are_probabilities": False,
        "automatic_edit_applied": False,
    }


def _edit_distance(left: object, right: object) -> int:
    """Bounded shape-preserving edits; never delete factors or change constants.

Changing a function family, adding/removing an operand, or changing a literal
may encode a legal business exception. Such edits need additional evidence
outside this copy-template policy, and remain review-only here.
"""
    if type(left) is not type(right):
        return 99
    if isinstance(left, Number):
        return 0 if left.value == right.value else 99
    if isinstance(left, Ref):
        return int(left != right) if left.sheet == right.sheet else 99
    if isinstance(left, Range):
        return _edit_distance(left.start, right.start) + _edit_distance(left.end, right.end)
    if isinstance(left, Unary):
        return _edit_distance(left.value, right.value) if left.op == right.op else 99
    if isinstance(left, Binary):
        if left.op != right.op and not {left.op, right.op} <= {"+", "-", "*", "/"}:
            return 99
        return int(left.op != right.op) + _edit_distance(left.left, right.left) + _edit_distance(left.right, right.right)
    if isinstance(left, Func):
        if left.name != right.name or len(left.args) != len(right.args):
            return 99
        return sum(_edit_distance(a, b) for a, b in zip(left.args, right.args, strict=True))
    return 99


def _eligible(model: WorkbookModel, cell: CellKey) -> bool:
    address = parse_address(cell[1])
    if not model.sheet_visibility.get(cell[0], True) or not model.cell_visibility.get(cell, True):
        return False
    if address.row in model.hidden_rows.get(cell[0], ()):
        return False
    if any(lo <= address.col <= hi for lo, hi in model.hidden_columns.get(cell[0], ())):
        return False
    if model.formula_kinds.get(cell, "normal") != "normal":
        return False
    for start, end in model.merged_ranges.get(cell[0], ()):
        a, b = parse_address(start), parse_address(end)
        if a.row <= address.row <= b.row and a.col <= address.col <= b.col:
            return False
    try:
        parse_formula(model.formulas[cell])
    except (ValueError, RecursionError):
        return False
    return True


def _regions(model: WorkbookModel, axis: str):
    buckets = defaultdict(list)
    for cell in model.formula_cells:
        if not _eligible(model, cell):
            continue
        address = parse_address(cell[1])
        fixed, moving = (address.col, address.row) if axis == "column" else (address.row, address.col)
        buckets[(cell[0], fixed)].append((moving, cell))
    for key in sorted(buckets):
        current = []
        previous = None
        for position, cell in sorted(buckets[key]):
            if previous is not None and position != previous + 1:
                if current:
                    yield current
                current = []
            current.append(cell)
            previous = position
        if current:
            yield current


@dataclass(frozen=True)
class Proposal:
    cell: CellKey
    formula: str
    axis: str
    group: tuple[CellKey, ...]
    quality: float
    support: int
    left_anchors: int
    right_anchors: int
    passes: bool
    reason: str


def _proposals(model: WorkbookModel, config: Parameters) -> list[Proposal]:
    proposals = []
    for axis in ("column", "row"):
        for region in _regions(model, axis):
            runs = [(signature, list(cells)) for signature, cells in groupby(
                region, key=lambda cell: _signature(model.formulas[cell], cell[1])
            )]
            for index in range(1, len(runs) - 1):
                signature, cells = runs[index]
                left_signature, left = runs[index - 1]
                right_signature, right = runs[index + 1]
                if left_signature != right_signature or signature == left_signature:
                    continue
                support = len(left) + len(right)
                dominance = support / (support + len(cells))
                stable = support >= config.min_support and dominance >= config.min_dominance
                anchored = (
                    len(cells) >= config.min_group_size
                    and min(len(left), len(right)) >= config.min_anchor_each_side
                )
                for cell in cells:
                    candidate = _safe_translate(model.formulas[left[-1]], left[-1][1], cell[1])
                    opposite = _safe_translate(model.formulas[right[0]], right[0][1], cell[1])
                    if candidate is None or opposite is None:
                        continue
                    if _signature(candidate, cell[1]) != _signature(opposite, cell[1]):
                        continue
                    semantic_agreement = any(
                        _signature(formula, cell[1]) == _signature(candidate, cell[1])
                        for formula, _ in _role_candidates(model, cell)
                    )
                    distance = _edit_distance(parse_formula(model.formulas[cell]), parse_formula(candidate))
                    structural_gate = stable or (anchored and semantic_agreement)
                    passes = structural_gate and distance == 1
                    reason = (
                        "stable_copy_template" if stable and passes else
                        "two_sided_anchors_and_role" if passes else
                        "business_expression_change_requires_review" if distance != 1 else
                        "insufficient_candidate_support"
                    )
                    # No semantic floor. Every score is attached to observed
                    # support for this particular candidate, on this axis.
                    quality = dominance if stable else min(0.95, support / (support + 1))
                    proposals.append(Proposal(
                        cell, candidate, axis, tuple(cells), quality, support,
                        len(left), len(right), passes, reason,
                    ))
    return proposals


def v5_1_2_development_scores(
    model: WorkbookModel, *, config: Parameters | None = None,
) -> list[LocalizationResult]:
    config = config or Parameters()
    by_cell = defaultdict(list)
    proposals = _proposals(model, config)
    for proposal in proposals:
        by_cell[proposal.cell].append(proposal)
    selected = {}
    margins = {}
    ambiguous = set()
    for cell, choices in by_cell.items():
        templates = defaultdict(list)
        for choice in choices:
            templates[_signature(choice.formula, cell[1])].append(choice)
        ranked = sorted(
            templates.items(), key=lambda item: (-max(p.quality for p in item[1]), item[0])
        )
        best_score = max(p.quality for p in ranked[0][1])
        second = max(p.quality for p in ranked[1][1]) if len(ranked) > 1 else 0.0
        margins[cell] = best_score - second
        if margins[cell] < config.min_candidate_margin:
            ambiguous.add(cell)
            continue
        eligible = [p for p in ranked[0][1] if p.passes]
        if eligible:
            selected[cell] = max(eligible, key=lambda p: (p.quality, p.axis))

    # Atomic groups: every member must independently select the same proposed
    # template and pass its own gate. Losing one member rejects the whole group.
    groups = {}
    for proposal in proposals:
        identity = (proposal.axis, proposal.group)
        groups.setdefault(identity, {})[proposal.cell] = proposal
    accepted = {}
    for identity, members in sorted(groups.items()):
        if any(
            not p.passes or cell not in selected or
            _signature(selected[cell].formula, cell[1]) != _signature(p.formula, cell[1])
            for cell, p in members.items()
        ) or len(members) != len(identity[1]):
            continue
        # Do not partially materialize overlapping groups.
        if any(cell in accepted for cell in members):
            continue
        payload = [(cell, p.formula) for cell, p in sorted(members.items())]
        group_id = "v512_" + hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        minimum = min(p.quality for p in members.values())
        for cell, p in members.items():
            accepted[cell] = (p, group_id, minimum)

    results = []
    for cell in model.formula_cells:
        choices = by_cell.get(cell, [])
        item = accepted.get(cell)
        proposal = item[0] if item else max(choices, key=lambda p: p.quality, default=None)
        score = proposal.quality if proposal else 0.0
        reason = (
            proposal.reason if item else "candidate_tie_or_small_margin" if cell in ambiguous
            else "atomic_group_rejected" if cell in selected else proposal.reason if proposal
            else "unsupported_or_invisible" if not _eligible(model, cell)
            else "no_two_sided_candidate_evidence"
        )
        results.append(LocalizationResult(
            cell=cell, score=score, candidate_formula=proposal.formula if item else None,
            evidence={
                "model_version": MODEL_VERSION,
                "decision": "accepted" if item else "review" if choices else "abstained",
                "group_state": "accepted" if item else "not_applicable",
                "group_reason": reason,
                "group_id": item[1] if item else "",
                "group_size": len(proposal.group) if item else 0,
                "group_min_score": item[2] if item else 0.0,
                "candidate_score": score,
                "score_is_probability": False,
                "candidate_margin": margins.get(cell, 0.0),
                "candidate_support": proposal.support if proposal else 0,
                "left_anchors": proposal.left_anchors if proposal else 0,
                "right_anchors": proposal.right_anchors if proposal else 0,
                "candidate_axis": proposal.axis if proposal else "none",
                "review_formula": proposal.formula if proposal and not item else "",
                "automatic_edit_applied": False,
            },
        ))
    results.sort(key=lambda result: (-result.score, result.cell))
    for rank, result in enumerate(results, 1):
        result.evidence["final_rank"] = rank
    return results
