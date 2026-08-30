"""Run the preregistered V4-RRC grouped cross-fit development gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_rrc import (
    MODEL_FEATURES,
    RidgeModel,
    candidate_feature_map,
    fit_ridge,
    guarded_candidate,
    peer_candidates,
    rerank,
    residual_utility,
    structure_fold,
)


PROTOCOL = "formulaguard_v4_residual_controller_crossfit_v1"
DEFAULT_EVENTS = ROOT / "results/model_discovery_gate2_final_v3/event_scores.jsonl"
DEFAULT_SIGNALS = ROOT / "results/model_discovery_signal_audit_observed"
DEFAULT_V4 = ROOT / "results/model_discovery_v4_baseline"
DEFAULT_PREREGISTRATION = ROOT / "research/V5_V4_RESIDUAL_CONTROLLER_PREREGISTRATION.json"
DEFAULT_OUTPUT = ROOT / "results/v4_rrc_d0"
MAIN_N2_COHORTS = (
    "public:integer_corpus",
    "public:modified_euses",
    "historical_100",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def reject_protected(path: Path) -> None:
    if "FormulaGuard_240_120" in path.resolve().parts:
        raise ValueError(f"protected path is forbidden for V4-RRC development: {path}")


def load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_event_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    event_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            required = {
                "event_id", "unit_id", "case_kind", "cohort", "structure_group",
                "source_formula_cells", "v4_rank", "review_cells", "selector_metrics",
            }
            missing = sorted(required - set(row))
            if missing:
                raise ValueError(f"event line {line_number} missing fields: {missing}")
            event_id = str(row["event_id"])
            if event_id in event_ids:
                raise ValueError(f"duplicate event_id: {event_id}")
            event_ids.add(event_id)
            rows.append(row)
    if not rows:
        raise ValueError("V4-RRC event table is empty")
    return rows


def load_shards(directory: Path, *, kind: str) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    complete = load_json(directory / "complete.json")
    if complete.get("complete") is not True or complete.get("label_inputs_to_prediction") != []:
        raise ValueError(f"incomplete or label-contaminated {kind} run")
    paths = sorted((directory / "shards").glob("*.json"))
    if len(paths) != int(complete["shard_count"]):
        raise ValueError(f"{kind} shard count differs from completion receipt")
    result: dict[str, dict[str, object]] = {}
    for path in paths:
        payload = load_json(path)
        unit_id = str(payload["unit_id"])
        if unit_id in result:
            raise ValueError(f"duplicate {kind} unit: {unit_id}")
        result[unit_id] = payload
    return result, complete


@dataclass(frozen=True)
class Unit:
    unit_id: str
    structure_group: str
    fold: int
    events: tuple[dict[str, object], ...]
    audit: dict[str, object]
    v4_rows: tuple[dict[str, object], ...]
    v4_cells: tuple[str, ...]
    candidates: tuple[str, ...]
    features: Mapping[str, Mapping[str, float]]


def build_units(
    event_rows: Sequence[dict[str, object]],
    signal_shards: Mapping[str, dict[str, object]],
    v4_shards: Mapping[str, dict[str, object]],
) -> list[Unit]:
    by_unit: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in event_rows:
        by_unit[str(row["unit_id"])].append(row)
    if set(by_unit) != set(signal_shards) or set(by_unit) != set(v4_shards):
        raise ValueError("event, signal, and V4 unit inventories differ")
    units: list[Unit] = []
    for unit_id in sorted(by_unit):
        events = sorted(by_unit[unit_id], key=lambda row: str(row["event_id"]))
        groups = {str(row["structure_group"]) for row in events}
        if len(groups) != 1:
            raise ValueError(f"unit crosses structure groups: {unit_id}")
        structure_group = next(iter(groups))
        signal = signal_shards[unit_id]
        v4 = v4_shards[unit_id]
        if signal.get("workbook_sha256") != v4.get("workbook_sha256"):
            raise ValueError(f"signal/V4 workbook mismatch: {unit_id}")
        audit = signal.get("audit")
        v4_rows = v4.get("ranking")
        if not isinstance(audit, dict) or not isinstance(v4_rows, list):
            raise ValueError(f"incomplete signal/V4 payload: {unit_id}")
        if audit.get("label_inputs") != [] or v4.get("label_inputs") != []:
            raise ValueError(f"prediction shard consumed labels: {unit_id}")
        v4_cells = tuple(str(row["cell"]) for row in v4_rows)
        if any(list(row["v4_rank"]) != list(v4_cells) for row in events):
            raise ValueError(f"event V4 ranking differs from frozen shard: {unit_id}")
        audit_review = list(audit["review_cells"]["peer"])
        if any(list(row["review_cells"]["peer"]) != audit_review for row in events):
            raise ValueError(f"event peer review cells differ from frozen shard: {unit_id}")
        candidates = tuple(peer_candidates(audit, v4_rows))
        features = {
            cell: candidate_feature_map(cell, audit, v4_rows)
            for cell in candidates
        }
        units.append(Unit(
            unit_id=unit_id,
            structure_group=structure_group,
            fold=structure_fold(structure_group),
            events=tuple(events),
            audit=audit,
            v4_rows=tuple(v4_rows),
            v4_cells=v4_cells,
            candidates=candidates,
            features=features,
        ))
    return units


def allowed_candidates(unit: Unit, revision: int) -> list[str]:
    return [
        cell for cell in unit.candidates
        if guarded_candidate(cell, unit.audit, revision=revision)
    ]


def training_examples(
    units: Sequence[Unit], revision: int,
) -> tuple[list[Mapping[str, float]], list[float], list[float]]:
    group_events: dict[str, int] = defaultdict(int)
    for unit in units:
        group_events[unit.structure_group] += len(unit.events)
    features: list[Mapping[str, float]] = []
    targets: list[float] = []
    weights: list[float] = []
    for unit in units:
        candidates = allowed_candidates(unit, revision)
        if not candidates:
            continue
        event_weight = 1.0 / group_events[unit.structure_group]
        row_weight = event_weight / len(candidates)
        for event in unit.events:
            for candidate in candidates:
                features.append(unit.features[candidate])
                targets.append(residual_utility(
                    str(event["case_kind"]),
                    [str(cell) for cell in event["source_formula_cells"]],
                    unit.v4_cells,
                    candidate,
                ))
                weights.append(row_weight)
    if not features:
        raise ValueError("no V4-RRC training examples")
    return features, targets, weights


def predict_units(
    model: RidgeModel,
    units: Sequence[Unit],
    revision: int,
) -> dict[str, dict[str, object]]:
    predictions: dict[str, dict[str, object]] = {}
    for unit in units:
        candidates = allowed_candidates(unit, revision)
        if not candidates:
            predictions[unit.unit_id] = {"candidate": None, "score": None}
            continue
        candidate_order = {cell: index for index, cell in enumerate(unit.candidates)}
        scored = [
            (model.predict(unit.features[cell]), candidate_order[cell], cell)
            for cell in candidates
        ]
        score, _, cell = min(scored, key=lambda row: (-row[0], row[1], row[2]))
        predictions[unit.unit_id] = {"candidate": cell, "score": score}
    return predictions


def source_rank(ranking: Sequence[str], sources: Sequence[str]) -> int | None:
    source_set = set(sources)
    for rank, cell in enumerate(ranking, start=1):
        if cell in source_set:
            return rank
    return None


def event_prediction_rows(
    units: Sequence[Unit],
    predictions: Mapping[str, Mapping[str, object]],
    threshold: float,
    *,
    outer_fold: int | None,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for unit in units:
        prediction = predictions[unit.unit_id]
        candidate = prediction["candidate"]
        score = prediction["score"]
        acted = candidate is not None and score is not None and float(score) > threshold
        action = str(candidate) if acted else None
        controller_rank = rerank(unit.v4_cells, action)
        for event in unit.events:
            sources = [str(cell) for cell in event["source_formula_cells"]]
            v4_rank = source_rank(unit.v4_cells, sources)
            new_rank = source_rank(controller_rank, sources)
            v4_hit = int(v4_rank is not None and v4_rank <= 5)
            new_hit = int(new_rank is not None and new_rank <= 5)
            output.append({
                "event_id": str(event["event_id"]),
                "unit_id": unit.unit_id,
                "structure_group": unit.structure_group,
                "cohort": str(event["cohort"]),
                "case_kind": str(event["case_kind"]),
                "outer_fold": outer_fold,
                "candidate": candidate,
                "candidate_score": score,
                "threshold": None if math.isinf(threshold) else threshold,
                "acted": int(acted),
                "action_cell": action,
                "v4_source_rank": v4_rank,
                "controller_source_rank": new_rank,
                "v4_top5": v4_hit,
                "controller_top5": new_hit,
                "residual_delta": new_hit - v4_hit,
                "controller_ranking": controller_rank,
            })
    return sorted(output, key=lambda row: str(row["event_id"]))


def _group_macro(rows: Sequence[Mapping[str, object]], field: str) -> float | None:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["case_kind"] != "error":
            continue
        value = row[field]
        if value is None:
            continue
        groups[str(row["structure_group"])].append(float(value))
    if not groups:
        return None
    return statistics.fmean(statistics.fmean(values) for values in groups.values())


def _mrr_rows(rows: Sequence[Mapping[str, object]], rank_field: str) -> list[dict[str, object]]:
    result = []
    for row in rows:
        clone = dict(row)
        rank = row[rank_field]
        clone["_mrr"] = 1.0 / int(rank) if rank else 0.0
        result.append(clone)
    return result


def summarize_predictions(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    v4_top5 = _group_macro(errors, "v4_top5")
    controller_top5 = _group_macro(errors, "controller_top5")
    v4_mrr = _group_macro(_mrr_rows(errors, "v4_source_rank"), "_mrr")
    controller_mrr = _group_macro(_mrr_rows(errors, "controller_source_rank"), "_mrr")
    gains = sum(int(row["residual_delta"] == 1) for row in errors)
    losses = sum(int(row["residual_delta"] == -1) for row in errors)
    acted_error_events = sum(int(row["acted"]) for row in errors)
    v4_misses = sum(int(row["v4_top5"] == 0) for row in errors)
    v4_hits = sum(int(row["v4_top5"] == 1) for row in errors)
    control_units = {str(row["unit_id"]) for row in controls}
    acted_control_units = {str(row["unit_id"]) for row in controls if row["acted"]}
    action_units = {str(row["unit_id"]) for row in rows if row["acted"]}
    by_cohort: dict[str, object] = {}
    for cohort in sorted({str(row["cohort"]) for row in errors}):
        cohort_rows = [row for row in errors if row["cohort"] == cohort]
        baseline = _group_macro(cohort_rows, "v4_top5")
        current = _group_macro(cohort_rows, "controller_top5")
        baseline_mrr = _group_macro(_mrr_rows(cohort_rows, "v4_source_rank"), "_mrr")
        current_mrr = _group_macro(_mrr_rows(cohort_rows, "controller_source_rank"), "_mrr")
        by_cohort[cohort] = {
            "events": len(cohort_rows),
            "groups": len({str(row["structure_group"]) for row in cohort_rows}),
            "v4_top5": baseline,
            "controller_top5": current,
            "top5_difference": current - baseline,
            "v4_mrr": baseline_mrr,
            "controller_mrr": current_mrr,
            "mrr_difference": current_mrr - baseline_mrr,
        }
    return {
        "events": len(rows),
        "errors": len(errors),
        "controls": len(controls),
        "error_groups": len({str(row["structure_group"]) for row in errors}),
        "v4_top5": v4_top5,
        "controller_top5": controller_top5,
        "top5_difference": controller_top5 - v4_top5,
        "v4_mrr": v4_mrr,
        "controller_mrr": controller_mrr,
        "mrr_difference": controller_mrr - v4_mrr,
        "residual_event_gains": gains,
        "residual_event_losses": losses,
        "acted_error_events": acted_error_events,
        "positive_residual_action_precision": gains / acted_error_events if acted_error_events else 0.0,
        "v4_miss_events": v4_misses,
        "v4_miss_recovery_rate": gains / v4_misses if v4_misses else 0.0,
        "v4_hit_events": v4_hits,
        "v4_hit_loss_rate": losses / v4_hits if v4_hits else 0.0,
        "control_workbooks": len(control_units),
        "acted_control_workbooks": len(acted_control_units),
        "control_workbook_action_rate": (
            len(acted_control_units) / len(control_units) if control_units else None
        ),
        "action_units": len(action_units),
        "by_cohort": by_cohort,
    }


def choose_threshold(
    units: Sequence[Unit],
    predictions: Mapping[str, Mapping[str, object]],
) -> tuple[float, dict[str, object]]:
    scores = sorted({
        float(row["score"])
        for row in predictions.values()
        if row["score"] is not None
    }, reverse=True)
    candidates: list[tuple[tuple[float, int, int, float], float, dict[str, object]]] = []
    for score in scores:
        threshold = math.nextafter(score, -math.inf)
        rows = event_prediction_rows(units, predictions, threshold, outer_fold=None)
        summary = summarize_predictions(rows)
        control_rate = summary["control_workbook_action_rate"]
        if (
            summary["residual_event_gains"] >= 3
            and summary["positive_residual_action_precision"] >= 0.75
            and control_rate is not None
            and control_rate <= 0.15
            and summary["v4_hit_loss_rate"] <= 0.02
        ):
            key = (
                float(summary["top5_difference"]),
                int(summary["residual_event_gains"]),
                -int(summary["action_units"]),
                threshold,
            )
            candidates.append((key, threshold, summary))
    if not candidates:
        return math.inf, {
            "finite_threshold": False,
            "reason": "no_threshold_met_preregistered_calibration_constraints",
            "candidate_thresholds": len(scores),
            "control_workbooks": len({
                unit.unit_id for unit in units
                if any(event["case_kind"] == "control" for event in unit.events)
            }),
        }
    _, threshold, summary = max(candidates, key=lambda row: row[0])
    return threshold, {
        "finite_threshold": True,
        "threshold": threshold,
        "candidate_thresholds": len(scores),
        "summary": summary,
    }


def rrf_ranking(unit: Unit, k: int = 60) -> list[str]:
    peer = [str(cell) for cell in unit.audit["rankings"]["peer"]]
    v4_rank = {cell: rank for rank, cell in enumerate(unit.v4_cells, start=1)}
    peer_rank = {cell: rank for rank, cell in enumerate(peer, start=1)}
    cells = list(unit.v4_cells)
    return sorted(cells, key=lambda cell: (
        -(1.0 / (k + v4_rank[cell]) + 1.0 / (k + peer_rank[cell])),
        v4_rank[cell],
        cell,
    ))


def baseline_summary(units: Sequence[Unit]) -> dict[str, object]:
    methods: dict[str, list[dict[str, object]]] = {
        "forced_peer_top1_fifth_slot": [],
        "rrf_v4_peer_k60": [],
        "gate2_fixed_selector": [],
    }
    for unit in units:
        review = [str(cell) for cell in unit.audit["review_cells"]["peer"][:1]]
        forced = rerank(unit.v4_cells, review[0] if review and review[0] not in unit.v4_cells[:5] else None)
        rrf = rrf_ranking(unit)
        for event in unit.events:
            sources = [str(cell) for cell in event["source_formula_cells"]]
            v4_rank = source_rank(unit.v4_cells, sources)
            for method, ranking in (
                ("forced_peer_top1_fifth_slot", forced),
                ("rrf_v4_peer_k60", rrf),
            ):
                rank = source_rank(ranking, sources)
                methods[method].append({
                    "case_kind": event["case_kind"],
                    "structure_group": unit.structure_group,
                    "v4_top5": int(v4_rank is not None and v4_rank <= 5),
                    "controller_top5": int(rank is not None and rank <= 5),
                    "v4_source_rank": v4_rank,
                    "controller_source_rank": rank,
                    "residual_delta": int(rank is not None and rank <= 5) - int(v4_rank is not None and v4_rank <= 5),
                    "acted": int(ranking != list(unit.v4_cells)),
                    "unit_id": unit.unit_id,
                    "cohort": event["cohort"],
                })
            selector = event["selector_metrics"]
            methods["gate2_fixed_selector"].append({
                "case_kind": event["case_kind"],
                "structure_group": unit.structure_group,
                "v4_top5": int(v4_rank is not None and v4_rank <= 5),
                "controller_top5": int(selector["top5"]),
                "v4_source_rank": v4_rank,
                "controller_source_rank": selector["rank"],
                "residual_delta": int(selector["top5"]) - int(v4_rank is not None and v4_rank <= 5),
                "acted": int(event["selector_action"]["acted"]),
                "unit_id": unit.unit_id,
                "cohort": event["cohort"],
            })
    output = {method: summarize_predictions(rows) for method, rows in methods.items()}
    output.update({
        "v4_r1": {"status": "primary_metrics_embedded_in_each_comparison"},
        "v4_2_review_b": {"status": "deferred_unless_development_gate_passes", "native_budget": "five_plus_optional_sixth"},
        "v5_psl_static_anchor": {"status": "deferred_unless_development_gate_passes"},
        "excelint_native": {"status": "deferred_unless_development_gate_passes", "metric_contract": "region_hit_and_review_cost_only"},
        "oracle_headroom": {
            "status": "reported_in_results/v4_residual_headroom_v0/receipt.json",
            "deployable": False,
        },
    })
    return output


def decision(summary: Mapping[str, object], folds: Sequence[Mapping[str, object]]) -> dict[str, object]:
    cohorts = summary["by_cohort"]
    enron = cohorts["enron"]
    n2_differences = [float(cohorts[name]["top5_difference"]) for name in MAIN_N2_COHORTS]
    finite_thresholds = sum(bool(fold["calibration"]["finite_threshold"]) for fold in folds)
    nonnegative_folds = sum(float(fold["test_summary"]["top5_difference"]) >= 0.0 for fold in folds)
    control_rate = summary["control_workbook_action_rate"]
    gates = {
        "overall_top5_gain_at_least_5pp": float(summary["top5_difference"]) >= 0.05,
        "enron_top5_gain_at_least_5pp": float(enron["top5_difference"]) >= 0.05,
        "enron_mrr_not_below_v4": float(enron["mrr_difference"]) >= 0.0,
        "all_n2_cohort_regressions_at_most_2pp": min(n2_differences) >= -0.02,
        "positive_residual_action_precision_at_least_75pct": float(summary["positive_residual_action_precision"]) >= 0.75,
        "v4_miss_recovery_rate_at_least_15pct": float(summary["v4_miss_recovery_rate"]) >= 0.15,
        "v4_hit_loss_rate_at_most_2pct": float(summary["v4_hit_loss_rate"]) <= 0.02,
        "control_workbook_action_rate_at_most_15pct": control_rate is not None and float(control_rate) <= 0.15,
        "at_least_four_nonnegative_outer_folds": nonnegative_folds >= 4,
        "at_least_three_finite_calibration_thresholds": finite_thresholds >= 3,
        "two_process_hash_match": False,
    }
    non_repro = {key: value for key, value in gates.items() if key != "two_process_hash_match"}
    safety_keys = {
        "positive_residual_action_precision_at_least_75pct",
        "v4_hit_loss_rate_at_most_2pct",
        "control_workbook_action_rate_at_most_15pct",
    }
    failed_without_repro = {key for key, value in non_repro.items() if not value}
    revision_allowed = (
        bool(gates["overall_top5_gain_at_least_5pp"])
        and float(enron["top5_difference"]) >= 0.0
        and bool(failed_without_repro)
        and failed_without_repro <= safety_keys
    )
    return {
        "gates": gates,
        "finite_calibration_thresholds": finite_thresholds,
        "nonnegative_outer_folds": nonnegative_folds,
        "passed": all(gates.values()),
        "single_revision_allowed": revision_allowed,
        "failed_gates_without_reproducibility": sorted(failed_without_repro),
    }


def fit_fold(train_units: Sequence[Unit], revision: int) -> RidgeModel:
    features, targets, weights = training_examples(train_units, revision)
    return fit_ridge(features, targets, weights, ridge_lambda=1.0)


def final_candidate(units: Sequence[Unit], revision: int) -> dict[str, object]:
    train = [unit for unit in units if unit.fold in {0, 1, 2, 3}]
    calibration = [unit for unit in units if unit.fold == 4]
    model = fit_fold(train, revision)
    predictions = predict_units(model, calibration, revision)
    threshold, calibration_result = choose_threshold(calibration, predictions)
    if math.isinf(threshold):
        return {"eligible": False, "reason": "final_fold4_calibration_failed", "calibration": calibration_result}
    all_predictions = predict_units(model, units, revision)
    unit_predictions = []
    for unit in units:
        prediction = all_predictions[unit.unit_id]
        acted = prediction["score"] is not None and float(prediction["score"]) > threshold
        action = str(prediction["candidate"]) if acted else None
        unit_predictions.append({
            "unit_id": unit.unit_id,
            "candidate": prediction["candidate"],
            "candidate_score": prediction["score"],
            "threshold": threshold,
            "acted": int(acted),
            "action_cell": action,
            "ranking": rerank(unit.v4_cells, action),
        })
    return {
        "eligible": True,
        "train_folds": [0, 1, 2, 3],
        "calibration_fold": 4,
        "model": model.to_dict(),
        "threshold": threshold,
        "calibration": calibration_result,
        "public_unit_predictions": unit_predictions,
    }


def run_crossfit(
    *,
    events_path: Path,
    signal_dir: Path,
    v4_dir: Path,
    preregistration_path: Path,
    revision: int,
) -> dict[str, object]:
    for path in (events_path, signal_dir, v4_dir, preregistration_path):
        reject_protected(path)
    preregistration = load_json(preregistration_path)
    if preregistration.get("protocol") != "formulaguard_v4_residual_controller_v1":
        raise ValueError("unexpected V4-RRC preregistration")
    event_rows = load_event_rows(events_path)
    signals, signal_complete = load_shards(signal_dir, kind="signal")
    v4, v4_complete = load_shards(v4_dir, kind="V4")
    units = build_units(event_rows, signals, v4)
    fold_artifacts: list[dict[str, object]] = []
    combined_predictions: list[dict[str, object]] = []
    for outer_fold in range(5):
        calibration_fold = (outer_fold + 1) % 5
        train = [unit for unit in units if unit.fold not in {outer_fold, calibration_fold}]
        calibration = [unit for unit in units if unit.fold == calibration_fold]
        test = [unit for unit in units if unit.fold == outer_fold]
        model = fit_fold(train, revision)
        calibration_predictions = predict_units(model, calibration, revision)
        threshold, calibration_result = choose_threshold(calibration, calibration_predictions)
        test_predictions = predict_units(model, test, revision)
        test_rows = event_prediction_rows(test, test_predictions, threshold, outer_fold=outer_fold)
        test_summary = summarize_predictions(test_rows)
        combined_predictions.extend(test_rows)
        fold_artifacts.append({
            "outer_fold": outer_fold,
            "calibration_fold": calibration_fold,
            "training_folds": sorted({0, 1, 2, 3, 4} - {outer_fold, calibration_fold}),
            "train_units": len(train),
            "calibration_units": len(calibration),
            "test_units": len(test),
            "model": model.to_dict(),
            "calibration": calibration_result,
            "test_summary": test_summary,
        })
    combined_predictions.sort(key=lambda row: str(row["event_id"]))
    summary = summarize_predictions(combined_predictions)
    result_decision = decision(summary, fold_artifacts)
    source_hashes = {
        "events": sha256(events_path),
        "signal_metadata": sha256(signal_dir / "metadata.json"),
        "signal_complete": sha256(signal_dir / "complete.json"),
        "v4_metadata": sha256(v4_dir / "metadata.json"),
        "v4_complete": sha256(v4_dir / "complete.json"),
        "preregistration": sha256(preregistration_path),
        "core": sha256(ROOT / "formulaguard/v4_rrc.py"),
        "runner": sha256(Path(__file__)),
    }
    deterministic_projection = {
        "revision": revision,
        "source_hashes": source_hashes,
        "fold_artifacts": fold_artifacts,
        "predictions": combined_predictions,
        "summary": summary,
        "baselines": baseline_summary(units),
        "decision_without_reproducibility": result_decision,
    }
    projection_hash = stable_hash(deterministic_projection)
    result: dict[str, object] = {
        "protocol": PROTOCOL,
        "revision": revision,
        "git_commit": git_commit(),
        "inputs": {
            "events": {"path": relative(events_path), "sha256": source_hashes["events"]},
            "signals": {"path": relative(signal_dir), "combined_shards_sha256": signal_complete["combined_shards_sha256"]},
            "v4": {"path": relative(v4_dir), "combined_shards_sha256": v4_complete["combined_shards_sha256"]},
            "preregistration": {"path": relative(preregistration_path), "sha256": source_hashes["preregistration"]},
        },
        "counts": {
            "units": len(units),
            "events": len(event_rows),
            "errors": sum(row["case_kind"] == "error" for row in event_rows),
            "controls": sum(row["case_kind"] == "control" for row in event_rows),
            "candidate_feature_maps": sum(len(unit.candidates) for unit in units),
            "empty_candidate_units": sum(not unit.candidates for unit in units),
        },
        "feature_contract": {
            "model_features": list(MODEL_FEATURES),
            "feature_count": len(MODEL_FEATURES),
            "forbidden_identity_features": [],
        },
        "source_hashes": source_hashes,
        "fold_artifacts": fold_artifacts,
        "event_predictions": combined_predictions,
        "summary": summary,
        "baselines": deterministic_projection["baselines"],
        "decision": result_decision,
        "deterministic_projection_sha256": projection_hash,
        "protected_data_inputs": [],
    }
    if all(
        value for key, value in result_decision["gates"].items()
        if key != "two_process_hash_match"
    ):
        result["final_candidate"] = final_candidate(units, revision)
    else:
        result["final_candidate"] = {"eligible": False, "reason": "crossfit_gate_failed"}
    return result


def write_immutable(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"completed V4-RRC output differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def worker(args: argparse.Namespace) -> int:
    payload = run_crossfit(
        events_path=args.events.resolve(),
        signal_dir=args.signals.resolve(),
        v4_dir=args.v4.resolve(),
        preregistration_path=args.preregistration.resolve(),
        revision=args.revision,
    )
    Path(args.worker_output).write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    return 0


def parent(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="v4_rrc_repro_") as directory:
        worker_outputs = [Path(directory) / f"run_{index}.json" for index in range(2)]
        for output in worker_outputs:
            command = [
                sys.executable, str(Path(__file__).resolve()),
                "--events", str(args.events),
                "--signals", str(args.signals),
                "--v4", str(args.v4),
                "--preregistration", str(args.preregistration),
                "--revision", str(args.revision),
                "--worker-output", str(output),
            ]
            subprocess.run(command, cwd=ROOT, check=True)
        first, second = (load_json(path) for path in worker_outputs)
    reproducible = (
        first["deterministic_projection_sha256"]
        == second["deterministic_projection_sha256"]
    )
    first["decision"]["gates"]["two_process_hash_match"] = reproducible
    candidate = first["final_candidate"]
    first["decision"]["gates"]["final_fold4_calibration_passed"] = bool(
        candidate.get("eligible")
    )
    first["decision"]["passed"] = all(first["decision"]["gates"].values())
    if not first["decision"]["passed"]:
        candidate = {"eligible": False, "reason": "crossfit_gate_failed"}

    output_dir = args.output_dir.resolve()
    fold_bytes = (json.dumps(first["fold_artifacts"], ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    prediction_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        for row in first["event_predictions"]
    ).encode("utf-8")
    write_immutable(output_dir / "fold_models.json", fold_bytes)
    write_immutable(output_dir / "event_predictions.jsonl", prediction_bytes)
    first.pop("final_candidate")
    candidate_path = None
    if first["decision"]["passed"] and candidate.get("eligible"):
        candidate_bytes = (json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        candidate_path = output_dir / "candidate.json"
        write_immutable(candidate_path, candidate_bytes)
    first.pop("fold_artifacts")
    first.pop("event_predictions")
    first["artifacts"] = {
        "fold_models": {"path": relative(output_dir / "fold_models.json"), "sha256": hashlib.sha256(fold_bytes).hexdigest()},
        "event_predictions": {"path": relative(output_dir / "event_predictions.jsonl"), "sha256": hashlib.sha256(prediction_bytes).hexdigest()},
        "candidate": (
            {"path": relative(candidate_path), "sha256": sha256(candidate_path)}
            if candidate_path else None
        ),
    }
    first["complete"] = True
    first["receipt_sha256"] = stable_hash(first)
    receipt_bytes = (json.dumps(first, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_immutable(output_dir / "receipt.json", receipt_bytes)
    print(output_dir / "receipt.json")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--revision", type=int, choices=(0, 1), default=0)
    parser.add_argument("--worker-output", type=Path)
    args = parser.parse_args(argv)
    return worker(args) if args.worker_output else parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
