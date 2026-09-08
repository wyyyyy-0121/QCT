"""Run the preregistered nested-fold Peer Repair learnability audit."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.peer_repair_closure import select_peer_candidate
from formulaguard.peer_repair_learnability import (
    FEATURE_VIEWS,
    VIEW_ORDER,
    build_feature_views,
)
from formulaguard.v4_rrc import candidate_feature_map, fit_ridge
from scripts.extract_peer_repair_closure import (
    DEFAULT_PROFILES,
    DEFAULT_SIGNALS,
    DEFAULT_V4,
    _load_sources,
    _reject_protected,
)
from scripts.extract_peer_repair_responsibility import (
    DEFAULT_OUTPUT as DEFAULT_RESPONSIBILITY,
)
from scripts.run_model_discovery_signals import read_profiles, sha256
from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    Unit,
    build_units,
    choose_threshold,
    event_prediction_rows,
    load_event_rows,
    predict_units,
    stable_hash,
    summarize_predictions,
    training_examples,
    write_immutable,
)
from scripts.score_peer_repair_closure import (
    DEFAULT_CLOSURE,
    load_closure,
)
from scripts.score_peer_repair_responsibility import load_responsibility

PROTOCOL = "formulaguard_peer_repair_learnability_audit_v1"
DEFAULT_PREREGISTRATION = (
    ROOT / "research/V5_PEER_REPAIR_LEARNABILITY_AUDIT_PREREGISTRATION.md"
)
DEFAULT_OUTPUT = ROOT / "results/peer_repair_learnability_audit_v1"
BOOTSTRAP_SEED = 20260901
BOOTSTRAP_SAMPLES = 10_000
EXPECTED_PROFILES_SHA256 = (
    "26f7d1d64a65860fb90714a51beb602742d28d1cfefeea8cbadf331b0e1463dc"
)
EXPECTED_EVENTS_SHA256 = (
    "c68e2436957a83f6e8e80e6de6c5a3d45ca35b71e162ebc928275352ba90dd34"
)
EXPECTED_V4_SHARDS_SHA256 = (
    "b6ad4b46058e7c5b966bd8faa4b790f52c33a87fa03631fa744fe4a1df28d1f6"
)
EXPECTED_SIGNAL_SHARDS_SHA256 = (
    "17fab17b109376e22d339a25d3861aa8c72e5c05a2c410cceab1845938a93890"
)
EXPECTED_CLOSURE_SHARDS_SHA256 = (
    "74dea9153e9e6422f66ba4f7d99534d8a01d343dc7cb33752060aa050dea0f3d"
)
EXPECTED_RESPONSIBILITY_SHARDS_SHA256 = (
    "3d8e9bd9deffca914f60a6eb8459817cdb521605d2c911d661a3478aba614e7f"
)
EXPECTED_EVENTS = 220
EXPECTED_ERRORS = 190
EXPECTED_CONTROLS = 30


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
        raise ValueError("tracked worktree must be clean before learnability audit")


def _relative(path: Path) -> str:
    resolved = path.resolve()
    return (
        resolved.relative_to(ROOT).as_posix()
        if resolved.is_relative_to(ROOT)
        else str(resolved)
    )


def _probe(record: Mapping[str, object], unit_id: str) -> Mapping[str, object]:
    probe = record.get("probe")
    if not isinstance(probe, Mapping):
        raise TypeError(f"Peer Repair probe is malformed: {unit_id}")
    return probe


def build_view_units(
    base_units: Sequence[Unit],
    closures: Mapping[str, Mapping[str, object]],
    responsibilities: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, list[Unit]], dict[str, int]]:
    """Bind the same fixed candidate inventory to all five feature views."""

    if set(closures) != {unit.unit_id for unit in base_units} or set(responsibilities) != set(closures):
        raise ValueError("Peer Repair feature inventories differ from public units")
    output = {name: [] for name in VIEW_ORDER}
    selected = 0
    eligible = 0
    no_hypothesis = 0
    for unit in base_units:
        closure = _probe(closures[unit.unit_id], unit.unit_id)
        responsibility = _probe(responsibilities[unit.unit_id], unit.unit_id)
        selected_flags = (
            closure.get("candidate_selected") is True,
            responsibility.get("candidate_selected") is True,
        )
        if selected_flags[0] != selected_flags[1]:
            raise ValueError(f"Closure/responsibility candidate selection differs: {unit.unit_id}")
        candidate, reason = select_peer_candidate(unit.v4_cells, unit.audit)
        if (candidate is not None) != selected_flags[0]:
            raise ValueError(f"persisted Peer candidate differs from frozen policy: {unit.unit_id}")
        reason_differs = (
            closure.get("selection_reason") != reason
            or responsibility.get("selection_reason") != reason
        )
        no_hypothesis_reason = (
            candidate is not None
            and closure.get("selection_reason") == "peer_top1_has_no_repair_hypothesis"
            and responsibility.get("selection_reason") == "peer_top1_has_no_repair_hypothesis"
        )
        if reason_differs and not no_hypothesis_reason:
            raise ValueError(f"Peer Repair selection reason differs: {unit.unit_id}")
        executed = closure.get("repair_executed") is True
        evaluated = responsibility.get("responsibility_evaluated") is True
        if executed != evaluated:
            raise ValueError(f"Closure/responsibility execution differs: {unit.unit_id}")
        if candidate is not None:
            selected += 1
        if candidate is None or not executed:
            if candidate is not None:
                no_hypothesis += 1
            for name in VIEW_ORDER:
                output[name].append(replace(unit, candidates=(), features={}))
            continue
        if candidate not in unit.candidates:
            raise ValueError(f"fixed Peer Top-1 is absent from the source candidate pool: {unit.unit_id}")
        rank = unit.v4_cells.index(candidate) + 1
        if closure.get("candidate_v4_rank") != rank or responsibility.get("candidate_v4_rank") != rank:
            raise ValueError(f"Peer Repair candidate rank differs from V4: {unit.unit_id}")
        base = candidate_feature_map(candidate, unit.audit, unit.v4_rows)
        feature_maps = build_feature_views(base, closure, responsibility)
        eligible += 1
        for name in VIEW_ORDER:
            output[name].append(replace(
                unit,
                candidates=(candidate,),
                features={candidate: feature_maps[name]},
            ))
    return output, {
        "selected_peer_top1_units": selected,
        "eligible_repaired_candidate_units": eligible,
        "selected_without_repair_hypothesis_units": no_hypothesis,
        "forced_abstention_units": len(base_units) - eligible,
    }


def fit_view(units: Sequence[Unit], view_name: str):
    feature_rows, targets, weights = training_examples(units, revision=0)
    view = FEATURE_VIEWS[view_name]
    return fit_ridge(
        feature_rows,
        targets,
        weights,
        ridge_lambda=1.0,
        continuous_features=view.continuous,
        binary_features=view.binary,
    )


def _bootstrap_delta(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_group: dict[str, list[float]] = {}
    for row in rows:
        if row["case_kind"] != "error":
            continue
        group = str(row["structure_group"])
        by_group.setdefault(group, []).append(
            float(row["controller_top5"]) - float(row["v4_top5"])
        )
    group_deltas = [
        statistics.fmean(by_group[group]) for group in sorted(by_group)
    ]
    if not group_deltas:
        raise ValueError("cannot bootstrap an empty learnability error table")
    rng = random.Random(BOOTSTRAP_SEED)
    estimates = sorted(
        statistics.fmean(rng.choice(group_deltas) for _ in group_deltas)
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return {
        "seed": BOOTSTRAP_SEED,
        "samples": BOOTSTRAP_SAMPLES,
        "groups": len(group_deltas),
        "mean_delta_pp": 100.0 * statistics.fmean(group_deltas),
        "ci95_delta_pp": [100.0 * estimates[250], 100.0 * estimates[9749]],
        "positive_groups": sum(value > 0.0 for value in group_deltas),
        "zero_groups": sum(value == 0.0 for value in group_deltas),
        "negative_groups": sum(value < 0.0 for value in group_deltas),
    }


def _public_gates(
    summary: Mapping[str, object],
    bootstrap: Mapping[str, object],
) -> dict[str, bool]:
    cohorts = summary.get("by_cohort")
    if not isinstance(cohorts, Mapping) or not isinstance(cohorts.get("enron"), Mapping):
        raise TypeError("learnability summary has no Enron cohort")
    enron = cohorts["enron"]
    control_rate = summary.get("control_workbook_action_rate")
    ci = bootstrap.get("ci95_delta_pp")
    if not isinstance(ci, list) or len(ci) != 2:
        raise ValueError("learnability bootstrap interval is malformed")
    return {
        "overall_top5_gain_at_least_5pp": float(summary["top5_difference"]) >= 0.05,
        "enron_top5_gain_at_least_5pp": float(enron["top5_difference"]) >= 0.05,
        "overall_mrr_nonnegative": float(summary["mrr_difference"]) >= 0.0,
        "positive_residual_action_precision_at_least_75pct": (
            float(summary["positive_residual_action_precision"]) >= 0.75
        ),
        "v4_hit_loss_rate_at_most_2pct": float(summary["v4_hit_loss_rate"]) <= 0.02,
        "control_workbook_action_rate_at_most_15pct": (
            control_rate is not None and float(control_rate) <= 0.15
        ),
        "structure_bootstrap_lower_bound_positive": float(ci[0]) > 0.0,
    }


def _persisted_prediction(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "event_id": row["event_id"],
        "unit_id": row["unit_id"],
        "structure_group": row["structure_group"],
        "cohort": row["cohort"],
        "case_kind": row["case_kind"],
        "outer_fold": row["outer_fold"],
        "candidate_available": row["candidate"] is not None,
        "candidate_score": row["candidate_score"],
        "threshold": row["threshold"],
        "acted": row["acted"],
        "v4_source_rank": row["v4_source_rank"],
        "model_source_rank": row["controller_source_rank"],
        "v4_top5": row["v4_top5"],
        "model_top5": row["controller_top5"],
        "residual_delta": row["residual_delta"],
    }


def evaluate_view(units: Sequence[Unit], view_name: str) -> dict[str, object]:
    if view_name not in FEATURE_VIEWS:
        raise ValueError(f"unknown learnability feature view: {view_name}")
    fold_artifacts: list[dict[str, object]] = []
    outer_rows: list[dict[str, object]] = []
    for outer_fold in range(5):
        calibration_fold = (outer_fold + 1) % 5
        train = [unit for unit in units if unit.fold not in {outer_fold, calibration_fold}]
        calibration = [unit for unit in units if unit.fold == calibration_fold]
        test = [unit for unit in units if unit.fold == outer_fold]
        train_groups = {unit.structure_group for unit in train}
        calibration_groups = {unit.structure_group for unit in calibration}
        test_groups = {unit.structure_group for unit in test}
        if (
            train_groups & calibration_groups
            or train_groups & test_groups
            or calibration_groups & test_groups
        ):
            raise ValueError("structure group crossed a nested learnability split")
        model = fit_view(train, view_name)
        calibration_predictions = predict_units(model, calibration, revision=0)
        threshold, calibration_result = choose_threshold(
            calibration, calibration_predictions,
        )
        test_predictions = predict_units(model, test, revision=0)
        test_rows = event_prediction_rows(
            test,
            test_predictions,
            threshold,
            outer_fold=outer_fold,
        )
        outer_rows.extend(test_rows)
        fold_artifacts.append({
            "outer_fold": outer_fold,
            "calibration_fold": calibration_fold,
            "training_folds": sorted({0, 1, 2, 3, 4} - {outer_fold, calibration_fold}),
            "train_units": len(train),
            "calibration_units": len(calibration),
            "test_units": len(test),
            "train_structure_groups": len(train_groups),
            "calibration_structure_groups": len(calibration_groups),
            "test_structure_groups": len(test_groups),
            "model": model.to_dict(),
            "calibration": calibration_result,
            "test_summary": summarize_predictions(test_rows),
        })
    outer_rows.sort(key=lambda row: str(row["event_id"]))
    event_ids = [str(row["event_id"]) for row in outer_rows]
    if len(event_ids) != EXPECTED_EVENTS or len(set(event_ids)) != EXPECTED_EVENTS:
        raise ValueError("outer learnability predictions do not cover each event exactly once")
    errors = sum(row["case_kind"] == "error" for row in outer_rows)
    controls = sum(row["case_kind"] == "control" for row in outer_rows)
    if errors != EXPECTED_ERRORS or controls != EXPECTED_CONTROLS:
        raise ValueError("outer learnability event inventory differs from preregistration")
    summary = summarize_predictions(outer_rows)
    bootstrap = _bootstrap_delta(outer_rows)
    gates = _public_gates(summary, bootstrap)
    view = FEATURE_VIEWS[view_name]
    return {
        "view": view_name,
        "feature_contract": {
            "continuous": list(view.continuous),
            "binary": list(view.binary),
            "raw_feature_count": len(view.continuous) + len(view.binary),
            "model_feature_count_with_missing_indicators": view.model_feature_count,
            "ridge_lambda": 1.0,
        },
        "fold_artifacts": fold_artifacts,
        "finite_calibration_thresholds": sum(
            fold["calibration"]["finite_threshold"] for fold in fold_artifacts
        ),
        "outer_summary": summary,
        "structure_group_bootstrap": bootstrap,
        "public_gates": gates,
        "all_public_gates_passed": all(gates.values()),
        "outer_predictions": [_persisted_prediction(row) for row in outer_rows],
    }


def select_passing_view(results: Mapping[str, Mapping[str, object]]) -> str | None:
    passed = [name for name in VIEW_ORDER if results[name]["all_public_gates_passed"]]
    if not passed:
        return None

    def key(name: str) -> tuple[float, float, float, float, int, int]:
        result = results[name]
        summary = result["outer_summary"]
        cohorts = summary["by_cohort"]
        feature_contract = result["feature_contract"]
        return (
            float(summary["top5_difference"]),
            float(cohorts["enron"]["top5_difference"]),
            float(summary["mrr_difference"]),
            float(summary["positive_residual_action_precision"]),
            -int(feature_contract["model_feature_count_with_missing_indicators"]),
            -VIEW_ORDER.index(name),
        )

    return max(passed, key=key)


def run(
    *,
    profiles_path: Path,
    events_path: Path,
    v4_dir: Path,
    signal_dir: Path,
    closure_dir: Path,
    responsibility_dir: Path,
    preregistration_path: Path,
    output_dir: Path,
) -> Path:
    paths = (
        profiles_path,
        events_path,
        v4_dir,
        signal_dir,
        closure_dir,
        responsibility_dir,
        preregistration_path,
        output_dir,
    )
    for path in paths:
        _reject_protected(path)
    _require_clean_tracked_worktree()
    if sha256(profiles_path) != EXPECTED_PROFILES_SHA256:
        raise ValueError("learnability profile hash differs from preregistration")
    if sha256(events_path) != EXPECTED_EVENTS_SHA256:
        raise ValueError("learnability event hash differs from preregistration")
    profiles = read_profiles(profiles_path)
    events = load_event_rows(events_path)
    signals, signal_complete = _load_sources(signal_dir, profiles, kind="peer signals")
    v4, v4_complete = _load_sources(v4_dir, profiles, kind="V4")
    closures, closure_complete, closure_metadata = load_closure(
        closure_dir, profiles, signals,
    )
    responsibilities, responsibility_complete, responsibility_metadata = load_responsibility(
        responsibility_dir, profiles, signals,
    )
    observed_hashes = {
        "v4": v4_complete.get("combined_shards_sha256"),
        "signals": signal_complete.get("combined_shards_sha256"),
        "closure": closure_complete.get("combined_shards_sha256"),
        "responsibility": responsibility_complete.get("combined_shards_sha256"),
    }
    expected_hashes = {
        "v4": EXPECTED_V4_SHARDS_SHA256,
        "signals": EXPECTED_SIGNAL_SHARDS_SHA256,
        "closure": EXPECTED_CLOSURE_SHARDS_SHA256,
        "responsibility": EXPECTED_RESPONSIBILITY_SHARDS_SHA256,
    }
    if observed_hashes != expected_hashes:
        raise ValueError("learnability shard hashes differ from preregistration")
    for metadata, kind in (
        (closure_metadata, "closure"),
        (responsibility_metadata, "responsibility"),
    ):
        if (
            metadata.get("v4_combined_shards_sha256") != EXPECTED_V4_SHARDS_SHA256
            or metadata.get("signal_combined_shards_sha256") != EXPECTED_SIGNAL_SHARDS_SHA256
            or metadata.get("label_inputs") != []
            or metadata.get("protected_data_inputs") != []
        ):
            raise ValueError(f"{kind} metadata crosses the frozen learnability boundary")
    base_units = build_units(events, signals, v4)
    view_units, candidate_counts = build_view_units(
        base_units, closures, responsibilities,
    )
    results = {
        name: evaluate_view(view_units[name], name)
        for name in VIEW_ORDER
    }
    selected_view = select_passing_view(results)
    source_hashes = {
        "profiles": EXPECTED_PROFILES_SHA256,
        "events": EXPECTED_EVENTS_SHA256,
        "v4_combined_shards": EXPECTED_V4_SHARDS_SHA256,
        "signal_combined_shards": EXPECTED_SIGNAL_SHARDS_SHA256,
        "closure_combined_shards": EXPECTED_CLOSURE_SHARDS_SHA256,
        "responsibility_combined_shards": EXPECTED_RESPONSIBILITY_SHARDS_SHA256,
        "preregistration": sha256(preregistration_path),
        "v4_rrc": sha256(ROOT / "formulaguard/v4_rrc.py"),
        "feature_views": sha256(ROOT / "formulaguard/peer_repair_learnability.py"),
        "runner": sha256(Path(__file__)),
    }
    deterministic_projection = {
        "source_hashes": source_hashes,
        "candidate_counts": candidate_counts,
        "view_results": results,
        "selected_view": selected_view,
    }
    payload = {
        "protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "inputs": {
            "profiles": _relative(profiles_path),
            "events": _relative(events_path),
            "v4": _relative(v4_dir),
            "signals": _relative(signal_dir),
            "closure": _relative(closure_dir),
            "responsibility": _relative(responsibility_dir),
            "preregistration": _relative(preregistration_path),
        },
        "counts": {
            "units": len(base_units),
            "events": len(events),
            "errors": sum(row["case_kind"] == "error" for row in events),
            "controls": sum(row["case_kind"] == "control" for row in events),
            **candidate_counts,
        },
        "nested_split": {
            "outer_fold": "i",
            "calibration_fold": "(i+1)%5",
            "training_folds": "remaining_three",
            "structure_fold_function": "sha256_prefix_mod_5",
        },
        "source_hashes": source_hashes,
        "view_results": results,
        "decision": {
            "passing_views": [
                name for name in VIEW_ORDER
                if results[name]["all_public_gates_passed"]
            ],
            "selected_view": selected_view,
            "peer_residual_route": (
                "candidate_freeze_protocol_authorized"
                if selected_view is not None
                else "stop_after_all_five_views_failed"
            ),
            "protected_240_120_access_authorized": False,
        },
        "deterministic_projection_sha256": stable_hash(deterministic_projection),
        "label_inputs": [_relative(events_path)],
        "protected_data_inputs": [],
    }
    output_path = output_dir.resolve() / "receipt.json"
    write_immutable(
        output_path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--closure", type=Path, default=DEFAULT_CLOSURE)
    parser.add_argument("--responsibility", type=Path, default=DEFAULT_RESPONSIBILITY)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = run(
        profiles_path=args.profiles.resolve(),
        events_path=args.events.resolve(),
        v4_dir=args.v4.resolve(),
        signal_dir=args.signals.resolve(),
        closure_dir=args.closure.resolve(),
        responsibility_dir=args.responsibility.resolve(),
        preregistration_path=args.preregistration.resolve(),
        output_dir=args.output.resolve(),
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
