"""Combine two revealed-data R2 pressure cohorts into an auditable safety receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-100", type=Path, required=True)
    parser.add_argument("--enron", type=Path, required=True)
    parser.add_argument("--development-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--method-label", default="R2-R1",
        help="Human-readable model label stored in the retrospective receipt.",
    )
    parser.add_argument(
        "--protocol", default="v5_core_r2_r1_pressure_safety_decision_v1",
        help="Versioned receipt protocol; historical R2-R1 remains the default.",
    )
    args = parser.parse_args()

    historical = load(args.historical_100)
    enron = load(args.enron)
    development = load(args.development_audit)
    for name, payload, expected in (
        ("historical_100", historical, 100), ("enron", enron, 30),
    ):
        if payload.get("protocol") != "v5_core_r2_revealed_retrospective_pressure_v1":
            raise SystemExit(f"Unexpected pressure protocol for {name}")
        if not payload.get("retrospective_only") or not payload.get("not_for_model_selection"):
            raise SystemExit(f"Retrospective disclosure is missing for {name}")
        if int(payload.get("events", -1)) != expected:
            raise SystemExit(f"{name} must contain exactly {expected} events")
        checks = payload.get("quality_checks", {})
        if not all(checks.get(key) for key in ("unique_instance_ids", "all_workbooks_present", "complete_rankings")):
            raise SystemExit(f"Data-quality checks failed for {name}")
        if int(checks.get("raw_rows", -1)) != expected * 3:
            raise SystemExit(f"Unexpected event-method grain for {name}")
    if int(enron.get("input_events", -1)) != 36:
        raise SystemExit("Enron pressure input must preserve all 36 inventory records")
    if int(enron.get("excluded_inventory_events", -1)) != 6:
        raise SystemExit("Enron pressure input must record exactly six excluded inventory events")

    cohorts = {"historical_100": historical, "enron": enron}
    gates: dict[str, bool] = {
        "development_source_macro_top5_at_least_0_90":
            development["error_metrics"]["r2_source"]["macro_top5"] >= 0.90,
        "development_source_weakest_top5_at_least_0_75":
            development["error_metrics"]["r2_source"]["weakest_top5"] >= 0.75,
    }
    cohort_metrics: dict[str, dict] = {}
    for name, payload in cohorts.items():
        summary = payload["summary"]
        full_vs_source = payload["paired_full_vs_source"]
        cohort_metrics[name] = {
            "v4": summary["v4"],
            "r2_source": summary["r2_source"],
            "r2_full": summary["r2_full"],
            "full_vs_source": full_vs_source,
        }
        gates[f"{name}_r2_full_mrr_not_below_v4_by_more_than_0_01"] = (
            summary["r2_full"]["mrr"] + 0.01 >= summary["v4"]["mrr"]
        )
        gates[f"{name}_r2_full_top5_not_below_v4_by_more_than_0_05"] = (
            summary["r2_full"]["top5"] + 0.05 >= summary["v4"]["top5"]
        )
        gates[f"{name}_dcf_harmed_rate_at_most_0_02"] = full_vs_source["harmed_rate"] <= 0.02

    passed = all(gates.values())
    cohort_provenance = {
        name: {
            "git_commit": payload.get("git_commit"),
            "runner_source_sha256": payload.get("runner_source_sha256"),
            "model_source_sha256": payload.get("model_source_sha256"),
            "events_sha256": payload.get("events_sha256"),
            "input_events": payload.get("input_events", payload.get("events")),
            "evaluated_events": payload.get("events"),
            "excluded_inventory_events": payload.get("excluded_inventory_events", 0),
        }
        for name, payload in cohorts.items()
    }
    runner_hashes_equal = (
        cohort_provenance["historical_100"]["runner_source_sha256"]
        == cohort_provenance["enron"]["runner_source_sha256"]
    )
    receipt = {
        "protocol": args.protocol,
        "method_label": args.method_label,
        "development_only": True,
        "independent_evidence": False,
        "original_preregistered_development_gate_passed": bool(
            development.get("gates", {}).get("hard_gate_passed", False)
        ),
        "original_failed_gates_preserved": development.get("gates", {}).get("failed_gates", []),
        "cohorts": cohort_metrics,
        "gates": gates,
        "pressure_safety_passed": passed,
        "eligible_for_new_independent_confirmation": passed,
        "cohort_execution_provenance": cohort_provenance,
        "runner_source_hashes_equal": runner_hashes_equal,
        "runner_difference_disclosure": (
            "Both cohorts used the same pressure-runner source."
            if runner_hashes_equal else
            "The completed historical-100 receipt is reused from the pre-adapter runner. "
            "The later runner change only filters an explicit include field, which the "
            "historical cohort does not contain; Enron preserves all 36 inventory rows "
            "while evaluating the 30 admitted formula events and recording six exclusions."
        ),
        "interpretation": (
            f"Safety pressure passed; {args.method_label} may be frozen for a genuinely new independent confirmation set."
            if passed else
            f"Safety pressure failed; {args.method_label} must remain a development mechanism and cannot be promoted."
        ),
        "hashes": {
            "historical_100_summary": sha256(args.historical_100),
            "enron_summary": sha256(args.enron),
            "development_audit": sha256(args.development_audit),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    print(f"{args.method_label} pressure safety passed: {passed}")
    if not passed:
        print("Failed gates: " + ", ".join(name for name, value in gates.items() if not value))


if __name__ == "__main__":
    main()
