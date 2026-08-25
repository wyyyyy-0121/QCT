"""Combine one preregistered V6 development round into an auditable receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", choices=("a", "b", "c"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    args = parser.parse_args()
    method = f"v6_{args.round}"
    development = load(args.root / "development/summary.json")
    redteam = load(args.root / "redteam/summary.json")
    clean = load(args.root / "clean/v6_clean_summary.json")
    enron = load(args.root / "enron/enron_summary.json")
    enron_completion = load(args.root / "enron/enron_prediction_complete.json")
    development_completion = load(args.root / "development/predictions/prediction_complete.json")
    redteam_completion = load(args.root / "redteam/predictions/prediction_complete.json")
    clean_completion = load(args.root / "clean/predictions/prediction_complete.json")
    development_quality = load("data/v6_development/validation/dataset_quality.json")
    redteam_quality = load("data/v6_redteam/validation/dataset_quality.json")
    clean_quality = load("data/v6_clean/validation/dataset_quality.json")
    leakage = load("data/v6_development/validation/leakage_audit.json")
    dev = development["summaries"][method]
    red = redteam["summaries"][method]
    clean_rate = clean["variants"][method]["false_alarm_rate"]
    gates = {
        "development_predictions_complete": development["events"] == 1200,
        "redteam_predictions_complete": redteam["events"] == 360,
        "all_full_ranking_audits_passed": all(
            item.get("full_ranking_audit_passed")
            for item in (development_completion, redteam_completion, clean_completion, enron_completion)
        ),
        "all_dataset_quality_gates_passed": all(
            item.get("hard_gate_passed") for item in (development_quality, redteam_quality, clean_quality)
        ),
        "cross_split_leakage_audit_passed": leakage.get("cross_split_passed", False),
        "traceability_complete": development["traceability_complete"] and redteam["traceability_complete"],
        "candidate_coverage_at_25_at_least_95_percent": dev["candidate_coverage_at_25"] >= 0.95,
        "clean_false_alarm_at_most_10_percent": clean_rate <= 0.10,
        "enron_inventory_30_events": (
            enron_completion.get("events") == 30
            and enron["summary"]["v4"]["events"] == 30
            and enron["summary"][method]["events"] == 30
        ),
        "enron_mrr_not_below_v4": enron["v6_mrr_not_below_v4"],
        "worker_policy_24": args.workers == 24,
    }
    payload = {
        "protocol": "v6_preregistered_development_round",
        "round": args.round,
        "single_mechanism": {"a": "FFC", "b": "FFC+BSS", "c": "FFC+BSS+safety"}[args.round],
        "workers": args.workers,
        "development": dev,
        "redteam": red,
        "clean_false_alarm_rate": clean_rate,
        "enron": enron["summary"],
        "gates": gates,
        "round_passed": all(gates.values()),
        "selection_forbidden_until_all_rounds_complete": True,
    }
    output = args.root / "v6_round_audit.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log = Path("research/V6_DEVELOPMENT_LOG.md")
    existing = log.read_text(encoding="utf-8") if log.exists() else "# V6 开发日志\n\n"
    marker = f"## V6-{args.round.upper()}"
    block = (
        f"{marker}\n\n- 机制：{payload['single_mechanism']}\n- 进程：{args.workers}\n"
        f"- 开发集：1,200；红队：360；干净表：240；Enron：{enron['summary']['v4']['events']}\n"
        f"- 开发宏 Top-5：{dev['macro_top5']:.4f}；MRR：{dev['mrr']:.4f}\n"
        f"- 红队宏 Top-5：{red['macro_top5']:.4f}；干净误报：{clean_rate:.4f}\n"
        f"- 本轮门槛：{'通过' if payload['round_passed'] else '未通过'}\n\n"
    )
    if marker not in existing:
        log.write_text(existing + block, encoding="utf-8")
    print(output)
    if not payload["round_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
