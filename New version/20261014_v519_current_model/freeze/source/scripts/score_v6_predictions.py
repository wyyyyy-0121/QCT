"""Score completed V6 shards; labels are opened only after completion proof."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def mean(values):
    return statistics.fmean(values) if values else 0.0


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(p * (len(ordered) - 1))))]


def bootstrap(values, seed=20260819, draws=10000):
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    estimates = [mean([rng.choice(values) for _ in values]) for _ in range(draws)]
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def macro_top5(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["error_type"]].append(row["top5"])
    return mean([mean(values) for values in grouped.values()])


def macro_bootstrap_difference(v6_rows, v4_rows, seed=20260819, draws=10000):
    v4 = {row["instance_id"]: row for row in v4_rows}
    by_type = defaultdict(list)
    for row in v6_rows:
        by_type[row["error_type"]].append((row["top5"], v4[row["instance_id"]]["top5"]))
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        differences = []
        for pairs in by_type.values():
            draw = [rng.choice(pairs) for _ in pairs]
            differences.append(mean([a - b for a, b in draw]))
        estimates.append(mean(differences))
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=10000)
    args = parser.parse_args()
    completion = args.predictions / "prediction_complete.json"
    completion_payload = json.loads(completion.read_text(encoding="utf-8")) if completion.is_file() else {}
    if not completion_payload.get("complete") or not completion_payload.get("full_ranking_audit_passed"):
        raise SystemExit("Scoring refused: prediction completion proof is missing")
    labels = {row["instance_id"]: row for row in load_jsonl(args.benchmark / "evaluation_labels.jsonl")}
    public = {row["instance_id"]: row for row in load_jsonl(args.benchmark / "instances.jsonl")}
    shards = sorted((args.predictions / "shards").glob("*.json"))
    if {path.stem for path in shards} != set(labels):
        raise SystemExit("Scoring refused: shard and label instance sets differ")
    raw = []
    traceability = True
    methods = set()
    for shard in shards:
        record = json.loads(shard.read_text(encoding="utf-8"))
        instance_id = record["instance_id"]
        label, row_public = labels[instance_id], public[instance_id]
        source = label["source_cell"].replace("$", "")
        for method, ranking in record["rankings"].items():
            methods.add(method)
            source_row = next((row for row in ranking if row["cell"].replace("$", "") == source), None)
            if source_row is None:
                raise SystemExit(f"Source absent from complete ranking: {instance_id} {method}")
            rank = int(source_row["rank"])
            evidence = source_row.get("evidence", {})
            portfolio = evidence.get("candidate_portfolio", [])
            correct = normalized_formula(label["correct_formula"])
            coverage = any(normalized_formula(item["formula"]) == correct for item in portfolio[:25]) if method.startswith("v6_") else False
            candidate = source_row.get("candidate_formula", "")
            repair_exact = bool(candidate) and normalized_formula(candidate) == correct
            promoted = next((item for item in ranking if item.get("evidence", {}).get("promotion_target")), None)
            is_main_v6 = method in {"v6_a", "v6_b", "v6_c"}
            if is_main_v6:
                required = {
                    "model_version", "v4_rank", "v6_rank", "semantic_tier", "family_support",
                    "boundary_support", "candidate_sources", "candidate_edit_kinds",
                    "counterfactual_delta", "counterfactual_irg", "global_harm", "propagation_path",
                }
                traceability = traceability and required <= set(evidence)
            raw.append({
                "instance_id": instance_id,
                "method": method,
                "error_type": label["mutation_type"],
                "topology": row_public["topology_id"],
                "complexity": row_public["complexity"],
                "expected_depth": label["expected_depth"],
                "actual_depth": label.get("actual_depth"),
                "formula_count": record["formula_count"],
                "size_bucket": (
                    "small_lt_100" if record["formula_count"] < 100 else
                    "medium_100_499" if record["formula_count"] < 500 else "large_ge_500"
                ),
                "source_cell": label["source_cell"],
                "rank": rank,
                "top1": int(rank <= 1),
                "top3": int(rank <= 3),
                "top5": int(rank <= 5),
                "mrr": 1 / rank,
                "exam": rank / max(1, record["formula_count"]),
                "repair_exact": int(repair_exact) if method == "v4" or is_main_v6 else "",
                "candidate_coverage_at_25": int(coverage) if is_main_v6 else "",
                "promotion_active": int(promoted is not None) if is_main_v6 else "",
                "promotion_correct": int(bool(promoted) and promoted["cell"].replace("$", "") == source) if is_main_v6 else "",
                "candidate_formula": candidate,
                "candidate_sources": evidence.get("candidate_sources", ""),
                "candidate_edit_kinds": evidence.get("candidate_edit_kinds", ""),
                "semantic_tier": evidence.get("semantic_tier", ""),
                "family_support": evidence.get("family_support", ""),
                "boundary_support": evidence.get("boundary_support", ""),
                "counterfactual_delta": evidence.get("counterfactual_delta", ""),
                "counterfactual_irg": evidence.get("counterfactual_irg", ""),
                "global_harm": evidence.get("global_harm", ""),
                "promotion_reason": evidence.get("promotion_reason", ""),
                "runtime_seconds": evidence.get("localization_seconds") or record["wall_seconds"],
            })
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "raw_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0]))
        writer.writeheader(); writer.writerows(raw)
    summaries = {}
    by_error_rows = []
    for method in sorted(methods):
        rows = [row for row in raw if row["method"] == method]
        per_type = {}
        for error in sorted({row["error_type"] for row in rows}):
            items = [row for row in rows if row["error_type"] == error]
            per_type[error] = {
                "events": len(items),
                "top5": mean([row["top5"] for row in items]),
                "mrr": mean([row["mrr"] for row in items]),
            }
            by_error_rows.append({"method": method, "error_type": error, **per_type[error]})
        summaries[method] = {
            "events": len(rows),
            "top1": mean([row["top1"] for row in rows]),
            "top3": mean([row["top3"] for row in rows]),
            "top5": mean([row["top5"] for row in rows]),
            "macro_top5": mean([item["top5"] for item in per_type.values()]),
            "worst_type_top5": min((item["top5"] for item in per_type.values()), default=0),
            "mrr": mean([row["mrr"] for row in rows]),
            "exam": mean([row["exam"] for row in rows]),
            "repair_exact": mean([row["repair_exact"] for row in rows if row["repair_exact"] != ""]),
            "candidate_coverage_at_25": mean([row["candidate_coverage_at_25"] for row in rows if row["candidate_coverage_at_25"] != ""]),
            "promotion_activation": mean([row["promotion_active"] for row in rows if row["promotion_active"] != ""]),
            "promotion_precision": (
                sum(row["promotion_correct"] for row in rows if row["promotion_correct"] != "") /
                max(1, sum(row["promotion_active"] for row in rows if row["promotion_active"] != ""))
            ),
            "runtime_median": statistics.median(float(row["runtime_seconds"]) for row in rows),
            "by_error": per_type,
        }
    with (args.output / "by_error.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(by_error_rows[0]))
        writer.writeheader(); writer.writerows(by_error_rows)
    by_stratum_rows = []
    for method in sorted(methods):
        method_rows = [row for row in raw if row["method"] == method]
        for field in ("error_type", "topology", "complexity", "expected_depth", "size_bucket"):
            for value in sorted({row[field] for row in method_rows}):
                items = [row for row in method_rows if row[field] == value]
                by_stratum_rows.append({
                    "method": method, "stratum": field, "value": value, "events": len(items),
                    "top1": mean([row["top1"] for row in items]),
                    "top5": mean([row["top5"] for row in items]),
                    "mrr": mean([row["mrr"] for row in items]),
                    "repair_exact": mean([row["repair_exact"] for row in items if row["repair_exact"] != ""]),
                })
    with (args.output / "by_stratum.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(by_stratum_rows[0]))
        writer.writeheader(); writer.writerows(by_stratum_rows)
    failures = [
        row for row in raw
        if row["method"] in {"v6_a", "v6_b", "v6_c"} and row["rank"] > 5
    ]
    with (args.output / "failure_cases.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0]))
        writer.writeheader(); writer.writerows(failures)
    comparisons = {}
    v4_rows = [row for row in raw if row["method"] == "v4"]
    v4_by_id = {row["instance_id"]: row for row in v4_rows}
    for method in sorted(method for method in methods if method.startswith("v6_")):
        rows = [row for row in raw if row["method"] == method]
        mrr_diffs = [row["mrr"] - v4_by_id[row["instance_id"]]["mrr"] for row in rows]
        comparisons[method] = {
            "mrr_difference": mean(mrr_diffs),
            "mrr_difference_bootstrap_95_ci": bootstrap(mrr_diffs, draws=args.bootstrap),
            "macro_top5_difference": summaries[method]["macro_top5"] - summaries["v4"]["macro_top5"],
            "macro_top5_difference_bootstrap_95_ci": macro_bootstrap_difference(rows, v4_rows, draws=args.bootstrap),
        }
    payload = {
        "protocol": "v6_scoring_after_label_free_prediction_completion",
        "events": len(labels),
        "summaries": summaries,
        "paired_v6_minus_v4": comparisons,
        "traceability_complete": traceability,
        "bootstrap_seed": 20260819,
        "bootstrap_draws": args.bootstrap,
        "historical_100_excluded": True,
    }
    (args.output / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "summary.json")


if __name__ == "__main__":
    main()
