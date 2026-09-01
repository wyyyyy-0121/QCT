"""Score the frozen output-coupled Peer repair responsibility rule."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_rrc import rerank, structure_fold  # noqa: E402
from scripts.extract_peer_repair_closure import (  # noqa: E402
    DEFAULT_PROFILES,
    DEFAULT_SIGNALS,
    DEFAULT_V4,
    _combined_shards,
    _load_json,
    _load_sources,
    _reject_protected,
)
from scripts.extract_peer_repair_responsibility import (  # noqa: E402
    DEFAULT_OUTPUT as DEFAULT_RESPONSIBILITY,
    RUN_PROTOCOL as RESPONSIBILITY_RUN_PROTOCOL,
    _validate_record,
)
from scripts.run_model_discovery_signals import read_profiles, sha256, shard_name  # noqa: E402
from scripts.run_v4_residual_controller import (  # noqa: E402
    DEFAULT_EVENTS,
    load_event_rows,
    source_rank,
    stable_hash,
)
from scripts.run_v4_rrc_required_baselines import write_immutable  # noqa: E402
from scripts.score_peer_repair_closure import (  # noqa: E402
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    EXPECTED_CONTROLS,
    EXPECTED_ERRORS,
    EXPECTED_EVENTS,
    REVIEW_BUDGET,
    _bootstrap_delta,
    _error_metrics,
)


PROTOCOL = "formulaguard_peer_repair_responsibility_score_v1"
PREDICTION_PROTOCOL = "formulaguard_peer_repair_responsibility_prediction_v1"
DEFAULT_OUTPUT = ROOT / "results/peer_repair_responsibility_score_v1"


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_clean_tracked_worktree() -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("tracked worktree must be clean before responsibility scoring")


def _relative(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else str(resolved)


def load_responsibility(
    directory: Path,
    profiles: Sequence[Mapping[str, str]],
    signals: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, object], dict[str, object]]:
    _reject_protected(directory)
    complete = _load_json(directory / "complete.json")
    metadata = _load_json(directory / "metadata.json")
    if (
        complete.get("protocol") != RESPONSIBILITY_RUN_PROTOCOL
        or metadata.get("protocol") != RESPONSIBILITY_RUN_PROTOCOL
        or complete.get("complete") is not True
        or complete.get("profile_count") != len(profiles)
        or complete.get("shard_count") != len(profiles)
        or complete.get("label_inputs") != []
        or complete.get("protected_data_inputs") != []
        or complete.get("revealed_label_files_read") != []
        or metadata.get("label_inputs") != []
        or metadata.get("protected_data_inputs") != []
        or complete.get("metadata_sha256") != sha256(directory / "metadata.json")
    ):
        raise ValueError("responsibility completion violates the scoring contract")
    paths = sorted((directory / "shards").glob("*.json"), key=lambda path: path.name)
    if len(paths) != len(profiles) or _combined_shards(paths) != complete.get("combined_shards_sha256"):
        raise ValueError("responsibility shard inventory or hash differs")
    profiles_by_id = {str(row["unit_id"]): row for row in profiles}
    result: dict[str, dict[str, object]] = {}
    for path in paths:
        payload = _load_json(path)
        unit_id = str(payload.get("unit_id", ""))
        if unit_id not in profiles_by_id or unit_id in result or path.name != shard_name(unit_id):
            raise ValueError(f"unexpected or duplicate responsibility unit: {unit_id!r}")
        audit = signals[unit_id].get("audit")
        if not isinstance(audit, dict):
            raise ValueError(f"source peer audit is malformed: {unit_id}")
        result[unit_id] = _validate_record(path, profiles_by_id[unit_id], audit)
    if set(result) != set(profiles_by_id):
        raise ValueError("responsibility unit inventory differs from profiles")
    return result, complete, metadata


def build_prediction(
    unit_id: str,
    v4_payload: Mapping[str, object],
    responsibility_payload: Mapping[str, object],
) -> dict[str, object]:
    ranking = v4_payload.get("ranking")
    probe = responsibility_payload.get("probe")
    if not isinstance(ranking, list) or not isinstance(probe, Mapping):
        raise ValueError(f"V4 or responsibility payload is malformed: {unit_id}")
    v4_cells = tuple(str(row["cell"]) for row in ranking if isinstance(row, Mapping))
    if len(v4_cells) != len(ranking) or len(v4_cells) != len(set(v4_cells)):
        raise ValueError(f"V4 ranking is malformed: {unit_id}")
    metrics = probe.get("responsibility")
    passed = bool(isinstance(metrics, Mapping) and metrics.get("responsibility_pass") is True)
    candidate_rank = probe.get("candidate_v4_rank")
    candidate: str | None = None
    if probe.get("candidate_selected") is True:
        if (
            not isinstance(candidate_rank, int)
            or isinstance(candidate_rank, bool)
            or candidate_rank <= REVIEW_BUDGET
            or candidate_rank > len(v4_cells)
        ):
            raise ValueError(f"selected responsibility candidate rank is invalid: {unit_id}")
        candidate = v4_cells[candidate_rank - 1]
    if passed and candidate is None:
        raise ValueError(f"responsibility passed without a fixed candidate: {unit_id}")
    model_ranking = tuple(rerank(v4_cells, candidate if passed else None))
    forced_ranking = tuple(rerank(v4_cells, candidate))
    if probe.get("candidate_selected") is not True:
        state = "no_candidate"
    elif probe.get("responsibility_evaluated") is not True:
        state = "not_evaluated"
    elif passed:
        state = "responsibility_pass"
    else:
        state = "responsibility_fail"
    exact_positive = bool(
        isinstance(metrics, Mapping) and metrics.get("positive_exact_repair_delta") is True
    )
    sink_changed = bool(
        isinstance(metrics, Mapping) and metrics.get("changed_reachable_visible_sink") is True
    )
    no_new_errors = bool(
        isinstance(metrics, Mapping) and metrics.get("no_new_evaluation_errors") is True
    )
    return {
        "protocol": PREDICTION_PROTOCOL,
        "unit_id": unit_id,
        "workbook_sha256": v4_payload.get("workbook_sha256"),
        "ranking": list(model_ranking),
        "top5": list(model_ranking[:REVIEW_BUDGET]),
        "forced_peer_top1_ranking": list(forced_ranking),
        "candidate_v4_rank": candidate_rank if candidate is not None else None,
        "probe_state": state,
        "responsibility_pass": passed,
        "positive_exact_repair_delta": exact_positive,
        "changed_reachable_visible_sink": sink_changed,
        "no_new_evaluation_errors": no_new_errors,
        "changed": model_ranking != v4_cells,
        "label_inputs": [],
        "protected_data_inputs": [],
    }


def write_predictions(
    v4: Mapping[str, Mapping[str, object]],
    responsibilities: Mapping[str, Mapping[str, object]],
    output_dir: Path,
    responsibility_complete: Mapping[str, object],
) -> tuple[dict[str, dict[str, object]], Path]:
    if set(v4) != set(responsibilities):
        raise ValueError("V4 and responsibility unit inventories differ")
    predictions: dict[str, dict[str, object]] = {}
    for unit_id in sorted(v4):
        prediction = build_prediction(unit_id, v4[unit_id], responsibilities[unit_id])
        target = output_dir / "shards" / shard_name(unit_id)
        write_immutable(
            target,
            (json.dumps(prediction, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
        predictions[unit_id] = prediction
    paths = sorted((output_dir / "shards").glob("*.json"), key=lambda path: path.name)
    completion: dict[str, object] = {
        "protocol": PREDICTION_PROTOCOL,
        "complete": True,
        "source_lock_git_commit": _git_commit(),
        "unit_count": len(predictions),
        "shard_count": len(paths),
        "changed_units": sum(bool(row["changed"]) for row in predictions.values()),
        "responsibility_combined_shards_sha256": responsibility_complete["combined_shards_sha256"],
        "combined_shards_sha256": _combined_shards(paths),
        "label_inputs": [],
        "protected_data_inputs": [],
        "revealed_label_files_read": [],
    }
    completion_path = output_dir / "prediction_complete.json"
    write_immutable(
        completion_path,
        (json.dumps(completion, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return predictions, completion_path


def event_rows(
    events: Sequence[Mapping[str, object]],
    v4: Mapping[str, Mapping[str, object]],
    predictions: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in events:
        unit_id = str(event["unit_id"])
        prediction = predictions[unit_id]
        ranking = v4[unit_id]["ranking"]
        if not isinstance(ranking, list):
            raise ValueError(f"V4 ranking is malformed: {unit_id}")
        v4_cells = [str(row["cell"]) for row in ranking if isinstance(row, Mapping)]
        if list(event["v4_rank"]) != v4_cells:
            raise ValueError(f"event V4 ranking differs from frozen source: {unit_id}")
        sources = [str(cell) for cell in event["source_formula_cells"]]
        v4_source_rank = source_rank(v4_cells, sources)
        model_source_rank = source_rank(prediction["ranking"], sources)
        forced_source_rank = source_rank(prediction["forced_peer_top1_ranking"], sources)
        v4_top5 = int(v4_source_rank is not None and v4_source_rank <= REVIEW_BUDGET)
        model_top5 = int(model_source_rank is not None and model_source_rank <= REVIEW_BUDGET)
        forced_top5 = int(forced_source_rank is not None and forced_source_rank <= REVIEW_BUDGET)
        rows.append({
            "event_id": str(event["event_id"]),
            "unit_id": unit_id,
            "case_kind": str(event["case_kind"]),
            "cohort": str(event["cohort"]),
            "structure_group": str(event["structure_group"]),
            "fold": structure_fold(str(event["structure_group"])),
            "probe_state": prediction["probe_state"],
            "candidate_v4_rank": prediction["candidate_v4_rank"],
            "responsibility_pass": bool(prediction["responsibility_pass"]),
            "positive_exact_repair_delta": bool(prediction["positive_exact_repair_delta"]),
            "changed_reachable_visible_sink": bool(prediction["changed_reachable_visible_sink"]),
            "no_new_evaluation_errors": bool(prediction["no_new_evaluation_errors"]),
            "acted": bool(prediction["changed"]),
            "v4_source_rank": v4_source_rank,
            "model_source_rank": model_source_rank,
            "forced_peer_top1_source_rank": forced_source_rank,
            "v4_top5": v4_top5,
            "model_top5": model_top5,
            "forced_peer_top1_top5": forced_top5,
            "v4_mrr": 1.0 / v4_source_rank if v4_source_rank else 0.0,
            "model_mrr": 1.0 / model_source_rank if model_source_rank else 0.0,
            "residual_delta": model_top5 - v4_top5,
            "forced_peer_top1_residual_delta": forced_top5 - v4_top5,
        })
    return sorted(rows, key=lambda row: str(row["event_id"]))


def _strata(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for state in ("responsibility_pass", "responsibility_fail", "not_evaluated", "no_candidate"):
        subset = [row for row in rows if row["probe_state"] == state]
        errors = [row for row in subset if row["case_kind"] == "error"]
        controls = [row for row in subset if row["case_kind"] == "control"]
        result[state] = {
            "units": len({str(row["unit_id"]) for row in subset}),
            "error_events": len(errors),
            "forced_gains": sum(int(row["forced_peer_top1_residual_delta"]) == 1 for row in errors),
            "forced_neutral": sum(int(row["forced_peer_top1_residual_delta"]) == 0 for row in errors),
            "forced_losses": sum(int(row["forced_peer_top1_residual_delta"]) == -1 for row in errors),
            "control_workbooks": len({str(row["unit_id"]) for row in controls}),
        }
    return result


def summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    if len(rows) != EXPECTED_EVENTS or len(errors) != EXPECTED_ERRORS or len(controls) != EXPECTED_CONTROLS:
        raise ValueError("public event counts differ from the preregistered inventory")
    overall = _error_metrics(errors)
    by_cohort = {
        cohort: _error_metrics([row for row in errors if row["cohort"] == cohort])
        for cohort in sorted({str(row["cohort"]) for row in errors})
    }
    by_fold = {
        str(fold): _error_metrics([row for row in errors if row["fold"] == fold])
        for fold in range(5)
    }
    control_units = {str(row["unit_id"]) for row in controls}
    acted_control_units = {str(row["unit_id"]) for row in controls if row["acted"]}
    control_rate = len(acted_control_units) / len(control_units) if control_units else 0.0
    bootstrap = _bootstrap_delta(errors)
    gates = {
        "overall_top5_gain_at_least_5pp": float(overall["top5_delta_pp"]) >= 5.0,
        "enron_top5_gain_at_least_5pp": float(by_cohort["enron"]["top5_delta_pp"]) >= 5.0,
        "overall_mrr_nonnegative": float(overall["mrr_delta"]) >= 0.0,
        "positive_residual_action_precision_at_least_75pct": (
            float(overall["positive_residual_action_precision"]) >= 0.75
        ),
        "v4_hit_loss_rate_at_most_2pct": float(overall["v4_hit_loss_rate"]) <= 0.02,
        "control_workbook_action_rate_at_most_15pct": control_rate <= 0.15,
        "structure_bootstrap_lower_bound_positive": float(bootstrap["ci95_delta_pp"][0]) > 0.0,
    }
    return {
        "overall": overall,
        "by_cohort": by_cohort,
        "by_structure_fold": by_fold,
        "controls": {
            "events": len(controls),
            "workbooks": len(control_units),
            "acted_workbooks": len(acted_control_units),
            "workbook_action_rate": control_rate,
        },
        "structure_group_bootstrap": bootstrap,
        "mechanism_strata": _strata(rows),
        "public_gates": gates,
        "all_public_gates_passed": all(gates.values()),
    }


def run(
    *,
    profiles_path: Path,
    events_path: Path,
    v4_dir: Path,
    signal_dir: Path,
    responsibility_dir: Path,
    output_dir: Path,
) -> Path:
    for path in (profiles_path, events_path, v4_dir, signal_dir, responsibility_dir, output_dir):
        _reject_protected(path)
    _require_clean_tracked_worktree()
    profiles = read_profiles(profiles_path.resolve())
    v4, v4_complete = _load_sources(v4_dir.resolve(), profiles, kind="V4")
    signals, signal_complete = _load_sources(signal_dir.resolve(), profiles, kind="peer signals")
    responsibilities, responsibility_complete, responsibility_metadata = load_responsibility(
        responsibility_dir.resolve(), profiles, signals,
    )
    if responsibility_metadata.get("v4_combined_shards_sha256") != v4_complete["combined_shards_sha256"]:
        raise ValueError("responsibility run refers to a different V4 source")
    if responsibility_metadata.get("signal_combined_shards_sha256") != signal_complete["combined_shards_sha256"]:
        raise ValueError("responsibility run refers to a different peer-signal source")
    output_dir = output_dir.resolve()
    predictions, prediction_complete_path = write_predictions(
        v4, responsibilities, output_dir, responsibility_complete,
    )

    events = load_event_rows(events_path.resolve())
    rows = event_rows(events, v4, predictions)
    summary = summarize(rows)
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    ).encode("utf-8")
    event_path = output_dir / "event_scores.jsonl"
    write_immutable(event_path, event_bytes)
    prediction_complete = _load_json(prediction_complete_path)
    receipt: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "source_lock_git_commit": _git_commit(),
        "status": (
            "public_development_gate_passed"
            if summary["all_public_gates_passed"]
            else "public_development_gate_failed"
        ),
        "model": {
            "architecture": "frozen_v4_top4_plus_output_coupled_peer_fifth",
            "review_budget": REVIEW_BUDGET,
            "immutable_v4_prefix": 4,
            "candidate_policy": "peer_review_top1_outside_v4_top5",
            "action_rule": "positive_exact_delta_and_changed_visible_sink_without_new_errors",
            "learned_weights": 0,
            "numeric_thresholds": 0,
            "formal_v5_authorized": False,
            "bounded_v5_core_candidate_authorized": summary["all_public_gates_passed"],
        },
        "inputs": {
            "profiles": {"path": _relative(profiles_path), "sha256": sha256(profiles_path)},
            "events_for_scoring_only": {"path": _relative(events_path), "sha256": sha256(events_path)},
            "v4": {"path": _relative(v4_dir), "combined_shards_sha256": v4_complete["combined_shards_sha256"]},
            "peer_signals": {"path": _relative(signal_dir), "combined_shards_sha256": signal_complete["combined_shards_sha256"]},
            "responsibility": {
                "path": _relative(responsibility_dir),
                "complete_sha256": sha256(responsibility_dir / "complete.json"),
                "combined_shards_sha256": responsibility_complete["combined_shards_sha256"],
                "source_lock_git_commit": responsibility_metadata["git_commit"],
                "label_inputs": responsibility_complete["label_inputs"],
                "revealed_label_files_read": responsibility_complete["revealed_label_files_read"],
            },
        },
        "counts": {
            "units": len(predictions),
            "events": len(rows),
            "errors": sum(row["case_kind"] == "error" for row in rows),
            "controls": sum(row["case_kind"] == "control" for row in rows),
            "changed_units": prediction_complete["changed_units"],
        },
        "summary": summary,
        "artifacts": {
            "prediction_complete": {
                "path": _relative(prediction_complete_path),
                "sha256": sha256(prediction_complete_path),
                "combined_shards_sha256": prediction_complete["combined_shards_sha256"],
            },
            "event_scores": {"path": _relative(event_path), "sha256": hashlib.sha256(event_bytes).hexdigest()},
        },
        "bootstrap_contract": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED},
        "label_boundary": {
            "prediction_label_inputs": [],
            "labels_opened_after_prediction_complete": True,
        },
        "protected_data_inputs": [],
        "private_240_120_accessed": False,
    }
    receipt["receipt_sha256"] = stable_hash(receipt)
    receipt_path = output_dir / "receipt.json"
    write_immutable(
        receipt_path,
        (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--responsibility", type=Path, default=DEFAULT_RESPONSIBILITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        receipt = run(
            profiles_path=args.profiles,
            events_path=args.events,
            v4_dir=args.v4,
            signal_dir=args.signals,
            responsibility_dir=args.responsibility,
            output_dir=args.output,
        )
    except Exception as exc:
        raise SystemExit(f"peer repair responsibility scoring refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
