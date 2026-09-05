"""Consolidate V5-Core development, red-team, clean, training, and Enron evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABLATIONS = (
    "no_regime", "no_exception", "no_structure", "no_causal",
    "no_graph", "no_replication", "no_harm", "weighted_sum",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/v5_core_development"))
    parser.add_argument("--dataset-audit", type=Path, default=Path("results/v5_core_dataset_audit.json"))
    args = parser.parse_args()
    development = json.loads((args.root / "development/summary.json").read_text(encoding="utf-8"))
    redteam = json.loads((args.root / "redteam/summary.json").read_text(encoding="utf-8"))
    training = json.loads((args.root / "config/training_audit.json").read_text(encoding="utf-8"))
    enron = json.loads((args.root / "enron/enron_summary.json").read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset_audit.read_text(encoding="utf-8"))
    reasons = []
    if not dataset.get("hard_gate_passed"):
        reasons.append("dataset audit failed")
    if not training.get("positive_weight_constraints_passed") or not training.get("negative_weight_constraints_passed"):
        reasons.append("learned weight sign constraint failed")
    if not training.get("major_feature_directions_consistent"):
        reasons.append("learned feature directions are not stable")
    if training.get("held_out_family_success_fraction", 0.0) < 0.75:
        reasons.append("learned head does not generalize across 75% of template families")
    if training.get("worst_held_out_family_pair_accuracy", 0.0) < 0.25:
        reasons.append("learned head collapses on a held-out template family")
    if training.get("source_code_hash") != hashlib.sha256(
        (ROOT / "formulaguard/v5_core.py").read_bytes()
    ).hexdigest():
        reasons.append("training source hash differs from current V5-Core")
    for method in ("v5_rule", "v5_learned"):
        metrics = development["summary"].get(method, {})
        if metrics.get("candidate_coverage_32", 0.0) < 0.95:
            reasons.append(f"{method} candidate coverage below 95%")
        if development.get("clean", {}).get(method, {}).get("false_alarm_rate", 1.0) > 0.10:
            reasons.append(f"{method} clean false alarm above 10%")
        if development.get("clean", {}).get(method, {}).get("legitimate_exception_false_alarm_rate", 1.0) > 0.15:
            reasons.append(f"{method} legitimate-exception false alarm above 15%")
        full_macro = metrics.get("macro_top5", 0.0)
        for ablation in ABLATIONS:
            ablated = development["summary"].get(f"{method}_ablation_{ablation}")
            if not ablated:
                reasons.append(f"missing matched {method} {ablation} ablation")
            elif ablated.get("macro_top5", 0.0) > full_macro + 0.02:
                reasons.append(f"{method} {ablation} ablation exceeds full model by >0.02")
        redteam_metrics = redteam["summary"].get(method, {})
        if redteam_metrics.get("candidate_coverage_32", 0.0) < 0.95:
            reasons.append(f"{method} red-team candidate coverage below 95%")
    if not enron.get("rule_mrr_not_below_v4_by_more_than_001"):
        reasons.append("rule Enron safety gate failed")
    if not enron.get("learned_mrr_not_below_v4_by_more_than_001"):
        reasons.append("learned Enron safety gate failed")
    payload = {
        "protocol": "v5_core_development_audit_v1",
        "development": development,
        "redteam": redteam,
        "training": training,
        "enron": enron,
        "hard_gate_passed": not reasons,
        "reasons": reasons,
        "locked_validation_labels_seen": False,
        "third_party_labels_seen": False,
    }
    output = args.root / "development_audit.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    if reasons:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
