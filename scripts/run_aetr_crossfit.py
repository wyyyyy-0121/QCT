"""Run the preregistered AETR structure-fold and corpus-transfer audit."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.aetr import (
    AETR_VIEWS,
    VIEW_ORDER,
    ranking_from_model,
    workbook_feature_maps,
)
from formulaguard.v4_rrc import fit_ridge, structure_fold
from scripts.extract_peer_repair_closure import (
    DEFAULT_PROFILES,
    DEFAULT_SIGNALS,
    DEFAULT_V4,
    _load_sources,
    _reject_protected,
)
from scripts.run_model_discovery_signals import read_profiles, sha256
from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    load_event_rows,
    source_rank,
    stable_hash,
    summarize_predictions,
    write_immutable,
)

PROTOCOL = "formulaguard_aetr_crossfit_v1"
DEFAULT_PREREGISTRATION = ROOT / "research/V5_AETR_PREREGISTRATION.md"
DEFAULT_OUTPUT = ROOT / "results/aetr_crossfit_v1"
BOOTSTRAP_SEED = 20260901
BOOTSTRAP_SAMPLES = 10_000
EXPECTED_PROFILES_SHA256 = (
    "26f7d1d64a65860fb90714a51beb602742d28d1cfefeea8cbadf331b0e1463dc"
)
EXPECTED_EVENTS_SHA256 = (
    "c68e2436957a83f6e8e80e6de6c5a3d45ca35b71e162ebc928275352ba90dd34"
)
EXPECTED_SIGNAL_SHARDS_SHA256 = (
    "17fab17b109376e22d339a25d3861aa8c72e5c05a2c410cceab1845938a93890"
)
EXPECTED_V4_SHARDS_SHA256 = (
    "b6ad4b46058e7c5b966bd8faa4b790f52c33a87fa03631fa744fe4a1df28d1f6"
)
EXPECTED_EVENTS = 220
EXPECTED_ERRORS = 190
EXPECTED_CONTROLS = 30
LOCO_COHORTS = (
    "enron",
    "historical_100",
    "public:integer_corpus",
    "public:modified_euses",
    "public:info1",
)
MAJOR_COHORTS = LOCO_COHORTS[:-1]
N2_COHORTS = (
    "historical_100",
    "public:integer_corpus",
    "public:modified_euses",
)


@dataclass(frozen=True)
class AETRUnit:
    unit_id: str
    structure_group: str
    fold: int
    cohort: str
    events: tuple[dict[str, object], ...]
    audit: Mapping[str, object]
    inventory: tuple[str, ...]
    features: Mapping[str, Mapping[str, float]]

    @property
    def sources(self) -> frozenset[str]:
        return frozenset(
            str(cell)
            for event in self.events
            if event["case_kind"] == "error"
            for cell in event["source_formula_cells"]
        )


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
        raise ValueError("tracked worktree must be clean before AETR crossfit")


def _relative(path: Path) -> str:
    resolved = path.resolve()
    return (
        resolved.relative_to(ROOT).as_posix()
        if resolved.is_relative_to(ROOT)
        else str(resolved)
    )


def build_units(
    event_rows: Sequence[dict[str, object]],
    signal_shards: Mapping[str, Mapping[str, object]],
) -> list[AETRUnit]:
    by_unit: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in event_rows:
        by_unit[str(row["unit_id"])].append(row)
    if set(by_unit) != set(signal_shards):
        raise ValueError("AETR event and signal unit inventories differ")
    units: list[AETRUnit] = []
    for unit_id in sorted(by_unit):
        events = tuple(sorted(by_unit[unit_id], key=lambda row: str(row["event_id"])))
        groups = {str(row["structure_group"]) for row in events}
        cohorts = {str(row["cohort"]) for row in events}
        if len(groups) != 1 or len(cohorts) != 1:
            raise ValueError(f"AETR unit crosses structure groups or cohorts: {unit_id}")
        signal = signal_shards[unit_id]
        audit = signal.get("audit")
        if not isinstance(audit, Mapping):
            raise TypeError(f"AETR source audit is malformed: {unit_id}")
        if audit.get("label_inputs") != []:
            raise ValueError(f"AETR source shard consumed labels: {unit_id}")
        inventory, features = workbook_feature_maps(audit)
        sources = {
            str(cell)
            for event in events
            if event["case_kind"] == "error"
            for cell in event["source_formula_cells"]
        }
        if not sources <= set(inventory):
            raise ValueError(f"AETR source label is absent from formula inventory: {unit_id}")
        group = next(iter(groups))
        units.append(AETRUnit(
            unit_id=unit_id,
            structure_group=group,
            fold=structure_fold(group),
            cohort=next(iter(cohorts)),
            events=events,
            audit=audit,
            inventory=inventory,
            features=features,
        ))
    return units


def training_examples(
    units: Sequence[AETRUnit],
    view_name: str,
) -> tuple[list[Mapping[str, float]], list[float], list[float], dict[str, object]]:
    view = AETR_VIEWS[view_name]
    eligible = [unit for unit in units if unit.sources]
    by_group: dict[str, list[AETRUnit]] = defaultdict(list)
    for unit in eligible:
        by_group[unit.structure_group].append(unit)
    if not by_group:
        raise ValueError("AETR training split has no error units")
    rows: list[Mapping[str, float]] = []
    targets: list[float] = []
    weights: list[float] = []
    if view.weighting == "formula_micro":
        for unit in eligible:
            for cell in unit.inventory:
                rows.append(unit.features[cell])
                targets.append(float(cell in unit.sources))
        constant = len(by_group) / len(rows)
        weights = [constant] * len(rows)
    else:
        for group in sorted(by_group):
            group_units = by_group[group]
            unit_weight = 1.0 / len(group_units)
            for unit in group_units:
                positives = [cell for cell in unit.inventory if cell in unit.sources]
                negatives = [cell for cell in unit.inventory if cell not in unit.sources]
                if not positives or not negatives:
                    raise ValueError(f"AETR unit cannot form both training classes: {unit.unit_id}")
                positive_weight = 0.5 * unit_weight / len(positives)
                negative_weight = 0.5 * unit_weight / len(negatives)
                for cell in positives:
                    rows.append(unit.features[cell])
                    targets.append(1.0)
                    weights.append(positive_weight)
                for cell in negatives:
                    rows.append(unit.features[cell])
                    targets.append(0.0)
                    weights.append(negative_weight)
    return rows, targets, weights, {
        "error_units": len(eligible),
        "structure_groups": len(by_group),
        "formula_rows": len(rows),
        "positive_rows": sum(target == 1.0 for target in targets),
        "negative_rows": sum(target == 0.0 for target in targets),
        "weight_sum": sum(weights),
        "weighting": view.weighting,
    }


def fit_view(units: Sequence[AETRUnit], view_name: str):
    rows, targets, weights, audit = training_examples(units, view_name)
    view = AETR_VIEWS[view_name]
    model = fit_ridge(
        rows,
        targets,
        weights,
        ridge_lambda=1.0,
        continuous_features=view.continuous,
        binary_features=view.discrete,
    )
    return model, audit


def predict_units(model, units: Sequence[AETRUnit]) -> dict[str, tuple[str, ...]]:
    output: dict[str, tuple[str, ...]] = {}
    for unit in units:
        ranking, _ = ranking_from_model(
            model, unit.audit, unit.inventory, unit.features,
        )
        if len(ranking) != len(unit.inventory) or set(ranking) != set(unit.inventory):
            raise ValueError(f"AETR prediction is not a complete ranking: {unit.unit_id}")
        output[unit.unit_id] = tuple(ranking)
    return output


def generate_crossfit(
    units: Sequence[AETRUnit],
    view_name: str,
) -> tuple[dict[str, tuple[str, ...]], list[dict[str, object]]]:
    predictions: dict[str, tuple[str, ...]] = {}
    folds: list[dict[str, object]] = []
    for outer_fold in range(5):
        train = [unit for unit in units if unit.fold != outer_fold]
        test = [unit for unit in units if unit.fold == outer_fold]
        train_groups = {unit.structure_group for unit in train}
        test_groups = {unit.structure_group for unit in test}
        if train_groups & test_groups:
            raise ValueError("AETR structure group crossed an outer fold")
        model, training_audit = fit_view(train, view_name)
        fold_predictions = predict_units(model, test)
        if set(predictions) & set(fold_predictions):
            raise ValueError("AETR unit received multiple outer predictions")
        predictions.update(fold_predictions)
        folds.append({
            "outer_fold": outer_fold,
            "training_folds": sorted({0, 1, 2, 3, 4} - {outer_fold}),
            "train_units": len(train),
            "test_units": len(test),
            "train_structure_groups": len(train_groups),
            "test_structure_groups": len(test_groups),
            "training_audit": training_audit,
            "model": model.to_dict(),
        })
    if set(predictions) != {unit.unit_id for unit in units}:
        raise ValueError("AETR outer predictions do not cover every unit")
    return predictions, folds


def generate_loco(
    units: Sequence[AETRUnit],
    cohort: str,
) -> tuple[dict[str, tuple[str, ...]], dict[str, object]]:
    test = [unit for unit in units if unit.cohort == cohort]
    test_groups = {unit.structure_group for unit in test}
    train = [
        unit for unit in units
        if unit.cohort != cohort and unit.structure_group not in test_groups
    ]
    train_groups = {unit.structure_group for unit in train}
    if not test or not train or train_groups & test_groups:
        raise ValueError(f"AETR leave-one-corpus split is invalid: {cohort}")
    model, training_audit = fit_view(train, "full")
    predictions = predict_units(model, test)
    return predictions, {
        "cohort": cohort,
        "train_units": len(train),
        "test_units": len(test),
        "train_structure_groups": len(train_groups),
        "test_structure_groups": len(test_groups),
        "training_audit": training_audit,
        "model": model.to_dict(),
    }


def _v4_rankings(v4: Mapping[str, Mapping[str, object]]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for unit_id, payload in v4.items():
        ranking = payload.get("ranking")
        if not isinstance(ranking, list):
            raise TypeError(f"AETR V4 comparison ranking is malformed: {unit_id}")
        cells = tuple(
            str(row["cell"]) for row in ranking if isinstance(row, Mapping)
        )
        if len(cells) != len(ranking) or len(cells) != len(set(cells)):
            raise ValueError(f"AETR V4 comparison ranking is incomplete: {unit_id}")
        result[unit_id] = cells
    return result


def event_rows(
    units: Sequence[AETRUnit],
    predictions: Mapping[str, Sequence[str]],
    v4_rankings: Mapping[str, Sequence[str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for unit in units:
        if unit.unit_id not in predictions or unit.unit_id not in v4_rankings:
            raise ValueError(f"AETR scoring inventory is incomplete: {unit.unit_id}")
        model_ranking = predictions[unit.unit_id]
        v4_ranking = v4_rankings[unit.unit_id]
        if set(model_ranking) != set(unit.inventory) or set(v4_ranking) != set(unit.inventory):
            raise ValueError(f"AETR/V4 formula inventory differs: {unit.unit_id}")
        for event in unit.events:
            sources = [str(cell) for cell in event["source_formula_cells"]]
            v4_source_rank = source_rank(v4_ranking, sources)
            model_source_rank = source_rank(model_ranking, sources)
            v4_top5 = int(v4_source_rank is not None and v4_source_rank <= 5)
            model_top5 = int(model_source_rank is not None and model_source_rank <= 5)
            rows.append({
                "event_id": str(event["event_id"]),
                "unit_id": unit.unit_id,
                "structure_group": unit.structure_group,
                "cohort": unit.cohort,
                "case_kind": str(event["case_kind"]),
                "outer_fold": unit.fold,
                "v4_source_rank": v4_source_rank,
                "controller_source_rank": model_source_rank,
                "v4_top5": v4_top5,
                "controller_top5": model_top5,
                "residual_delta": model_top5 - v4_top5,
                "acted": 0,
            })
    return sorted(rows, key=lambda row: str(row["event_id"]))


def _group_macro(rows: Sequence[Mapping[str, object]], field: str) -> float:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["case_kind"] == "error":
            groups[str(row["structure_group"])].append(float(row[field]))
    if not groups:
        raise ValueError(f"AETR cannot compute empty structure macro: {field}")
    return statistics.fmean(statistics.fmean(values) for values in groups.values())


def summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    summary = summarize_predictions(rows)
    errors = [row for row in rows if row["case_kind"] == "error"]
    summary["v4_top1"] = _group_macro(
        [dict(row, _top1=int(row["v4_source_rank"] == 1)) for row in errors],
        "_top1",
    )
    summary["model_top1"] = _group_macro(
        [dict(row, _top1=int(row["controller_source_rank"] == 1)) for row in errors],
        "_top1",
    )
    summary["top1_difference"] = summary["model_top1"] - summary["v4_top1"]
    return summary


def _bootstrap_delta(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_group: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["case_kind"] == "error":
            by_group[str(row["structure_group"])].append(float(row["residual_delta"]))
    group_deltas = [statistics.fmean(by_group[group]) for group in sorted(by_group)]
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


def _persisted_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    fields = (
        "event_id",
        "unit_id",
        "structure_group",
        "cohort",
        "case_kind",
        "outer_fold",
        "v4_source_rank",
        "controller_source_rank",
        "v4_top5",
        "controller_top5",
        "residual_delta",
    )
    return [{field: row[field] for field in fields} for row in rows]


def _raw_channel_predictions(
    units: Sequence[AETRUnit],
    channel: str,
) -> dict[str, tuple[str, ...]]:
    result = {}
    for unit in units:
        rankings = unit.audit.get("rankings")
        if not isinstance(rankings, Mapping) or not isinstance(rankings.get(channel), list):
            raise TypeError(f"AETR raw {channel} ranking is malformed: {unit.unit_id}")
        result[unit.unit_id] = tuple(str(cell) for cell in rankings[channel])
    return result


def _gates(
    full_summary: Mapping[str, object],
    folds: Sequence[Mapping[str, object]],
    bootstrap: Mapping[str, object],
    loco: Mapping[str, Mapping[str, object]],
) -> dict[str, bool]:
    cohorts = full_summary["by_cohort"]
    enron = cohorts["enron"]
    ci = bootstrap["ci95_delta_pp"]
    nonnegative_folds = sum(
        float(fold["test_summary"]["top5_difference"]) >= 0.0
        for fold in folds
    )
    loco_enron = loco["enron"]["summary"]
    loco_n2_deltas = [
        float(loco[name]["summary"]["top5_difference"])
        for name in N2_COHORTS
    ]
    return {
        "overall_top5_gain_at_least_5pp": float(full_summary["top5_difference"]) >= 0.05,
        "enron_top5_gain_at_least_5pp": float(enron["top5_difference"]) >= 0.05,
        "overall_mrr_nonnegative": float(full_summary["mrr_difference"]) >= 0.0,
        "enron_mrr_nonnegative": float(enron["mrr_difference"]) >= 0.0,
        "major_cohort_regressions_at_most_5pp": all(
            float(cohorts[name]["top5_difference"]) >= -0.05
            for name in MAJOR_COHORTS
        ),
        "at_least_four_nonnegative_outer_folds": nonnegative_folds >= 4,
        "structure_bootstrap_lower_bound_positive": float(ci[0]) > 0.0,
        "leave_enron_out_top5_nonnegative": float(loco_enron["top5_difference"]) >= 0.0,
        "leave_enron_out_mrr_nonnegative": float(loco_enron["mrr_difference"]) >= 0.0,
        "at_least_one_n2_loco_gain_at_least_5pp": max(loco_n2_deltas) >= 0.05,
        "all_n2_loco_regressions_at_most_5pp": min(loco_n2_deltas) >= -0.05,
    }


def run(
    *,
    profiles_path: Path,
    events_path: Path,
    signal_dir: Path,
    v4_dir: Path,
    preregistration_path: Path,
    output_dir: Path,
) -> Path:
    for path in (
        profiles_path,
        events_path,
        signal_dir,
        v4_dir,
        preregistration_path,
        output_dir,
    ):
        _reject_protected(path)
    _require_clean_tracked_worktree()
    if sha256(profiles_path) != EXPECTED_PROFILES_SHA256:
        raise ValueError("AETR profile hash differs from preregistration")
    if sha256(events_path) != EXPECTED_EVENTS_SHA256:
        raise ValueError("AETR event hash differs from preregistration")
    profiles = read_profiles(profiles_path)
    signals, signal_complete = _load_sources(signal_dir, profiles, kind="peer signals")
    if signal_complete.get("combined_shards_sha256") != EXPECTED_SIGNAL_SHARDS_SHA256:
        raise ValueError("AETR signal shards differ from preregistration")
    events = load_event_rows(events_path)
    units = build_units(events, signals)

    generated = {}
    for view_name in VIEW_ORDER:
        predictions, fold_artifacts = generate_crossfit(units, view_name)
        generated[view_name] = {
            "predictions": predictions,
            "fold_artifacts": fold_artifacts,
        }
    generated_loco = {
        cohort: generate_loco(units, cohort)
        for cohort in LOCO_COHORTS
    }

    v4, v4_complete = _load_sources(v4_dir, profiles, kind="V4")
    if v4_complete.get("combined_shards_sha256") != EXPECTED_V4_SHARDS_SHA256:
        raise ValueError("AETR V4 scoring shards differ from preregistration")
    v4_rankings = _v4_rankings(v4)

    view_results: dict[str, dict[str, object]] = {}
    for view_name in VIEW_ORDER:
        rows = event_rows(units, generated[view_name]["predictions"], v4_rankings)
        summary = summarize(rows)
        bootstrap = _bootstrap_delta(rows)
        folds = generated[view_name]["fold_artifacts"]
        for fold in folds:
            fold["test_summary"] = summarize([
                row for row in rows if row["outer_fold"] == fold["outer_fold"]
            ])
        view = AETR_VIEWS[view_name]
        view_results[view_name] = {
            "feature_contract": {
                "continuous": list(view.continuous),
                "discrete": list(view.discrete),
                "model_feature_count_with_missing_indicators": view.model_feature_count,
                "weighting": view.weighting,
                "ridge_lambda": 1.0,
                "v4_feature_inputs": [],
            },
            "fold_artifacts": folds,
            "summary": summary,
            "structure_group_bootstrap": bootstrap,
            "event_predictions": _persisted_rows(rows),
        }
    loco_results: dict[str, dict[str, object]] = {}
    for cohort in LOCO_COHORTS:
        predictions, artifact = generated_loco[cohort]
        test_units = [unit for unit in units if unit.cohort == cohort]
        rows = event_rows(test_units, predictions, v4_rankings)
        loco_results[cohort] = {
            "split": artifact,
            "summary": summarize(rows),
            "event_predictions": _persisted_rows(rows),
        }
    full = view_results["full"]
    gates = _gates(
        full["summary"],
        full["fold_artifacts"],
        full["structure_group_bootstrap"],
        loco_results,
    )
    full["public_gates"] = gates
    full["all_public_gates_passed"] = all(gates.values())

    baselines = {}
    for channel in ("peer", "combined", "role", "impact"):
        rows = event_rows(
            units,
            _raw_channel_predictions(units, channel),
            v4_rankings,
        )
        baselines[channel] = summarize(rows)

    source_hashes = {
        "profiles": EXPECTED_PROFILES_SHA256,
        "events": EXPECTED_EVENTS_SHA256,
        "signal_combined_shards": EXPECTED_SIGNAL_SHARDS_SHA256,
        "v4_combined_shards_scoring_only": EXPECTED_V4_SHARDS_SHA256,
        "preregistration": sha256(preregistration_path),
        "aetr": sha256(ROOT / "formulaguard/aetr.py"),
        "v4_rrc_ridge": sha256(ROOT / "formulaguard/v4_rrc.py"),
        "runner": sha256(Path(__file__)),
    }
    deterministic_projection = {
        "source_hashes": source_hashes,
        "view_results": view_results,
        "loco_results": loco_results,
        "baselines": baselines,
    }
    passed = bool(full["all_public_gates_passed"])
    payload = {
        "protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "inputs": {
            "profiles": _relative(profiles_path),
            "events": _relative(events_path),
            "signals": _relative(signal_dir),
            "v4_scoring_only": _relative(v4_dir),
            "preregistration": _relative(preregistration_path),
        },
        "counts": {
            "units": len(units),
            "events": len(events),
            "errors": sum(row["case_kind"] == "error" for row in events),
            "controls": sum(row["case_kind"] == "control" for row in events),
            "structure_groups": len({unit.structure_group for unit in units}),
            "formula_feature_maps": sum(len(unit.inventory) for unit in units),
        },
        "prediction_input_contract": {
            "signal_shards_only": True,
            "v4_feature_inputs": [],
            "label_fields_in_formula_features": [],
            "identity_features": [],
        },
        "source_hashes": source_hashes,
        "view_results": view_results,
        "leave_one_corpus_out": loco_results,
        "raw_channel_baselines": baselines,
        "decision": {
            "all_public_gates_passed": passed,
            "aetr_candidate_freeze_authorized": passed,
            "protected_240_120_access_authorized": False,
            "next_step": (
                "write_candidate_freeze_protocol"
                if passed
                else "stop_aetr_without_protected_access"
            ),
        },
        "deterministic_projection_sha256": stable_hash(deterministic_projection),
        "label_inputs": [_relative(events_path)],
        "protected_data_inputs": [],
    }
    if len(events) != EXPECTED_EVENTS:
        raise ValueError("AETR public event count differs from preregistration")
    if sum(row["case_kind"] == "error" for row in events) != EXPECTED_ERRORS:
        raise ValueError("AETR public error count differs from preregistration")
    if sum(row["case_kind"] == "control" for row in events) != EXPECTED_CONTROLS:
        raise ValueError("AETR public control count differs from preregistration")
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
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = run(
        profiles_path=args.profiles.resolve(),
        events_path=args.events.resolve(),
        signal_dir=args.signals.resolve(),
        v4_dir=args.v4.resolve(),
        preregistration_path=args.preregistration.resolve(),
        output_dir=args.output.resolve(),
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
