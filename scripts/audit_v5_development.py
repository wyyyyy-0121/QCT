"""Apply the preregistered V5 synthetic, Enron, and clean-control gates."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_external_results import bootstrap_mean_difference


METHODS = (
    "graph", "pattern", "formulaguard", "formulaguard_v3", "formulaguard_v4",
    "formulaguard_v5",
)
REFERENCE_METHODS = METHODS[:-1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def matrix_audit(rows: list[dict[str, str]], expected_events: int) -> dict[str, object]:
    keys = [(row["instance_id"], row["method"]) for row in rows]
    instances = sorted({key[0] for key in keys})
    expected = {(instance, method) for instance in instances for method in METHODS}
    actual = set(keys)
    return {
        "events": len(instances),
        "rows": len(rows),
        "expected_rows": expected_events * len(METHODS),
        "duplicate_keys": len(keys) - len(actual),
        "missing_keys": [list(key) for key in sorted(expected - actual)],
        "unexpected_keys": [list(key) for key in sorted(actual - expected)],
        "passed": (
            len(instances) == expected_events
            and len(rows) == expected_events * len(METHODS)
            and len(keys) == len(actual)
            and not (expected - actual)
            and not (actual - expected)
        ),
    }


def reference_rank_changes(
    rows: list[dict[str, str]], reference_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    current = {
        (row["instance_id"], row["method"]): int(float(row["rank"]))
        for row in rows if row["method"] in REFERENCE_METHODS
    }
    reference = {
        (row["instance_id"], row["method"]): int(float(row["rank"]))
        for row in reference_rows if row["method"] in REFERENCE_METHODS
    }
    changes = []
    for key in sorted(set(current) | set(reference)):
        if current.get(key) != reference.get(key):
            changes.append({
                "instance_id": key[0], "method": key[1],
                "current_rank": current.get(key), "reference_rank": reference.get(key),
            })
    return changes


def method_summary(rows: list[dict[str, str]], method: str) -> dict[str, float]:
    group = [row for row in rows if row["method"] == method]
    return {
        "events": len(group),
        "top1": statistics.fmean(float(row["top1"]) for row in group),
        "top3": statistics.fmean(float(row["top3"]) for row in group),
        "top5": statistics.fmean(float(row["top5"]) for row in group),
        "mrr": statistics.fmean(float(row["mrr"]) for row in group),
        "exam": statistics.fmean(float(row["exam"]) for row in group),
    }


def paired_mrr(rows: list[dict[str, str]], left: str, right: str) -> dict[str, object]:
    by_instance: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_instance[row["instance_id"]][row["method"]] = row
    values = [
        float(methods[left]["mrr"]) - float(methods[right]["mrr"])
        for methods in by_instance.values()
        if left in methods and right in methods
    ]
    return {
        "events": len(values),
        "mean_mrr_difference": statistics.fmean(values) if values else None,
        "bootstrap_95_ci": bootstrap_mean_difference(values),
        "better_events": sum(value > 0 for value in values),
        "equal_events": sum(value == 0 for value in values),
        "worse_events": sum(value < 0 for value in values),
        "identity": "development_comparison_not_confirmatory",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the single V5 development run")
    parser.add_argument("--synthetic-raw", type=Path, required=True)
    parser.add_argument("--synthetic-reference", type=Path, required=True)
    parser.add_argument("--enron-raw", type=Path, required=True)
    parser.add_argument("--enron-reference", type=Path, required=True)
    parser.add_argument("--clean-summary", type=Path, required=True)
    parser.add_argument("--prerequisite-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    synthetic = read_csv(args.synthetic_raw)
    enron = read_csv(args.enron_raw)
    synthetic_reference = read_csv(args.synthetic_reference)
    enron_reference = read_csv(args.enron_reference)
    clean = json.loads(args.clean_summary.read_text(encoding="utf-8"))
    prerequisite = json.loads(args.prerequisite_audit.read_text(encoding="utf-8"))
    synthetic_matrix = matrix_audit(synthetic, 18)
    enron_matrix = matrix_audit(enron, 30)
    synthetic_changes = reference_rank_changes(synthetic, synthetic_reference)
    enron_changes = reference_rank_changes(enron, enron_reference)
    synthetic_v5 = method_summary(synthetic, "formulaguard_v5")
    enron_v5 = method_summary(enron, "formulaguard_v5")

    embedded_v4_rank_changes = []
    embedded_v4_rank_noncomparable_multi_source = []
    for dataset_name, rows in (("synthetic", synthetic), ("enron", enron)):
        by_instance: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
        for row in rows:
            by_instance[row["instance_id"]][row["method"]] = row
        for instance_id, methods in sorted(by_instance.items()):
            v5 = methods["formulaguard_v5"]
            source_count = int(float(v5.get("supported_source_formula_count", "0") or 0))
            if source_count != 1:
                embedded_v4_rank_noncomparable_multi_source.append({
                    "dataset": dataset_name,
                    "instance_id": instance_id,
                    "supported_source_formula_count": source_count,
                    "reason": (
                        "V5 source-row v4_final_rank belongs to the source selected by "
                        "the V5 event minimum; it is not necessarily the source that "
                        "attained the locked V4 event minimum."
                    ),
                })
                continue
            embedded = int(float(v5.get("v4_final_rank", "0") or 0))
            locked = int(float(methods["formulaguard_v4"]["rank"]))
            if embedded != locked:
                embedded_v4_rank_changes.append({
                    "dataset": dataset_name,
                    "instance_id": instance_id,
                    "embedded_v4_rank": embedded,
                    "locked_v4_rank": locked,
                })

    by_error: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in synthetic:
        if row["method"] == "formulaguard_v5":
            by_error[row.get("error_type", "")].append(row)
    by_error_top5 = {
        error_type: statistics.fmean(float(row["top5"]) for row in group)
        for error_type, group in sorted(by_error.items())
    }

    enron_by_instance: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in enron:
        enron_by_instance[row["instance_id"]][row["method"]] = row
    severe_vs_graph = []
    severe_vs_v4 = []
    for instance_id, methods in sorted(enron_by_instance.items()):
        v5_rank = int(float(methods["formulaguard_v5"]["rank"]))
        graph_rank = int(float(methods["graph"]["rank"]))
        v4_rank = int(float(methods["formulaguard_v4"]["rank"]))
        if v5_rank - graph_rank > 20:
            severe_vs_graph.append({"instance_id": instance_id, "rank_drop": v5_rank - graph_rank})
        if v5_rank - v4_rank > 20:
            severe_vs_v4.append({"instance_id": instance_id, "rank_drop": v5_rank - v4_rank})

    by_instance = {}
    for row in synthetic + enron:
        by_instance.setdefault(row["instance_id"], {})[row["method"]] = row

    invalid_joint_rows = []
    invalid_fallback_rows = []
    for row in [item for item in synthetic + enron if item["method"] == "formulaguard_v5"]:
        if row.get("diagnostic_status") == "joint_confirmed":
            valid = (
                row.get("v4_diagnostic_status") == "strong_counterfactual"
                and row.get("pattern_elite") == "1"
                and row.get("joint_eligible") == "1"
                and row.get("joint_gate_active") == "1"
                and 1 <= int(float(row.get("joint_candidate_count", "0") or 0)) <= 5
                and int(float(row.get("v4_final_rank", "0") or 0)) > 5
            )
            if not valid:
                invalid_joint_rows.append({
                    "instance_id": row["instance_id"],
                    "diagnostic_status": row.get("diagnostic_status", ""),
                })
        joint_count = int(float(row.get("joint_candidate_count", "0") or 0))
        if joint_count == 0 or joint_count > 5:
            locked_v4_rank = int(float(by_instance[row["instance_id"]]["formulaguard_v4"]["rank"]))
            if int(float(row["rank"])) != locked_v4_rank:
                invalid_fallback_rows.append({
                    "instance_id": row["instance_id"],
                    "joint_candidate_count": joint_count,
                    "v5_rank": int(float(row["rank"])),
                    "v4_rank": locked_v4_rank,
                })

    comparison_methods = ("graph", "pattern", "formulaguard", "formulaguard_v3", "formulaguard_v4")
    comparisons = {
        "synthetic": {
            f"formulaguard_v5_minus_{method}": paired_mrr(
                synthetic, "formulaguard_v5", method
            )
            for method in comparison_methods
        },
        "enron": {
            f"formulaguard_v5_minus_{method}": paired_mrr(enron, "formulaguard_v5", method)
            for method in comparison_methods
        },
    }

    gates = {
        "prerequisite_integrity_passed": prerequisite.get("passed") is True,
        "synthetic_complete_matrix": bool(synthetic_matrix["passed"]),
        "enron_complete_matrix": bool(enron_matrix["passed"]),
        "reference_ranks_unchanged": not synthetic_changes and not enron_changes,
        "v5_embedded_v4_single_source_rank_matches_locked_v4": not embedded_v4_rank_changes,
        "joint_rules_respected": not invalid_joint_rows,
        "inactive_gate_exactly_falls_back_to_v4": not invalid_fallback_rows,
        "synthetic_top5_at_least_17_of_18": synthetic_v5["top5"] >= 17 / 18,
        "synthetic_mrr_at_least_0_950": synthetic_v5["mrr"] >= 0.950,
        "all_error_types_top5_at_least_two_thirds": (
            len(by_error_top5) == 6 and all(value >= 2 / 3 for value in by_error_top5.values())
        ),
        "enron_top5_at_least_0_467": enron_v5["top5"] >= 0.467 - 1e-12,
        "enron_mrr_at_least_0_363": enron_v5["mrr"] >= 0.363 - 1e-12,
        "enron_severe_drops_vs_graph_at_most_3": len(severe_vs_graph) <= 3,
        "enron_new_severe_drops_vs_v4_at_most_2": len(severe_vs_v4) <= 2,
        "clean_workbooks_exactly_48": int(clean.get("clean_workbooks", 0)) == 48,
        "clean_joint_alarm_at_most_0_25": float(clean.get("alarm_rate", 1.0)) <= 0.25,
    }
    payload = {
        "audit_scope": "single_preregistered_v5_development_run_not_confirmatory",
        "synthetic_matrix": synthetic_matrix,
        "enron_matrix": enron_matrix,
        "synthetic_reference_rank_changes": synthetic_changes,
        "enron_reference_rank_changes": enron_changes,
        "v5_embedded_v4_single_source_rank_changes": embedded_v4_rank_changes,
        "v5_embedded_v4_rank_noncomparable_multi_source_events": (
            embedded_v4_rank_noncomparable_multi_source
        ),
        "synthetic_v5": synthetic_v5,
        "synthetic_v5_by_error_top5": by_error_top5,
        "enron_v5": enron_v5,
        "enron_severe_rank_drops_gt20_vs_graph": severe_vs_graph,
        "enron_severe_rank_drops_gt20_vs_v4": severe_vs_v4,
        "clean_v5": clean,
        "prerequisite_integrity": prerequisite,
        "invalid_joint_confirmations": invalid_joint_rows,
        "invalid_v4_fallbacks": invalid_fallback_rows,
        "paired_mrr_comparisons": comparisons,
        "gates": gates,
        "freeze_permitted": all(gates.values()),
        "failure_policy": "Algorithmic gate failure rejects V5; no V5-R2 is permitted.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if not payload["freeze_permitted"]:
        raise SystemExit("V5 development gates failed; freezing is forbidden")


if __name__ == "__main__":
    main()
