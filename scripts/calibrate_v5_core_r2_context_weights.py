"""Grouped, finite calibration of R2 observational weights.

This is a label-aware development utility.  It reuses already materialized
candidate-independent evidence and never presents its output as independent
evaluation.  Profiles are finite and template families are kept intact across
folds so one attractive workbook cannot determine the weights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


PROFILES = {
    "current_55_20_25": (0.55, 0.20, 0.25),
    "dual_50_30_20": (0.50, 0.30, 0.20),
    "structural_60_30_10": (0.60, 0.30, 0.10),
    "balanced_50_25_25": (0.50, 0.25, 0.25),
    "propagation_45_20_35": (0.45, 0.20, 0.35),
}
FUSION_WEIGHTS = (0.0, 0.25, 0.40, 0.50, 0.60)
FUSION_K = 10.0


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_cell(value: str) -> str:
    sheet, address = value.rsplit("!", 1)
    return f"{sheet.strip(chr(39))}!{address.replace('$', '').upper()}"


def fold_for(group: str, folds: int) -> int:
    return int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) % folds


def rescore(
    rows: list[dict],
    weights: tuple[float, float, float],
    *,
    fusion_weight: float = 0.0,
) -> list[str]:
    primary, secondary, propagation_weight = weights
    by_cell = {str(row["cell"]): row for row in rows}
    scores: dict[str, float] = {}
    for cell, row in by_cell.items():
        ev = row["evidence"]
        structural = 0.80 * float(ev["regime_conditioned_residual"]) + 0.20 * float(ev["formula_residual"])
        signals = sorted((structural, float(ev["behavior_residual"]), float(ev["graph_residual"])), reverse=True)
        base = primary * signals[0] + secondary * signals[1] + propagation_weight * float(ev["propagation_potential"])
        scores[cell] = max(0.0, min(1.0, base * (1.0 - 0.75 * float(ev["ancestor_penalty"]))))
    tails: dict[str, float] = {}
    for cell, row in by_cell.items():
        controls = [label for label in row["evidence"].get("observational_controls", []) if label in scores]
        tails[cell] = (1 + sum(scores[item] >= scores[cell] for item in controls)) / (1 + len(controls))
    stable = {str(row["cell"]): index for index, row in enumerate(rows)}
    baseline = sorted(by_cell, key=lambda cell: (tails[cell], -scores[cell], stable[cell]))
    if fusion_weight == 0.0 or len(baseline) <= 1:
        return baseline
    formula = {cell: float(by_cell[cell]["evidence"]["formula_residual"]) for cell in baseline}
    fused = {}
    for cell in baseline:
        obs_rank = 1 + sum(
            tails[other] < tails[cell]
            or (tails[other] == tails[cell] and scores[other] > scores[cell])
            for other in baseline
        )
        formula_rank = 1 + sum(formula[other] > formula[cell] for other in baseline)
        fused[cell] = (
            (1.0 - fusion_weight) / (FUSION_K + obs_rank)
            + fusion_weight / (FUSION_K + formula_rank)
        )
    base_rank = {cell: index for index, cell in enumerate(baseline)}
    return sorted(baseline, key=lambda cell: (-fused[cell], base_rank[cell]))


def metrics(records: list[dict]) -> dict:
    if not records:
        return {"events": 0, "top5": 0.0, "mrr": 0.0, "macro_top5": 0.0, "weakest_top5": 0.0}
    by_type: dict[str, list[int]] = defaultdict(list)
    for row in records:
        by_type[row["mutation_type"]].append(row["rank"])
    type_top5 = {key: sum(rank <= 5 for rank in ranks) / len(ranks) for key, ranks in by_type.items()}
    return {
        "events": len(records),
        "top5": sum(row["rank"] <= 5 for row in records) / len(records),
        "mrr": sum(1.0 / row["rank"] for row in records) / len(records),
        "macro_top5": sum(type_top5.values()) / len(type_top5),
        "weakest_top5": min(type_top5.values()),
        "by_type_top5": type_top5,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", type=Path, required=True)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    instances = {row["instance_id"]: row for row in read_jsonl(args.instances)}
    labels = {row["instance_id"]: row for row in read_jsonl(args.labels)}
    candidates = {
        f"{name}__rrf_{fusion:.2f}": (weights, fusion)
        for name, weights in PROFILES.items()
        for fusion in FUSION_WEIGHTS
    }
    profile_records: dict[str, list[dict]] = {name: [] for name in candidates}
    for instance_id, instance in instances.items():
        payload = json.loads((args.shards / f"{instance_id}.json").read_text(encoding="utf-8"))
        rows = payload["rankings"]["r2_source"]
        source = normalize_cell(labels[instance_id]["source_cell"])
        for name, (weights, fusion_weight) in candidates.items():
            ranking = rescore(rows, weights, fusion_weight=fusion_weight)
            rank = ranking.index(source) + 1
            profile_records[name].append({
                "instance_id": instance_id,
                "template_family": instance["template_family"],
                "fold": fold_for(instance["template_family"], args.folds),
                "mutation_type": labels[instance_id]["mutation_type"],
                "rank": rank,
            })

    report_profiles: dict[str, dict] = {}
    for name, records in profile_records.items():
        weights, fusion_weight = candidates[name]
        fold_metrics = {
            str(fold): metrics([row for row in records if row["fold"] == fold])
            for fold in range(args.folds)
        }
        overall = metrics(records)
        report_profiles[name] = {
            "weights": {
                "strongest_evidence": weights[0],
                "second_evidence": weights[1],
                "propagation": weights[2],
                "formula_rrf": fusion_weight,
                "rrf_k": FUSION_K,
            },
            "overall": overall,
            "folds": fold_metrics,
            "minimum_fold_macro_top5": min(row["macro_top5"] for row in fold_metrics.values()),
            "minimum_fold_mrr": min(row["mrr"] for row in fold_metrics.values()),
        }
    simplicity = {name: index for index, name in enumerate(candidates)}
    selected = max(report_profiles, key=lambda name: (
        report_profiles[name]["minimum_fold_macro_top5"],
        report_profiles[name]["overall"]["macro_top5"],
        report_profiles[name]["minimum_fold_mrr"],
        report_profiles[name]["overall"]["mrr"],
        -simplicity[name],
    ))
    fold_winners = Counter()
    for fold in range(args.folds):
        winner = max(candidates, key=lambda name: (
            report_profiles[name]["folds"][str(fold)]["macro_top5"],
            report_profiles[name]["folds"][str(fold)]["weakest_top5"],
            report_profiles[name]["folds"][str(fold)]["mrr"],
            -simplicity[name],
        ))
        fold_winners[winner] += 1
    report = {
        "protocol": "v5_core_r2_r2_finite_grouped_weight_calibration_v1",
        "development_only": True,
        "independent_evidence": False,
        "label_aware": True,
        "selection_unit": "template_family",
        "folds": args.folds,
        "profiles": report_profiles,
        "selected_profile": selected,
        "fold_winner_counts": dict(fold_winners),
        "selection_rule": [
            "maximum worst-fold macro Top-5",
            "maximum overall macro Top-5",
            "maximum worst-fold MRR",
            "maximum overall MRR",
            "simpler preregistered profile",
        ],
        "interpretation": "Weights are eligible only for a new development revision and require full pressure rerun.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "weight_calibration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(args.output / "weight_calibration.json")
    print(json.dumps({
        "selected_profile": selected,
        "selected_metrics": report_profiles[selected]["overall"],
        "fold_winner_counts": dict(fold_winners),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
