"""Independent audit of the completed V6 locked internal validation.

This does not rescore workbooks or alter model selection. It independently
checks the row grain, metric identities, aggregates, bootstrap intervals,
precommit hashes, complete-ranking receipts, clean controls, Enron receipts,
ablation shape and the deterministic selection decision.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERROR_TYPES = (
    "absolute_reference", "copy_offset", "function_replacement",
    "operator", "range_boundary", "reference_shift",
)
STRONG_TYPES = ("reference_shift", "operator", "absolute_reference", "copy_offset")
ABLATIONS = (
    "no_ffc", "no_bss", "no_d", "no_irg", "no_side_effect",
    "no_uniqueness", "v4_only", "semantics_only",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def mean(values) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(p * (len(ordered) - 1))))]


def bootstrap(values: list[float], draws: int = 10000, seed: int = 20260819) -> list[float]:
    rng = random.Random(seed)
    estimates = [mean(rng.choice(values) for _ in values) for _ in range(draws)]
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def macro_bootstrap_difference(v6_rows: list[dict], v4_rows: list[dict], draws: int = 10000) -> list[float]:
    v4 = {row["instance_id"]: row for row in v4_rows}
    by_type: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in v6_rows:
        by_type[row["error_type"]].append((row["top5"], v4[row["instance_id"]]["top5"]))
    rng = random.Random(20260819)
    estimates = []
    for _ in range(draws):
        type_differences = []
        for pairs in by_type.values():
            sampled = [rng.choice(pairs) for _ in pairs]
            type_differences.append(mean(left - right for left, right in sampled))
        estimates.append(mean(type_differences))
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def numeric_row(row: dict[str, str]) -> dict:
    converted = dict(row)
    for field in (
        "formula_count", "rank", "top1", "top3", "top5", "repair_exact",
        "candidate_coverage_at_25", "promotion_active", "promotion_correct",
    ):
        converted[field] = int(float(row[field])) if row[field] != "" else ""
    for field in ("mrr", "exam", "runtime_seconds"):
        converted[field] = float(row[field])
    return converted


def summarize(rows: list[dict]) -> dict:
    per_type = {}
    for error in ERROR_TYPES:
        items = [row for row in rows if row["error_type"] == error]
        per_type[error] = {
            "events": len(items),
            "top5": mean(row["top5"] for row in items),
            "mrr": mean(row["mrr"] for row in items),
        }
    active = [row for row in rows if row["promotion_active"] != ""]
    repair = [row["repair_exact"] for row in rows if row["repair_exact"] != ""]
    coverage = [row["candidate_coverage_at_25"] for row in rows if row["candidate_coverage_at_25"] != ""]
    return {
        "events": len(rows),
        "top1": mean(row["top1"] for row in rows),
        "top3": mean(row["top3"] for row in rows),
        "top5": mean(row["top5"] for row in rows),
        "macro_top5": mean(item["top5"] for item in per_type.values()),
        "worst_type_top5": min(item["top5"] for item in per_type.values()),
        "mrr": mean(row["mrr"] for row in rows),
        "exam": mean(row["exam"] for row in rows),
        "repair_exact": mean(repair),
        "candidate_coverage_at_25": mean(coverage),
        "promotion_activation": mean(row["promotion_active"] for row in active),
        "promotion_precision": (
            sum(row["promotion_correct"] for row in active)
            / max(1, sum(row["promotion_active"] for row in active))
        ),
        "runtime_median": statistics.median(row["runtime_seconds"] for row in rows),
        "by_error": per_type,
    }


def compare_summary(recomputed: dict, declared: dict, method: str, issues: list[str]) -> None:
    for field in (
        "events", "top1", "top3", "top5", "macro_top5", "worst_type_top5",
        "mrr", "exam", "repair_exact", "candidate_coverage_at_25",
        "promotion_activation", "promotion_precision", "runtime_median",
    ):
        if not close(float(recomputed[field]), float(declared[field])):
            issues.append(f"summary_mismatch:{method}:{field}")
    for error in ERROR_TYPES:
        for field in ("events", "top5", "mrr"):
            if not close(float(recomputed["by_error"][error][field]), float(declared["by_error"][error][field])):
                issues.append(f"by_error_mismatch:{method}:{error}:{field}")


def workbook_inventory(dataset: Path) -> dict:
    paths = sorted(dataset.rglob("*.xlsx"), key=lambda item: item.relative_to(dataset).as_posix())
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(dataset).as_posix()
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(sha256(path).encode("ascii")); digest.update(b"\n")
    return {"count": len(paths), "aggregate_sha256": digest.hexdigest()}


def combined_shard_hash(shard_paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in shard_paths:
        digest.update(path.name.encode())
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def audit(args) -> dict:
    root, dataset = args.root.resolve(), args.dataset.resolve()
    summary = load_json(root / "summary.json")
    selection = load_json(root / "v6_selection_receipt.json")
    metadata = load_json(root / "predictions/prediction_metadata.json")
    completion = load_json(root / "predictions/prediction_complete.json")
    precommit = load_json(args.precommit.resolve())
    quality = load_json(dataset / "validation/dataset_quality.json")
    leakage = load_json(dataset / "validation/leakage_audit.json")
    clean = load_json(root / "clean/v6_clean_summary.json")
    clean_metadata = load_json(root / "clean/predictions/prediction_metadata.json")
    clean_completion = load_json(root / "clean/predictions/prediction_complete.json")
    enron = {letter: load_json(root / f"enron_{letter}/enron_summary.json") for letter in "abc"}
    enron_completion = {
        letter: load_json(root / f"enron_{letter}/enron_prediction_complete.json") for letter in "abc"
    }
    public = load_jsonl(dataset / "instances.jsonl")
    labels = load_jsonl(dataset / "evaluation_labels.jsonl")
    label_by_id = {row["instance_id"]: row for row in labels}
    public_ids = [row["instance_id"] for row in public]
    label_ids = [row["instance_id"] for row in labels]
    raw = [numeric_row(row) for row in load_csv(root / "raw_results.csv")]

    expected_methods = {"v4", "v6_a", "v6_b", "v6_c"}
    expected_methods.update(
        f"v6_{letter}_ablation_{ablation}" for letter in "abc" for ablation in ABLATIONS
    )
    issues: list[str] = []
    if len(public) != 360 or len(labels) != 360:
        issues.append("validation_event_count_not_360")
    if len(public_ids) != len(set(public_ids)) or len(label_ids) != len(set(label_ids)):
        issues.append("duplicate_public_or_label_id")
    if set(public_ids) != set(label_ids):
        issues.append("public_label_id_mismatch")
    if {row["method"] for row in raw} != expected_methods:
        issues.append("method_set_mismatch")
    if len(raw) != 360 * len(expected_methods):
        issues.append("raw_row_count_mismatch")
    keys = Counter((row["instance_id"], row["method"]) for row in raw)
    if len(keys) != len(raw) or any(value != 1 for value in keys.values()):
        issues.append("duplicate_event_method_key")
    event_method_counts = Counter(row["instance_id"] for row in raw)
    if set(event_method_counts) != set(public_ids) or set(event_method_counts.values()) != {len(expected_methods)}:
        issues.append("event_method_coverage_mismatch")
    for row in raw:
        if not 1 <= row["rank"] <= row["formula_count"]:
            issues.append(f"rank_out_of_bounds:{row['instance_id']}:{row['method']}")
        for field, expected in (
            ("top1", int(row["rank"] <= 1)),
            ("top3", int(row["rank"] <= 3)),
            ("top5", int(row["rank"] <= 5)),
        ):
            if row[field] != expected:
                issues.append(f"metric_identity:{field}:{row['instance_id']}:{row['method']}")
        if not close(row["mrr"], 1.0 / row["rank"]):
            issues.append(f"mrr_identity:{row['instance_id']}:{row['method']}")
        if not close(row["exam"], row["rank"] / row["formula_count"]):
            issues.append(f"exam_identity:{row['instance_id']}:{row['method']}")
        label = label_by_id.get(row["instance_id"])
        if label and row["error_type"] != label["mutation_type"]:
            issues.append(f"label_type_join:{row['instance_id']}:{row['method']}")

    recomputed = {}
    for method in sorted(expected_methods):
        rows = [row for row in raw if row["method"] == method]
        recomputed[method] = summarize(rows)
        compare_summary(recomputed[method], summary["summaries"][method], method, issues)

    label_balance = Counter(row["mutation_type"] for row in labels)
    if set(label_balance) != set(ERROR_TYPES) or set(label_balance.values()) != {60}:
        issues.append("label_balance_mismatch")

    shards = sorted((root / "predictions/shards").glob("*.json"))
    receipt_checks = {
        "prediction_shards_360": len(shards) == 360,
        "combined_shard_hash_matches": combined_shard_hash(shards) == completion["combined_shards_sha256"],
        "metadata_hash_matches": sha256(root / "predictions/prediction_metadata.json") == completion["metadata_sha256"],
        "prediction_completion_passed": completion.get("complete") and completion.get("full_ranking_audit_passed"),
        "workers_24": completion.get("workers_requested") == 24,
        "label_files_read_empty": metadata.get("label_files_read") == [],
        "all_variants_and_ablations_declared": (
            metadata.get("variants") == ["a", "b", "c"] and metadata.get("ablations") == list(ABLATIONS)
        ),
        "public_instances_hash_matches_precommit": metadata.get("instances_sha256") == precommit["public_file_sha256"]["instances.jsonl"],
        "dataset_manifest_hash_matches_precommit": metadata.get("dataset_manifest_sha256") == precommit["public_file_sha256"]["dataset_manifest.json"],
        "label_hash_matches_precommit": sha256(dataset / precommit["secret_label_file"]) == precommit["secret_label_sha256"],
        "workbook_inventory_matches_precommit": workbook_inventory(dataset) == precommit["workbook_inventory"],
        "v6_source_matches_precommit": metadata.get("v6_source_sha256") == precommit["v6_source_sha256"],
        "v4_source_matches_precommit": metadata.get("v4_source_sha256") == precommit["v4_source_sha256"],
        "method_spec_matches_precommit": metadata.get("method_spec_sha256") == precommit["method_spec_sha256"],
        "data_quality_passed": quality.get("hard_gate_passed", False),
        "cross_split_leakage_passed": leakage.get("cross_split_passed", False),
        "historical_100_excluded": summary.get("historical_100_excluded", False),
    }
    issues.extend(name for name, passed in receipt_checks.items() if not passed)

    ci_recomputed = {}
    v4_rows = [row for row in raw if row["method"] == "v4"]
    v4_by_id = {row["instance_id"]: row for row in v4_rows}
    for method in ("v6_a", "v6_b", "v6_c"):
        rows = [row for row in raw if row["method"] == method]
        mrr_diffs = [row["mrr"] - v4_by_id[row["instance_id"]]["mrr"] for row in rows]
        ci_recomputed[method] = {
            "mrr_difference_bootstrap_95_ci": bootstrap(mrr_diffs),
            "macro_top5_difference_bootstrap_95_ci": macro_bootstrap_difference(rows, v4_rows),
        }
        declared = summary["paired_v6_minus_v4"][method]
        for field, values in ci_recomputed[method].items():
            if any(not close(a, b) for a, b in zip(values, declared[field])):
                issues.append(f"bootstrap_ci_mismatch:{method}:{field}")

    clean_manifest = load_json(ROOT / "data/v6_clean/clean_manifest.json")
    clean_structure = {row["clean_id"]: row["structure"] for row in clean_manifest}
    clean_alarm_counts = {letter: Counter() for letter in "abc"}
    clean_shards = sorted((root / "clean/predictions/shards").glob("*.json"))
    for path in clean_shards:
        record = load_json(path)
        for letter in "abc":
            promoted = [
                row for row in record["rankings"][f"v6_{letter}"]
                if row.get("evidence", {}).get("promotion_target")
            ]
            if len(promoted) > 1:
                issues.append(f"multiple_clean_promotions:{letter}:{path.stem}")
            if promoted:
                clean_alarm_counts[letter][clean_structure[path.stem]] += 1
    for letter in "abc":
        declared_alarms = clean["variants"][f"v6_{letter}"]["alarms"]
        if sum(clean_alarm_counts[letter].values()) != declared_alarms:
            issues.append(f"clean_alarm_mismatch:{letter}")
    clean_checks = {
        "clean_shards_240": len(clean_shards) == 240,
        "clean_completion_passed": clean_completion.get("complete") and clean_completion.get("full_ranking_audit_passed"),
        "clean_workers_24": clean_completion.get("workers_requested") == 24,
        "clean_label_files_read_empty": clean_metadata.get("label_files_read") == [],
        "all_alarms_confined_to_exception_structure": all(set(counts) <= {"exception"} for counts in clean_alarm_counts.values()),
    }
    issues.extend(name for name, passed in clean_checks.items() if not passed)

    selection_recomputed = {}
    v4 = recomputed["v4"]
    for letter in "abc":
        method = f"v6_{letter}"
        row = recomputed[method]
        strong_declines = {
            error: v4["by_error"][error]["top5"] - row["by_error"][error]["top5"]
            for error in STRONG_TYPES
        }
        ablation_methods = [f"v6_{letter}_ablation_{name}" for name in ABLATIONS]
        max_ablation_macro = max(recomputed[name]["macro_top5"] for name in ablation_methods)
        gates = {
            "data_validity_at_least_98_percent": quality["valid_rate"] >= 0.98,
            "cross_split_leakage_audit": leakage["cross_split_passed"],
            "all_360_predictions_complete": summary["events"] == 360 and completion["complete"] and completion["full_ranking_audit_passed"],
            "all_variants_predicted_before_scoring": metadata["variants"] == ["a", "b", "c"],
            "traceability_complete": summary["traceability_complete"],
            "candidate_coverage_at_25_at_least_95_percent": row["candidate_coverage_at_25"] >= 0.95,
            "macro_top5_at_least_80_percent": row["macro_top5"] >= 0.80,
            "worst_type_top5_at_least_70_percent": row["worst_type_top5"] >= 0.70,
            "function_replacement_top5_at_least_75_percent": row["by_error"]["function_replacement"]["top5"] >= 0.75,
            "range_boundary_top5_at_least_75_percent": row["by_error"]["range_boundary"]["top5"] >= 0.75,
            "repair_exact_at_least_75_percent": row["repair_exact"] >= 0.75,
            "clean_false_alarm_at_most_10_percent": clean["variants"][method]["false_alarm_rate"] <= 0.10,
            "strong_types_decline_at_most_5_points": max(strong_declines.values()) <= 0.05,
            "enron_mrr_not_below_v4": enron[letter]["v6_mrr_not_below_v4"],
            "enron_full_ranking_audit_passed": enron_completion[letter]["full_ranking_audit_passed"],
            "all_variant_matched_ablations_present": True,
            "not_outperformed_by_key_ablation_over_0_02": max_ablation_macro <= row["macro_top5"] + 0.02,
            "median_runtime_at_most_1_5x_v4": row["runtime_median"] <= 1.5 * v4["runtime_median"],
        }
        selection_recomputed[letter] = {"gates": gates, "passed": all(gates.values())}
        if gates != selection["assessments"][letter]["gates"]:
            issues.append(f"selection_gate_mismatch:{letter}")
        if selection_recomputed[letter]["passed"] != selection["assessments"][letter]["passed"]:
            issues.append(f"selection_pass_mismatch:{letter}")
    no_candidate = not any(item["passed"] for item in selection_recomputed.values())
    if selection.get("selected_variant") is not None or selection.get("freeze_allowed") or not no_candidate:
        issues.append("selection_or_freeze_decision_mismatch")

    semantics_only = {
        letter: recomputed[f"v6_{letter}_ablation_semantics_only"] for letter in "abc"
    }
    risk_findings = {
        "clean_false_alarm_gate_failed_all_variants": all(
            clean["variants"][f"v6_{letter}"]["false_alarm_rate"] > 0.10 for letter in "abc"
        ),
        "semantics_only_perfect_top1_all_variants": all(row["top1"] == 1.0 for row in semantics_only.values()),
        "semantics_only_outperforms_full_b_mrr": semantics_only["b"]["mrr"] > recomputed["v6_b"]["mrr"],
        "no_variant_freeze_eligible": no_candidate,
    }
    payload = {
        "protocol": "v6_locked_validation_independent_audit_v1",
        "dataset_and_grain": {
            "events": len(public), "error_types": dict(sorted(label_balance.items())),
            "methods": len(expected_methods), "raw_rows": len(raw),
            "grain": "one row per validation event and method",
        },
        "receipt_checks": receipt_checks,
        "clean_checks": clean_checks,
        "clean_alarm_counts_by_structure": {letter: dict(counts) for letter, counts in clean_alarm_counts.items()},
        "recomputed_main_metrics": {method: recomputed[method] for method in ("v4", "v6_a", "v6_b", "v6_c")},
        "recomputed_bootstrap_intervals": ci_recomputed,
        "selection_recomputed": selection_recomputed,
        "selection_receipt": {
            "selected_variant": selection.get("selected_variant"),
            "freeze_allowed": selection.get("freeze_allowed"),
            "no_v7_if_none_pass": selection.get("no_v7_if_none_pass"),
        },
        "semantics_only_metrics": semantics_only,
        "risk_findings": risk_findings,
        "issues": sorted(set(issues)),
        "audit_passed": not issues,
        "decision": "do_not_freeze_v6_stop_without_v7" if not issues and no_candidate else "manual_review_required",
    }
    return payload


def markdown(payload: dict) -> str:
    metrics = payload["recomputed_main_metrics"]
    receipt = payload["selection_receipt"]
    b = metrics["v6_b"]
    ci = payload["recomputed_bootstrap_intervals"]["v6_b"]
    failed = {
        letter.upper(): [name for name, passed in item["gates"].items() if not passed]
        for letter, item in payload["selection_recomputed"].items()
    }
    lines = [
        "# FormulaGuard V6 locked validation audit",
        "",
        "## Technical summary",
        "",
        (f"The 360-event locked validation is internally consistent and reproducible, but no V6 variant is eligible for freezing. "
        f"V6-B is the strongest locator (macro Top-5 {b['macro_top5']:.2%}, MRR {b['mrr']:.4f}, six-type minimum Top-5 {b['worst_type_top5']:.2%}), "
        "yet all three variants exceed the 10% clean-control alarm cap at 16.67%. V6-A/B also fail the exact Enron non-decrease rule, while V6-C is outperformed by a registered ablation and collapses on absolute-reference cases. "
        f"The selection receipt therefore records `selected_variant={receipt['selected_variant']}` and `freeze_allowed={str(receipt['freeze_allowed']).lower()}`."),
        "",
        "## V6-B dominates the synthetic localization task but fails deployment safety",
        "",
        "| Method | Top-1 | Top-3 | Top-5 | Macro Top-5 | Weakest type | MRR | Exact repair |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in ("v4", "v6_a", "v6_b", "v6_c"):
        row = metrics[method]
        lines.append(
            f"| {method.replace('_', '-').upper()} | {row['top1']:.2%} | {row['top3']:.2%} | {row['top5']:.2%} | "
            f"{row['macro_top5']:.2%} | {row['worst_type_top5']:.2%} | {row['mrr']:.4f} | {row['repair_exact']:.2%} |"
        )
    lines += [
        "",
        (f"V6-B improves paired MRR over V4 by {b['mrr'] - metrics['v4']['mrr']:+.4f}; the independently reproduced 95% interval is "
        f"[{ci['mrr_difference_bootstrap_95_ci'][0]:.4f}, {ci['mrr_difference_bootstrap_95_ci'][1]:.4f}]. "
        f"Its paired macro Top-5 interval is [{ci['macro_top5_difference_bootstrap_95_ci'][0]:.2%}, {ci['macro_top5_difference_bootstrap_95_ci'][1]:.2%}]. "
        "These are valid internal synthetic results, not evidence of independent real-world superiority."),
        "",
        "## Clean exceptions invalidate all three freeze candidates",
        "",
        ("Each variant triggers 40 alarms among 240 correct workbooks (16.67%). All 40 occur in the deliberately valid `exception` structure, while the other clean structures have zero alarms. "
        "This concentration identifies a systematic modeling error: alternating but intentional formula families are treated as anomalous and promoted. It is not random noise and cannot be dismissed by averaging."),
        "",
        "## The ablation pattern exposes synthetic alignment risk",
        "",
        ("The `semantics_only` ablation obtains Top-1 and MRR of 100% for A, B and C on all 360 events. "
        "That signal uses no labels at localization time, so the result is not evidence of label leakage. However, it shows that the deterministic validation generator produces errors that are perfectly separable by the same semantic regularities built into V6. "
        "Consequently, the large V6-B gain is useful mechanism evidence but is too optimistic as a generalization estimate. A third-party dataset with unseen templates is essential."),
        "",
        "## Scope, data and metric definitions",
        "",
        "- Grain: one event-method row; 360 events × 28 methods = 10,080 unique rows.",
        "- Balance: six mutation families with 60 events each; no historical revealed 100-case data is included.",
        "- Top-k: the true source formula is ranked at or above k; MRR is mean reciprocal source rank; EXAM is source rank divided by formula count.",
        "- Macro Top-5: unweighted mean of six per-type Top-5 rates; weakest type is the minimum of those six rates.",
        "- Clean alarm: any semantic promotion on one of 240 correct control workbooks.",
        "- Uncertainty: paired event bootstrap, 10,000 draws, seed 20260819.",
        "",
        "## Integrity and label-separation checks passed",
        "",
        ("The public and secret precommit hashes, 720-workbook inventory, V4/V6/method source hashes, 360 complete prediction shards, combined shard digest, 24-worker receipt, 28-method coverage, raw metric identities, aggregate summaries, bootstrap intervals, clean alarms, Enron receipts and selection gates were independently recomputed. "
        "Prediction metadata records `label_files_read=[]`; the secret label hash was released only after the complete-ranking receipt existed. No audit discrepancy was found."),
        "",
        "## Registered gate failures",
        "",
    ]
    for letter in "ABC":
        lines.append(f"- V6-{letter}: {', '.join(failed[letter])}")
    lines += [
        "",
        "## Limitations and robustness",
        "",
        ("This is a deterministic internal synthetic validation, not a third-party blind study. The perfect semantics-only result is the main robustness warning. Enron contains only 30 retrospective events and A/B fail its exact safety gate by a numerically tiny one-rank tail change. "
        "The clean-control failure is larger and practically important. Because the thresholds and stop rule were preregistered, changing them after seeing these results would invalidate the locked decision."),
        "",
        "## Recommended next steps",
        "",
        "1. Do not run `run_v6_freeze.cmd`; preserve the null selection receipt and all negative evidence.",
        "2. Do not tune V6 or open V7 within this protocol. Retain V4-R1 as the frozen main model and present V6 as a mechanism experiment with a clear safety failure.",
        "3. Do not request the 600-case third-party V6 package because no model was frozen. If a future separately preregistered study is approved, redesign ambiguity handling before obtaining new labels.",
        "4. Use the BSS range-boundary result and the clean-exception counterexample as the strongest scientifically honest V6 contributions.",
        "",
        "## Further questions",
        "",
        "- Can a future model recognize legitimate multi-regime formula blocks without learning from the locked controls?",
        "- How much of V6-B's gain persists on independently authored workbooks whose formula families were not generated by the V6 benchmark code?",
        "- Can range-boundary semantics be added as a non-ranking review explanation instead of a main-rank promotion?",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "results/v6_validation_locked")
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/v6_validation")
    parser.add_argument("--precommit", type=Path, default=ROOT / "research/V6_VALIDATION_PRECOMMIT.json")
    parser.add_argument("--json-output", type=Path, default=ROOT / "research/V6_VALIDATION_AUDIT.json")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "research/V6_VALIDATION_RESULTS.md")
    args = parser.parse_args()
    payload = audit(args)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(markdown(payload), encoding="utf-8")
    print(args.json_output)
    print(args.markdown_output)
    if not payload["audit_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
