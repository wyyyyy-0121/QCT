"""Apply the predeclared V5.2 non-interference and safety gates to one round."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _reference_ranks(path: Path) -> dict[str, int]:
    rows = _read_csv(path)
    selected = [row for row in rows if row.get("method") == "formulaguard_v4"]
    return {row["instance_id"]: int(row["rank"]) for row in selected}


def _dataset_audit(raw: Path, reference: Path | None = None) -> dict[str, object]:
    rows = _read_csv(raw)
    ids = [row["instance_id"] for row in rows]
    duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
    core_hash_match = all(
        row["v4_order_sha256"] == row["v52_core_order_sha256"] for row in rows
    )
    rescue_cardinality = all(
        not row["rescue_cell"] or ";" not in row["rescue_cell"] for row in rows
    )
    traceable = all(
        not int(row["rescue_alarm"])
        or (
            row["rescue_cell"]
            and row["rescue_v4_rank"]
            and row["rescue_formula_rank"]
            and row["rescue_irg"]
            and row["rescue_delta"]
            and row["rescue_candidate_formula"]
        )
        for row in rows
    )
    reference_match = None
    reference_mismatches: list[dict[str, object]] = []
    if reference is not None:
        ranks = _reference_ranks(reference)
        for row in rows:
            expected = ranks.get(row["instance_id"])
            actual = int(row["core_rank"])
            if expected != actual:
                reference_mismatches.append({
                    "instance_id": row["instance_id"],
                    "expected_v4_rank": expected,
                    "actual_core_rank": actual,
                })
        reference_match = set(ids) == set(ranks) and not reference_mismatches
    return {
        "events": len(rows),
        "duplicate_instance_ids": duplicate_ids,
        "core_order_hashes_match": core_hash_match,
        "at_most_one_rescue_per_workbook_event": rescue_cardinality,
        "activated_rescues_are_traceable": traceable,
        "reference_v4_event_ranks_match": reference_match,
        "reference_mismatches": reference_mismatches,
        "rescue_activations": sum(int(row["rescue_alarm"]) for row in rows),
        "rescue_hits": sum(int(row["rescue_hit"]) for row in rows),
        "incremental_rescue_hits": sum(int(row["incremental_rescue_hit"]) for row in rows),
        "review6_hits": sum(int(row["review6_hit"]) for row in rows),
        "runtime_median": statistics.median(float(row["runtime_seconds"]) for row in rows),
    }


def _redteam_coverage(raw: Path) -> dict[str, object]:
    rows = _read_csv(raw)
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"core_top5": 0, "core_below5": 0})
    depths = set()
    for row in rows:
        error_type = row["error_type"]
        key = "core_top5" if int(row["core_rank"]) <= 5 else "core_below5"
        by_type[error_type][key] += 1
        # depth is encoded in the selected source instance id and retained in the manifest;
        # the raw evaluator does not use it for prediction, so read it from the companion manifest later.
    both_strata_each_type = all(
        counts["core_top5"] > 0 and counts["core_below5"] > 0
        for counts in by_type.values()
    ) and len(by_type) == 6
    return {
        "events": len(rows),
        "error_types": dict(sorted(by_type.items())),
        "six_error_types_present": len(by_type) == 6,
        "both_v4_rank_strata_each_type": both_strata_each_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit one complete V5.2 development round")
    parser.add_argument("--variant", choices=("a", "b", "c"), required=True)
    parser.add_argument("--synthetic-raw", type=Path, required=True)
    parser.add_argument("--synthetic-reference", type=Path, required=True)
    parser.add_argument("--enron-raw", type=Path, required=True)
    parser.add_argument("--enron-reference", type=Path, required=True)
    parser.add_argument("--redteam-raw", type=Path, required=True)
    parser.add_argument("--clean-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--record-only", action="store_true",
        help="Record failed research gates without treating them as an engineering crash",
    )
    args = parser.parse_args()

    synthetic = _dataset_audit(args.synthetic_raw, args.synthetic_reference)
    enron = _dataset_audit(args.enron_raw, args.enron_reference)
    redteam = _dataset_audit(args.redteam_raw)
    redteam_coverage = _redteam_coverage(args.redteam_raw)
    clean = json.loads(args.clean_summary.read_text(encoding="utf-8"))
    expected_counts = (
        synthetic["events"] == 18
        and enron["events"] == 30
        and redteam["events"] == 36
        and clean.get("clean_workbooks") == 48
    )
    dataset_checks = [synthetic, enron, redteam]
    dataset_readiness = {
        "expected_dataset_counts": expected_counts,
        "redteam_six_error_types": redteam_coverage["six_error_types_present"],
        "redteam_each_type_has_top5_and_below5": redteam_coverage["both_v4_rank_strata_each_type"],
    }
    model_hard_gates = {
        "core_order_hash_invariant": all(row["core_order_hashes_match"] for row in dataset_checks),
        "frozen_v4_event_ranks_unchanged": bool(
            synthetic["reference_v4_event_ranks_match"]
            and enron["reference_v4_event_ranks_match"]
        ),
        "at_most_one_rescue": all(row["at_most_one_rescue_per_workbook_event"] for row in dataset_checks),
        "rescue_traceability": all(row["activated_rescues_are_traceable"] for row in dataset_checks),
        "clean_rescue_rate_at_most_10_percent": bool(clean.get("gate_passed")),
    }
    dataset_ready = all(dataset_readiness.values())
    model_hard_gates_passed = all(model_hard_gates.values())
    round_passed = dataset_ready and model_hard_gates_passed
    report = {
        "protocol": "v5.2_three_round_non_interference_development",
        "variant": args.variant,
        "synthetic": synthetic,
        "enron": enron,
        "redteam": redteam,
        "redteam_coverage": redteam_coverage,
        "clean": clean,
        "dataset_readiness": dataset_readiness,
        "dataset_ready": dataset_ready,
        "model_hard_gates": model_hard_gates,
        "model_hard_gates_passed": model_hard_gates_passed,
        "hard_gates_passed": round_passed,
        "selection_metrics": {
            "combined_incremental_rescue_hits": sum(
                int(row["incremental_rescue_hits"]) for row in dataset_checks
            ),
            "clean_rescue_activation_rate": clean.get("rescue_activation_rate"),
            "combined_runtime_median_sum": sum(float(row["runtime_median"]) for row in dataset_checks),
        },
        "decision": (
            "eligible_for_three_round_comparison" if round_passed
            else "rerun_same_round_after_dataset_repair" if not dataset_ready
            else "round_rejected_by_model_hard_gate"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if not round_passed and not args.record_only:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
