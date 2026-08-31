#!/usr/bin/env python3
"""Score frozen public semantic margins after verifying the label-free run."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_fcrl_u1_corpus import write_json_atomic
from scripts.extract_semantic_public_scores import (
    PROTOCOL as SEMANTIC_RUN_PROTOCOL,
)
from scripts.extract_semantic_public_scores import _validate_score_shard
from scripts.score_model_discovery_signals import (
    _load_json,
    _validate_v4_run,
    load_revealed_events,
    read_profiles,
    safe_qct_file,
    sha256,
    shard_name,
    stable_hash,
    write_immutable,
)

PROTOCOL = "formulaguard_semantic_public_localization_score_v1"
SELECTIVE_PROTOCOL = "formulaguard_semantic_compatibility_selective_v1"
REVIEW_BUDGET = 5
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260831
EXPECTED_EVENTS = 220
EXPECTED_ERRORS = 190
EXPECTED_CONTROLS = 30

DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_V4 = ROOT / "results/model_discovery_v4_baseline"
DEFAULT_SEMANTIC = ROOT / "results/semantic_public_scores_v3"
DEFAULT_SELECTIVE_RECEIPT = (
    ROOT / "results/semantic_compatibility_selective_v1/receipt.json"
)
DEFAULT_OUTPUT = ROOT / "results/semantic_public_localization_v1"


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_clean_tracked_worktree() -> None:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("tracked worktree must be clean before public semantic scoring")


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _load_v4_cells(
    v4_dir: Path,
    profiles: Sequence[Mapping[str, str]],
) -> dict[str, tuple[str, ...]]:
    result = {}
    for profile in profiles:
        unit_id = str(profile["unit_id"])
        payload = _load_json(safe_qct_file(v4_dir / "shards" / shard_name(unit_id)))
        ranking = payload["ranking"]
        if not isinstance(ranking, list) or any(not isinstance(row, dict) for row in ranking):
            raise ValueError(f"V4 ranking is malformed for {unit_id}")
        result[unit_id] = tuple(str(row["cell"]) for row in ranking)
    return result


def _validate_semantic_run(
    semantic_dir: Path,
    v4_dir: Path,
    profiles_path: Path,
    profiles: Sequence[Mapping[str, str]],
    v4_cells: Mapping[str, Sequence[str]],
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    metadata_path = safe_qct_file(semantic_dir / "metadata.json")
    complete_path = safe_qct_file(semantic_dir / "complete.json")
    metadata = _load_json(metadata_path)
    complete = _load_json(complete_path)
    if (
        metadata.get("protocol") != SEMANTIC_RUN_PROTOCOL
        or complete.get("protocol") != SEMANTIC_RUN_PROTOCOL
        or complete.get("complete") is not True
        or complete.get("profiles_sha256") != sha256(profiles_path)
        or complete.get("profile_count") != len(profiles)
        or complete.get("workbooks") != len(profiles)
        or complete.get("v4_scope") != 100
        or complete.get("label_inputs") != []
        or complete.get("protected_data_inputs") != []
        or complete.get("source_model_gate_passed") is not False
        or complete.get("status") != "exploratory_label_free_feature_extraction"
        or complete.get("raw_formula_strings_persisted") is not False
        or complete.get("formula_roles_persisted") is not False
        or complete.get("v4_complete_sha256") != sha256(v4_dir / "complete.json")
    ):
        raise ValueError("semantic public completion receipt violates the score contract")
    if any(complete.get(key) != value for key, value in metadata.items()):
        raise ValueError("semantic metadata differs from the completion receipt")

    expected = {str(profile["unit_id"]): profile for profile in profiles}
    paths = sorted((semantic_dir / "shards").glob("*.json"), key=lambda path: path.name)
    if len(paths) != len(profiles):
        raise ValueError("semantic public shard inventory is incomplete")
    by_unit: dict[str, dict[str, object]] = {}
    totals = {
        "v4_scope_cells": 0,
        "scored_cells": 0,
        "skipped_invisible": 0,
        "skipped_without_alternatives": 0,
    }
    for path in paths:
        payload = _load_json(safe_qct_file(path))
        unit_id = str(payload.get("unit_id", ""))
        if (
            unit_id not in expected
            or unit_id in by_unit
            or path.name != shard_name(unit_id)
        ):
            raise ValueError(f"semantic public shard identity mismatch: {path.name}")
        scope = tuple(v4_cells[unit_id][:100])
        _validate_score_shard(payload, expected[unit_id], scope)
        by_unit[unit_id] = payload
        for key in totals:
            totals[key] += int(payload[key])
    if any(complete.get(key) != value for key, value in totals.items()):
        raise ValueError("semantic public aggregate counts differ from its shards")
    observed_hash = stable_hash([(path.name, sha256(path)) for path in paths])
    if complete.get("combined_shards_sha256") != observed_hash:
        raise ValueError("semantic public combined shard hash differs")
    return {
        "metadata_path": metadata_path,
        "complete_path": complete_path,
        "metadata": metadata,
        "complete": complete,
    }, by_unit


def _validate_selective_receipt(
    path: Path,
    semantic_complete: Mapping[str, object],
) -> tuple[dict[str, object], float]:
    receipt = _load_json(safe_qct_file(path))
    calibration = receipt.get("calibration")
    internal = receipt.get("internal_test")
    if (
        receipt.get("protocol") != SELECTIVE_PROTOCOL
        or receipt.get("complete") is not True
        or receipt.get("calibration_passed") is not True
        or receipt.get("internal_test_evaluated") is not True
        or not isinstance(calibration, dict)
        or not isinstance(internal, dict)
        or receipt.get("selected_model_sha256")
        != semantic_complete.get("selected_model_sha256")
        or receipt.get("target_receipt_sha256")
        != semantic_complete.get("target_receipt_sha256")
        or receipt.get("vocabulary_sha256")
        != semantic_complete.get("vocabulary_sha256")
        or receipt.get("training_receipt_sha256")
        != semantic_complete.get("training_receipt_sha256")
        or receipt.get("protected_data_inputs") != []
        or receipt.get("fault_label_inputs") != []
        or receipt.get("v4_rank_inputs") != []
        or receipt.get("threshold_selection")
        != "maximum_calibration_coverage_passing_all_fixed_gates"
    ):
        raise ValueError("selective semantic receipt violates the score contract")
    threshold = calibration.get("threshold")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(float(threshold))
        or float(threshold) <= 0.0
        or internal.get("threshold") != threshold
    ):
        raise ValueError("selective semantic decision threshold is invalid")
    return receipt, float(threshold)


def semantic_ranking(
    v4_cells: Sequence[str],
    scores: Sequence[Mapping[str, object]],
) -> list[str]:
    """Return a complete label-free ranking by signed decision confidence."""

    ordered = sorted(
        scores,
        key=lambda row: (
            -float(row["semantic_anomaly_confidence"]),
            int(row["v4_rank"]),
            str(row["cell"]),
        ),
    )
    ranked = [str(row["cell"]) for row in ordered]
    seen = set(ranked)
    ranked.extend(cell for cell in v4_cells if cell not in seen)
    if len(ranked) != len(v4_cells) or len(ranked) != len(set(ranked)):
        raise ValueError("semantic ranking changed the V4 formula inventory")
    return ranked


def action_cells(
    scores: Sequence[Mapping[str, object]],
    threshold: float,
    *,
    budget: int = REVIEW_BUDGET,
) -> list[str]:
    if not math.isfinite(threshold) or threshold <= 0.0 or budget < 1:
        raise ValueError("semantic action configuration is invalid")
    eligible = [
        row
        for row in scores
        if row["semantic_prefers_alternative"] is True
        and float(row["semantic_decision_margin"]) >= threshold
    ]
    eligible.sort(
        key=lambda row: (
            -float(row["semantic_decision_margin"]),
            int(row["v4_rank"]),
            str(row["cell"]),
        )
    )
    return [str(row["cell"]) for row in eligible[:budget]]


def _metric(ranking: Sequence[str], sources: Sequence[str]) -> dict[str, object]:
    positions = {cell: rank for rank, cell in enumerate(ranking, 1)}
    ranks = [positions[cell] for cell in sources if cell in positions]
    rank = min(ranks) if ranks else None
    return {
        "rank": rank,
        "source_found": int(rank is not None),
        "top1": int(rank is not None and rank <= 1),
        "top5": int(rank is not None and rank <= REVIEW_BUDGET),
        "mrr": 1.0 / rank if rank is not None else 0.0,
    }


def attach_events(
    events: Sequence[Mapping[str, object]],
    profiles: Sequence[Mapping[str, str]],
    v4_cells: Mapping[str, Sequence[str]],
    semantic_by_unit: Mapping[str, Mapping[str, object]],
    threshold: float,
) -> list[dict[str, object]]:
    by_hash = {str(profile["workbook_sha256"]): profile for profile in profiles}
    rows = []
    for event in events:
        path = safe_qct_file(Path(event["path"]))
        digest = sha256(path)
        if digest not in by_hash:
            raise ValueError(f"public label workbook is absent from profiles: {path}")
        profile = by_hash[digest]
        unit_id = str(profile["unit_id"])
        v4 = list(v4_cells[unit_id])
        payload = semantic_by_unit[unit_id]
        scores = payload["scores"]
        if not isinstance(scores, list):
            raise TypeError(f"semantic scores are malformed for {unit_id}")
        semantic = semantic_ranking(v4, scores)
        actions = action_cells(scores, threshold)
        source_cells = [str(cell) for cell in event["source_cells"]]
        v4_set = set(v4)
        source_formula_cells = [cell for cell in source_cells if cell in v4_set]
        metrics = {
            "v4": _metric(v4, source_formula_cells),
            "semantic_confidence": _metric(semantic, source_formula_cells),
        }
        positions = {cell: rank for rank, cell in enumerate(v4, 1)}
        score_cells = {str(row["cell"]) for row in scores}
        rows.append({
            "event_id": event["event_id"],
            "cohort": event["cohort"],
            "case_kind": event["case_kind"],
            "unit_id": unit_id,
            "workbook_sha256": digest,
            "structure_group": profile["structure_cluster_id"],
            "source_cells": source_cells,
            "source_formula_cells": source_formula_cells,
            "non_formula_source_cells": [
                cell for cell in source_cells if cell not in v4_set
            ],
            "source_in_v4_top100": int(
                any(positions.get(cell, math.inf) <= 100 for cell in source_formula_cells)
            ),
            "semantic_score_available_for_source": int(
                any(cell in score_cells for cell in source_formula_cells)
            ),
            "metrics": metrics,
            "action_cells": actions,
            "acted": int(bool(actions)),
            "action_hit": int(bool(set(actions) & set(source_formula_cells))),
            "label_file": event["label_file"],
            "label_row": event["label_row"],
        })
    return rows


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def metric_summary(
    rows: Sequence[Mapping[str, object]],
    method: str,
) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in errors:
        groups[str(row["structure_group"])].append(row)
    metrics: dict[str, object] = {
        "events": len(errors),
        "formula_source_events": sum(bool(row["source_formula_cells"]) for row in errors),
        "structure_groups": len(groups),
    }
    for key in ("source_found", "top1", "top5", "mrr"):
        event_values = [float(row["metrics"][method][key]) for row in errors]
        group_values = [
            statistics.fmean(float(row["metrics"][method][key]) for row in group_rows)
            for group_rows in groups.values()
        ]
        metrics[key] = _mean(event_values)
        metrics[f"structure_macro_{key}"] = _mean(group_values)
    observed_ranks = [
        float(row["metrics"][method]["rank"])
        for row in errors
        if row["metrics"][method]["rank"] is not None
    ]
    metrics["mean_observed_source_rank"] = _mean(observed_ranks)
    return metrics


def group_bootstrap_interval(
    group_deltas: Sequence[float],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    if len(group_deltas) < 2 or samples < 100:
        raise ValueError("structure-group bootstrap needs two groups and 100 samples")
    values = list(group_deltas)
    rng = random.Random(seed)
    estimates = [
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(samples)
    ]
    estimates.sort()
    return (
        estimates[int(0.025 * (samples - 1))],
        estimates[int(0.975 * (samples - 1))],
    )


def paired_summary(
    rows: Sequence[Mapping[str, object]],
    metric: str,
    *,
    method: str = "semantic_confidence",
    baseline: str = "v4",
) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in errors:
        groups[str(row["structure_group"])].append(row)
    group_deltas = [
        statistics.fmean(
            float(row["metrics"][method][metric])
            - float(row["metrics"][baseline][metric])
            for row in group_rows
        )
        for group_rows in groups.values()
    ]
    event_deltas = [
        float(row["metrics"][method][metric])
        - float(row["metrics"][baseline][metric])
        for row in errors
    ]
    interval = group_bootstrap_interval(group_deltas)
    return {
        "events": len(errors),
        "structure_groups": len(groups),
        "event_mean_difference": _mean(event_deltas),
        "structure_macro_difference": _mean(group_deltas),
        "structure_group_bootstrap_95ci": list(interval),
        "improved_events": sum(value > 0.0 for value in event_deltas),
        "equal_events": sum(value == 0.0 for value in event_deltas),
        "worse_events": sum(value < 0.0 for value in event_deltas),
        "better_groups": sum(value > 0.0 for value in group_deltas),
        "equal_groups": sum(value == 0.0 for value in group_deltas),
        "worse_groups": sum(value < 0.0 for value in group_deltas),
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
    }


def action_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    selected = list(rows)
    acted = sum(int(row["acted"]) for row in selected)
    hits = sum(int(row["action_hit"]) for row in selected)
    source_events = sum(bool(row["source_formula_cells"]) for row in selected)
    return {
        "events": len(selected),
        "acted_events": acted,
        "action_rate": acted / len(selected) if selected else None,
        "hit_events": hits,
        "acted_precision": hits / acted if acted else None,
        "formula_source_coverage": hits / source_events if source_events else None,
        "review_cells": sum(len(row["action_cells"]) for row in selected),
    }


def score(
    *,
    profiles_path: Path,
    v4_dir: Path,
    semantic_dir: Path,
    selective_receipt_path: Path,
    output: Path,
) -> Path:
    require_clean_tracked_worktree()
    profiles_path = profiles_path.resolve()
    v4_dir = v4_dir.resolve()
    semantic_dir = semantic_dir.resolve()
    selective_receipt_path = selective_receipt_path.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("public semantic score output already exists; scoring is one-shot")

    profiles = read_profiles(profiles_path)
    profiles_hash = sha256(profiles_path)
    v4_receipt = _validate_v4_run(v4_dir, profiles, profiles_hash)
    v4_cells = _load_v4_cells(v4_dir, profiles)
    semantic_receipt, semantic_by_unit = _validate_semantic_run(
        semantic_dir,
        v4_dir,
        profiles_path,
        profiles,
        v4_cells,
    )
    selective_receipt, threshold = _validate_selective_receipt(
        selective_receipt_path,
        semantic_receipt["complete"],
    )

    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "profiles_path": _relative(profiles_path),
        "profiles_sha256": profiles_hash,
        "v4_complete_sha256": sha256(v4_dir / "complete.json"),
        "semantic_metadata_sha256": sha256(semantic_dir / "metadata.json"),
        "semantic_complete_sha256": sha256(semantic_dir / "complete.json"),
        "semantic_combined_shards_sha256": semantic_receipt["complete"][
            "combined_shards_sha256"
        ],
        "selective_receipt_sha256": sha256(selective_receipt_path),
        "decision_threshold": threshold,
        "decision_threshold_source": (
            "frozen calibration top1_minus_runner_up margin; action additionally "
            "requires an alternative role to win"
        ),
        "review_budget": REVIEW_BUDGET,
        "ranking_score": "signed top1_minus_runner_up semantic decision confidence",
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "prediction_label_inputs": [],
        "protected_data_inputs": [],
        "source_model_gate_passed": False,
        "status": "exploratory_revealed_public_localization_score",
    }
    output.mkdir(parents=True)
    write_json_atomic(output / "metadata.json", metadata)

    # This is the only boundary crossing: prediction artifacts and their
    # fixed threshold have been validated before revealed public labels load.
    events, label_files = load_revealed_events()
    rows = attach_events(events, profiles, v4_cells, semantic_by_unit, threshold)
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    if (
        len(rows) != EXPECTED_EVENTS
        or len(errors) != EXPECTED_ERRORS
        or len(controls) != EXPECTED_CONTROLS
    ):
        raise ValueError("revealed public event inventory changed")

    event_path = output / "event_scores.jsonl"
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(rows, key=lambda item: str(item["event_id"]))
    ).encode("utf-8")
    write_immutable(event_path, event_bytes, description="semantic public event scores")

    cohorts = sorted({str(row["cohort"]) for row in rows})
    by_cohort = {}
    for cohort in cohorts:
        cohort_rows = [row for row in rows if row["cohort"] == cohort]
        cohort_errors = [row for row in cohort_rows if row["case_kind"] == "error"]
        cohort_controls = [row for row in cohort_rows if row["case_kind"] == "control"]
        by_cohort[cohort] = {
            "v4": metric_summary(cohort_rows, "v4") if cohort_errors else None,
            "semantic_confidence": (
                metric_summary(cohort_rows, "semantic_confidence")
                if cohort_errors
                else None
            ),
            "paired_top5": paired_summary(cohort_rows, "top5") if cohort_errors else None,
            "paired_mrr": paired_summary(cohort_rows, "mrr") if cohort_errors else None,
            "error_action": action_summary(cohort_errors),
            "control_action": action_summary(cohort_controls),
        }

    v4_top5_misses = [row for row in errors if not row["metrics"]["v4"]["top5"]]
    top100_headroom = [row for row in v4_top5_misses if row["source_in_v4_top100"]]
    semantic_losses = [
        row
        for row in errors
        if row["metrics"]["v4"]["top5"]
        and not row["metrics"]["semantic_confidence"]["top5"]
    ]
    receipt = {
        **metadata,
        "complete": True,
        "prediction_receipts": {
            "semantic": {
                "path": _relative(semantic_dir),
                "protocol": semantic_receipt["complete"]["protocol"],
                "git_commit": semantic_receipt["complete"]["git_commit"],
                "combined_shards_sha256": semantic_receipt["complete"][
                    "combined_shards_sha256"
                ],
            },
            "v4": {
                "path": _relative(v4_dir),
                "combined_shards_sha256": v4_receipt["complete"][
                    "combined_shards_sha256"
                ],
            },
        },
        "threshold_receipt": {
            "path": _relative(selective_receipt_path),
            "selective_semantic_passed": selective_receipt[
                "selective_semantic_passed"
            ],
            "calibration_passed": selective_receipt["calibration_passed"],
            "internal_test_gates": selective_receipt["internal_test_gates"],
        },
        "label_boundary": {
            "prediction_label_inputs": [],
            "label_files_read_after_prediction_validation": [
                {"path": path, "sha256": sha256(ROOT / path)} for path in label_files
            ],
            "protected_data_inputs": [],
        },
        "events": {
            "total": len(rows),
            "errors": len(errors),
            "controls": len(controls),
            "formula_source_errors": sum(bool(row["source_formula_cells"]) for row in errors),
            "v4_top100_source_errors": sum(row["source_in_v4_top100"] for row in errors),
            "semantic_scored_source_errors": sum(
                row["semantic_score_available_for_source"] for row in errors
            ),
        },
        "overall": {
            "v4": metric_summary(rows, "v4"),
            "semantic_confidence": metric_summary(rows, "semantic_confidence"),
            "paired_top5": paired_summary(rows, "top5"),
            "paired_mrr": paired_summary(rows, "mrr"),
            "error_action": action_summary(errors),
            "control_action": action_summary(controls),
        },
        "by_cohort": by_cohort,
        "v4_top5_headroom": {
            "v4_top5_miss_events": len(v4_top5_misses),
            "source_in_v4_top100_events": len(top100_headroom),
            "semantic_top5_rescues": sum(
                row["metrics"]["semantic_confidence"]["top5"]
                for row in top100_headroom
            ),
            "semantic_top5_losses": len(semantic_losses),
        },
        "model_eligibility": {
            "source_semantic_gate_passed": False,
            "semantic_only_main_model_eligible": False,
            "interpretation": (
                "exploratory revealed-development evidence only; this score cannot "
                "restore the failed semantic gate or establish an independent result"
            ),
        },
        "event_scores_sha256": sha256(event_path),
        "raw_formula_strings_persisted": False,
    }
    receipt["receipt_sha256"] = stable_hash(receipt)
    receipt_path = output / "receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--semantic", type=Path, default=DEFAULT_SEMANTIC)
    parser.add_argument(
        "--selective-receipt",
        type=Path,
        default=DEFAULT_SELECTIVE_RECEIPT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        receipt = score(
            profiles_path=args.profiles,
            v4_dir=args.v4,
            semantic_dir=args.semantic,
            selective_receipt_path=args.selective_receipt,
            output=args.output,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(f"semantic public localization scoring refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
