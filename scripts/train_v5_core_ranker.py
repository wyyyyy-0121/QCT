"""Train and calibrate the transparent V5-Core learned head on development data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_core import (
    FEATURE_NAMES,
    _learned_score,
    fit_pairwise_linear_ranker,
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = shutil.which("git") or str(bundled)
    return subprocess.check_output([executable, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def load_shards(path: Path) -> dict[str, dict]:
    completion = path / "prediction_complete.json"
    if not completion.exists():
        raise SystemExit(f"Predictions are not complete: {path}")
    return {
        shard.stem: json.loads(shard.read_text(encoding="utf-8"))
        for shard in sorted((path / "shards").glob("*.json"))
    }


def assign_template_folds(template_families) -> dict[str, int]:
    """Assign whole template families to five exactly balanced folds."""
    ordered = sorted(set(template_families))
    return {family: index % 5 for index, family in enumerate(ordered)}


def source_features(shard: dict, source_cell: str) -> tuple[dict[str, float], list[dict[str, float]]]:
    ranking = shard["rankings"]["v5_rule"]
    source = next((row for row in ranking if row["cell"] == source_cell), None)
    if source is None:
        raise ValueError(f"Source cell {source_cell} missing from {shard['instance_id']}")
    positive = {name: float(source["evidence"]["feature_vector"].get(name, 0.0)) for name in FEATURE_NAMES}
    negatives = []
    for row in ranking:
        if row["cell"] == source_cell:
            continue
        negatives.append({
            name: float(row["evidence"]["feature_vector"].get(name, 0.0))
            for name in FEATURE_NAMES
        })
        if len(negatives) >= 20:
            break
    return positive, negatives


def pair_accuracy(config: dict, pairs) -> float:
    if not pairs:
        return 0.0
    return sum(
        _learned_score(positive, config) > _learned_score(negative, config)
        for positive, negative in pairs
    ) / len(pairs)


def _quantile_grid(values: list[float], points: int = 31) -> list[float]:
    if not values:
        return [0.0]
    ordered = sorted(values)
    indexes = {round(index * (len(ordered) - 1) / max(1, points - 1)) for index in range(points)}
    return sorted({ordered[index] for index in indexes})


def calibrate(error_pairs: list[tuple[float, float]], clean_pairs: list[tuple[float, float]]) -> dict:
    thresholds = _quantile_grid([top for top, _ in error_pairs + clean_pairs])
    margins = _quantile_grid([margin for _, margin in error_pairs + clean_pairs], 21)
    eligible = []
    for threshold in thresholds:
        for margin in margins:
            clean_fpr = sum(top >= threshold and gap >= margin for top, gap in clean_pairs) / max(1, len(clean_pairs))
            if clean_fpr > 0.10 + 1e-12:
                continue
            recall = sum(top >= threshold and gap >= margin for top, gap in error_pairs) / max(1, len(error_pairs))
            eligible.append((recall, threshold, margin, clean_fpr))
    if not eligible:
        return {"alarm_threshold": math.inf, "alarm_margin": math.inf, "development_recall": 0.0, "clean_fpr": 0.0}
    recall, threshold, margin, fpr = max(eligible, key=lambda row: (row[0], row[1], row[2], -row[3]))
    return {
        "alarm_threshold": threshold,
        "alarm_margin": margin,
        "development_recall": recall,
        "clean_fpr": fpr,
    }


def ranking_top_margin(ranking: list[dict], *, learned_config: dict | None = None) -> tuple[float, float]:
    if learned_config is None:
        scores = sorted((float(row["score"]) for row in ranking), reverse=True)
    else:
        scores = []
        for row in ranking:
            evaluated = row["evidence"].get("evaluated_candidate_features", [])
            candidate_scores = [
                _learned_score(candidate["feature_vector"], learned_config)
                for candidate in evaluated
            ]
            scores.append(max(candidate_scores, default=_learned_score(
                row["evidence"]["feature_vector"], learned_config,
            )))
        scores.sort(reverse=True)
    top = scores[0] if scores else 0.0
    second = scores[1] if len(scores) > 1 else 0.0
    return top, top - second


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--clean-predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = {row["instance_id"]: row for row in read_jsonl(args.benchmark / "instances.jsonl")}
    labels = {row["instance_id"]: row for row in read_jsonl(args.benchmark / "evaluation_labels.jsonl")}
    shards = load_shards(args.predictions)
    clean_shards = load_shards(args.clean_predictions)
    if set(rows) != set(labels) or set(rows) != set(shards):
        raise SystemExit("Development manifests, labels, and predictions do not match")

    family_folds = assign_template_folds(
        row["template_family"] for row in rows.values()
    )
    grouped_pairs: dict[int, list[tuple[dict[str, float], dict[str, float]]]] = {fold: [] for fold in range(5)}
    family_pairs: dict[str, list[tuple[dict[str, float], dict[str, float]]]] = {}
    for instance_id, shard in shards.items():
        positive, negatives = source_features(shard, labels[instance_id]["source_cell"])
        family = rows[instance_id]["template_family"]
        pairs = [(positive, negative) for negative in negatives]
        fold = family_folds[family]
        grouped_pairs[fold].extend(pairs)
        family_pairs.setdefault(family, []).extend(pairs)

    cv_rows = []
    cv_models: dict[float, list[dict]] = {}
    for regularization in (0.01, 0.1, 1.0):
        fold_scores = []
        fold_weights = []
        fold_configs = []
        for held_out in range(5):
            training = [pair for fold, pairs in grouped_pairs.items() if fold != held_out for pair in pairs]
            validation = grouped_pairs[held_out]
            config = fit_pairwise_linear_ranker(training, regularization=regularization)
            fold_scores.append(pair_accuracy(config, validation))
            fold_weights.append(config["feature_weights"])
            fold_configs.append(config)
        cv_models[regularization] = fold_configs
        cv_rows.append({
            "regularization": regularization,
            "fold_pair_accuracy": fold_scores,
            "mean_pair_accuracy": statistics.fmean(fold_scores),
            "fold_weights": fold_weights,
        })
    selected = max(cv_rows, key=lambda row: (row["mean_pair_accuracy"], -row["regularization"]))
    all_pairs = [pair for pairs in grouped_pairs.values() for pair in pairs]
    learned = fit_pairwise_linear_ranker(all_pairs, regularization=float(selected["regularization"]))
    learned["cross_validation"] = cv_rows
    learned["cross_validation_results"] = cv_rows
    learned["selected_by"] = "five_fold_template_group_pair_accuracy"
    selected_fold_configs = cv_models[float(selected["regularization"])]
    held_out_family_accuracy = {
        family: pair_accuracy(selected_fold_configs[family_folds[family]], pairs)
        for family, pairs in sorted(family_pairs.items())
    }
    major_features = [
        name for name, value in learned["feature_weights"].items()
        if abs(float(value)) >= 1e-3
    ]
    selected_fold_weights = selected["fold_weights"]
    direction_consistency = {
        name: sum(
            abs(float(weights[name])) >= 1e-9
            for weights in selected_fold_weights
        ) / len(selected_fold_weights)
        for name in major_features
    }
    learned["held_out_family_pair_accuracy"] = held_out_family_accuracy
    learned["major_feature_direction_consistency"] = direction_consistency
    learned["major_feature_directions_consistent"] = all(
        ratio >= 0.80 for ratio in direction_consistency.values()
    )
    learned["families_above_chance"] = sum(
        score > 0.50 for score in held_out_family_accuracy.values()
    )
    learned["held_out_families"] = len(held_out_family_accuracy)
    learned["held_out_family_success_fraction"] = (
        learned["families_above_chance"] / max(1, learned["held_out_families"])
    )
    learned["worst_held_out_family_pair_accuracy"] = min(
        held_out_family_accuracy.values(), default=0.0,
    )

    error_rule = [ranking_top_margin(shard["rankings"]["v5_rule"]) for shard in shards.values()]
    clean_rule = [ranking_top_margin(shard["rankings"]["v5_rule"]) for shard in clean_shards.values()]
    error_learned = [ranking_top_margin(shard["rankings"]["v5_rule"], learned_config=learned) for shard in shards.values()]
    clean_learned = [ranking_top_margin(shard["rankings"]["v5_rule"], learned_config=learned) for shard in clean_shards.values()]
    rule_config = {
        "model_version": "v5-core-dev-r2",
        "head": "rule",
        **calibrate(error_rule, clean_rule),
        "training_manifest": str((args.benchmark / "instances.jsonl").resolve()),
        "random_seed": 20260827,
    }
    learned.update(calibrate(error_learned, clean_learned))
    learned["training_manifest"] = str((args.benchmark / "instances.jsonl").resolve())
    learned["training_manifest_hash"] = sha256(args.benchmark / "instances.jsonl")
    learned["source_code_hash"] = sha256(ROOT / "formulaguard/v5_core.py")
    learned["git_commit"] = git_commit()
    learned["feature_scaler"] = {
        "center": learned["feature_center"],
        "scale": learned["feature_scale"],
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "v5_core_rule_config.json").write_text(
        json.dumps(rule_config, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (args.output / "v5_core_learned_config.json").write_text(
        json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    audit = {
        "protocol": "v5_core_transparent_pairwise_training_v1",
        "development_instances": len(shards),
        "clean_instances": len(clean_shards),
        "training_pairs": len(all_pairs),
        "template_group_folds": 5,
        "template_families_per_fold": {
            str(fold): sum(assigned == fold for assigned in family_folds.values())
            for fold in range(5)
        },
        "regularizations_tested": [0.01, 0.1, 1.0],
        "selected_regularization": selected["regularization"],
        "cross_validation": cv_rows,
        "held_out_family_pair_accuracy": held_out_family_accuracy,
        "major_feature_direction_consistency": direction_consistency,
        "major_feature_directions_consistent": learned["major_feature_directions_consistent"],
        "held_out_family_success_fraction": learned["held_out_family_success_fraction"],
        "worst_held_out_family_pair_accuracy": learned["worst_held_out_family_pair_accuracy"],
        "feature_names": list(FEATURE_NAMES),
        "feature_weights": learned["feature_weights"],
        "feature_scaler": {
            "center": learned["feature_center"],
            "scale": learned["feature_scale"],
        },
        "training_manifest_hash": learned["training_manifest_hash"],
        "source_code_hash": learned["source_code_hash"],
        "git_commit": learned["git_commit"],
        "positive_weight_constraints_passed": all(
            value >= 0 for name, value in learned["feature_weights"].items()
            if name not in {"exception_likelihood", "global_harm"}
        ),
        "negative_weight_constraints_passed": all(
            learned["feature_weights"][name] <= 0
            for name in ("exception_likelihood", "global_harm")
        ),
        "rule_calibration": rule_config,
        "learned_calibration": {
            key: learned[key] for key in ("alarm_threshold", "alarm_margin", "development_recall", "clean_fpr")
        },
    }
    audit_path = args.output / "training_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(audit_path)


if __name__ == "__main__":
    main()
