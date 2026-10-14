"""Multi-scale, explainable, structure-only formula anomaly detector."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence

from .a1 import parse_address
from .formula import FormulaProfile, profile_formula, translate_formula
from .workbook import CellKey, WorkbookSnapshot


@dataclass(frozen=True)
class DetectorConfig:
    local_radius: int = 5
    block_rows: int = 12
    block_cols: int = 4
    minimum_cohort: int = 5
    smoothing_alpha: float = 0.5
    review_score: float = 0.55
    repair_score: float = 0.72
    repair_consensus: float = 0.67
    empirical_q: float = 0.15
    disabled_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class CellRecord:
    key: CellKey
    row: int
    col: int
    formula: str
    profile: FormulaProfile

    @property
    def cell_id(self) -> str:
        return f"{self.key[0]}!{self.key[1]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entropy_reliability(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total < 2 or len(counter) <= 1:
        return min(1.0, total / 4.0)
    entropy = -sum((count / total) * math.log(count / total) for count in counter.values())
    normalized = entropy / math.log(len(counter))
    sample_strength = 1.0 - math.exp(-total / 8.0)
    return max(0.05, min(1.0, (1.0 - normalized) * sample_strength))


def _bayesian_rarity(value: str, counter: Counter[str], alpha: float) -> float:
    total = sum(counter.values())
    kinds = max(2, len(counter))
    probability = (counter.get(value, 0) + alpha) / (total + alpha * kinds)
    dominant = (max(counter.values(), default=0) + alpha) / (total + alpha * kinds)
    if dominant <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - probability / dominant))


def _weighted_support(target: CellRecord, peers: Iterable[CellRecord], attribute: str) -> tuple[float, float, str | None]:
    weights: Counter[str] = Counter()
    target_value = getattr(target.profile, attribute)
    for peer in peers:
        distance = abs(peer.row - target.row) + abs(peer.col - target.col)
        weights[getattr(peer.profile, attribute)] += 1.0 / max(1, distance)
    total = sum(weights.values())
    if not total:
        return 1.0, 0.0, None
    support = weights.get(target_value, 0.0) / total
    dominant, dominant_weight = min(weights.items(), key=lambda item: (-item[1], item[0]))
    consensus = dominant_weight / total
    return support, consensus, dominant


def _noisy_or(components: Mapping[str, tuple[float, float]]) -> tuple[float, dict[str, float]]:
    survival = 1.0
    contributions: dict[str, float] = {}
    for name, (evidence, reliability) in components.items():
        effective = max(0.0, min(0.97, evidence * reliability))
        survival *= 1.0 - effective
        contributions[name] = effective
    return 1.0 - survival, contributions


def _bh_q_values(pairs: Sequence[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(pairs, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    q_values: dict[str, float] = {}
    running = 1.0
    for rank in range(count, 0, -1):
        key, p_value = ordered[rank - 1]
        running = min(running, p_value * count / rank)
        q_values[key] = max(0.0, min(1.0, running))
    return q_values


def _translate_is_safe(formula: str, target: CellRecord) -> bool:
    if "#REF!" in formula.upper():
        return False
    try:
        profile = profile_formula(formula, target.key[1], target.key[0])
    except ValueError:
        return False
    return not profile.has_direct_self_reference


def _candidate_repair(
    target: CellRecord,
    neighbors: Sequence[CellRecord],
    desired_shape: str | None,
) -> tuple[str | None, str | None, float]:
    if desired_shape is None or desired_shape == target.profile.exact_shape:
        return None, None, 0.0
    candidates: list[tuple[int, str, str]] = []
    eligible = [peer for peer in neighbors if peer.profile.exact_shape == desired_shape]
    for peer in eligible:
        translated = translate_formula(peer.formula, peer.key[1], target.key[1])
        if _translate_is_safe(translated, target):
            distance = abs(peer.row - target.row) + abs(peer.col - target.col)
            candidates.append((distance, translated, peer.cell_id))
    if not candidates:
        return None, None, 0.0
    formula_counts = Counter(item[1] for item in candidates)
    best_formula, votes = min(formula_counts.items(), key=lambda item: (-item[1], item[0]))
    best_sources = [item for item in candidates if item[1] == best_formula]
    source = min(best_sources)[2]
    return best_formula, source, votes / len(candidates)


def analyze_snapshot(snapshot: WorkbookSnapshot, *, config: DetectorConfig | None = None) -> dict[str, object]:
    cfg = config or DetectorConfig()
    records: list[CellRecord] = []
    for key in snapshot.visible_formula_keys:
        try:
            address = parse_address(key[1])
            profile = profile_formula(snapshot.formulas[key], key[1], key[0])
        except ValueError:
            continue
        records.append(CellRecord(key, address.row, address.col, snapshot.formulas[key], profile))
    by_sheet: dict[str, list[CellRecord]] = defaultdict(list)
    by_column: dict[tuple[str, int], list[CellRecord]] = defaultdict(list)
    by_row: dict[tuple[str, int], list[CellRecord]] = defaultdict(list)
    by_block: dict[tuple[str, int, int], list[CellRecord]] = defaultdict(list)
    by_coarse_role: dict[tuple[str, int, str], list[CellRecord]] = defaultdict(list)
    for record in records:
        by_sheet[record.key[0]].append(record)
        by_column[(record.key[0], record.col)].append(record)
        by_row[(record.key[0], record.row)].append(record)
        by_block[(record.key[0], (record.row - 1) // cfg.block_rows, (record.col - 1) // cfg.block_cols)].append(record)
        by_coarse_role[(record.key[0], record.col, record.profile.shape)].append(record)
    for group in [*by_sheet.values(), *by_column.values(), *by_row.values(), *by_block.values()]:
        group.sort(key=lambda record: (record.row, record.col))

    preliminary: list[dict[str, object]] = []
    for record in records:
        column = by_column[(record.key[0], record.col)]
        row_peers = [peer for peer in by_row[(record.key[0], record.row)] if peer.key != record.key]
        local_column = [
            peer for peer in column
            if peer.key != record.key and abs(peer.row - record.row) <= cfg.local_radius
        ]
        block = [
            peer for peer in by_block[(record.key[0], (record.row - 1) // cfg.block_rows, (record.col - 1) // cfg.block_cols)]
            if peer.key != record.key
        ]
        cohort = [peer for peer in column if peer.key != record.key]
        if len(cohort) < cfg.minimum_cohort:
            cohort = [peer for peer in by_sheet[record.key[0]] if peer.key != record.key]

        exact_counter = Counter(peer.profile.exact_shape for peer in cohort)
        typed_counter = Counter(peer.profile.typed_shape for peer in cohort)
        dependency_counter = Counter(peer.profile.dependency_shape for peer in cohort)
        coarse_peers = [
            peer for peer in by_coarse_role[(record.key[0], record.col, record.profile.shape)]
            if peer.key != record.key
        ]
        constant_counter = Counter(peer.profile.exact_shape for peer in coarse_peers)
        local_support, local_consensus, local_dominant = _weighted_support(record, local_column, "exact_shape")
        row_support, _row_consensus, _row_dominant = _weighted_support(record, row_peers, "shape")
        block_support, _block_consensus, _block_dominant = _weighted_support(record, block, "shape")

        previous = max((peer for peer in column if peer.row < record.row), key=lambda x: x.row, default=None)
        following = min((peer for peer in column if peer.row > record.row), key=lambda x: x.row, default=None)
        singleton_break = 0.0
        boundary_discount = 1.0
        if previous and following:
            if previous.profile.exact_shape == following.profile.exact_shape != record.profile.exact_shape:
                singleton_break = 1.0
            elif record.profile.exact_shape in {previous.profile.exact_shape, following.profile.exact_shape}:
                boundary_discount = 0.45

        components = {
            "local_column_disagreement": ((1.0 - local_support) * boundary_discount, 0.95 if local_column else 0.0),
            "singleton_run_break": (singleton_break, 0.98),
            "hierarchical_role_rarity": (
                0.55 * _bayesian_rarity(record.profile.exact_shape, exact_counter, cfg.smoothing_alpha)
                + 0.45 * _bayesian_rarity(record.profile.typed_shape, typed_counter, cfg.smoothing_alpha),
                _entropy_reliability(exact_counter),
            ),
            "constant_signature_novelty": (
                _bayesian_rarity(record.profile.exact_shape, constant_counter, cfg.smoothing_alpha)
                if len(coarse_peers) >= 2 else 0.0,
                _entropy_reliability(constant_counter),
            ),
            "dependency_topology_rarity": (
                _bayesian_rarity(record.profile.dependency_shape, dependency_counter, cfg.smoothing_alpha),
                _entropy_reliability(dependency_counter),
            ),
            "row_disagreement": (1.0 - row_support, 0.30 if row_peers else 0.0),
            "block_disagreement": (1.0 - block_support, 0.25 if block else 0.0),
            "hard_integrity_violation": (
                1.0 if record.profile.has_ref_error or record.profile.has_direct_self_reference else 0.0,
                1.0,
            ),
        }
        components = {
            name: value for name, value in components.items()
            if name not in cfg.disabled_signals
        }
        raw_score, contributions = _noisy_or(components)
        repair, source, repair_consensus = _candidate_repair(record, local_column + cohort, local_dominant)
        preliminary.append({
            "id": record.cell_id,
            "sheet": record.key[0],
            "cell": record.key[1],
            "formula": record.formula,
            "shape": record.profile.shape,
            "typed_shape": record.profile.typed_shape,
            "exact_shape": record.profile.exact_shape,
            "dependency_shape": record.profile.dependency_shape,
            "raw_score": raw_score,
            "local_support": local_support,
            "local_consensus": local_consensus,
            "repair_formula": repair,
            "repair_source": source,
            "repair_consensus": repair_consensus,
            "components": contributions,
            "hard_violation": record.profile.has_ref_error or record.profile.has_direct_self_reference,
        })

    by_calibration: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in preliminary:
        by_calibration[(str(row["sheet"]), str(row["dependency_shape"]))].append(row)
    p_pairs: list[tuple[str, float]] = []
    for group in by_calibration.values():
        scores = [float(row["raw_score"]) for row in group]
        for row in group:
            score = float(row["raw_score"])
            p_value = (1 + sum(other >= score for other in scores)) / (len(scores) + 1)
            row["empirical_tail_p"] = p_value
            p_pairs.append((str(row["id"]), p_value))
    q_values = _bh_q_values(p_pairs)

    results: list[dict[str, object]] = []
    for row in preliminary:
        score = float(row["raw_score"])
        q_value = q_values[str(row["id"])]
        calibrated_score = max(score, 1.0 - q_value) if len(records) >= 20 else score
        can_repair = (
            row["repair_formula"] is not None
            and float(row["repair_consensus"]) >= cfg.repair_consensus
            and calibrated_score >= cfg.repair_score
        )
        status = (
            "repair_candidate" if can_repair
            else "review" if calibrated_score >= cfg.review_score or bool(row["hard_violation"])
            else "low_risk"
        )
        evidence = sorted(
            ((name, value) for name, value in dict(row["components"]).items() if value > 0.02),
            key=lambda item: (-item[1], item[0]),
        )[:4]
        results.append({
            "sheet": row["sheet"],
            "cell": row["cell"],
            "original_formula": row["formula"],
            "structural_score": calibrated_score,
            "raw_evidence_score": score,
            "empirical_tail_p": row["empirical_tail_p"],
            "bh_q_value": q_value,
            "local_role_support": row["local_support"],
            "status": status,
            "suggested_formula": row["repair_formula"] if can_repair else None,
            "suggestion_source": row["repair_source"] if can_repair else None,
            "repair_consensus": row["repair_consensus"] if can_repair else 0.0,
            "evidence": [{"signal": name, "contribution": value} for name, value in evidence],
            "automatic_edit_applied": False,
        })
    results.sort(key=lambda row: (-float(row["structural_score"]), str(row["sheet"]), str(row["cell"])))
    for rank, row in enumerate(results, 1):
        row["rank"] = rank
    status_counts = Counter(str(row["status"]) for row in results)
    return {
        "protocol": "structuralguard_multiscale_v1",
        "source_workbook": str(snapshot.path),
        "source_sha256": _sha256(snapshot.path),
        "formula_cells": len(records),
        "configuration": asdict(cfg),
        "method": {
            "neural_model_used": False,
            "formula_representation": "hierarchical relative-reference + typed/exact constants",
            "scopes": ["local column", "row", "spatial block", "column cohort", "dependency topology"],
            "fusion": "adaptive reliability-weighted noisy-or",
            "calibration": "dependency-cohort empirical upper tail with Benjamini-Hochberg q-values",
            "repair": "consensus peer translation with #REF/self-reference rejection",
        },
        "summary": {
            "status_counts": dict(status_counts),
            "review_rows": sum(count for status, count in status_counts.items() if status != "low_risk"),
            "repair_candidates": status_counts.get("repair_candidate", 0),
            "maximum_score": max((float(row["structural_score"]) for row in results), default=0.0),
            "median_score": median([float(row["structural_score"]) for row in results]) if results else 0.0,
        },
        "results": results,
    }


def analyze_workbook(
    path: str | Path,
    *,
    exclude_sheets: Sequence[str] = (),
    config: DetectorConfig | None = None,
) -> dict[str, object]:
    snapshot = WorkbookSnapshot.load(path, exclude_sheets=exclude_sheets)
    return analyze_snapshot(snapshot, config=config)


def save_json(report: Mapping[str, object], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
