"""Create event-aware external statistics, including exact random expectations."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path


def random_event_expectation(n: int, m: int) -> dict[str, float]:
    """Expected first-hit metrics for m labeled formulas in a random ranking of n."""
    if n < 1 or m < 1 or m > n:
        raise ValueError(f"invalid random-ranking dimensions n={n}, m={m}")
    denominator = math.comb(n, m)

    def topk(k: int) -> float:
        if k >= n or n - k < m:
            return 1.0
        return 1.0 - math.comb(n - k, m) / denominator

    expected_mrr = 0.0
    for rank in range(1, n - m + 2):
        probability = math.comb(n - rank, m - 1) / denominator
        expected_mrr += probability / rank
    expected_min_rank = (n + 1) / (m + 1)
    return {
        "top1": topk(1),
        "top3": topk(3),
        "top5": topk(5),
        "mrr": expected_mrr,
        "exam": expected_min_rank / n,
    }


def bootstrap_mean_difference(values: list[float], seed: int = 20260817, draws: int = 10000):
    if not values:
        return [None, None]
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        sample = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(statistics.fmean(sample))
    estimates.sort()
    return [estimates[int(0.025 * draws)], estimates[int(0.975 * draws)]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze event-level external localization results")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-quantitative-events", type=int, default=15)
    args = parser.parse_args()

    with args.raw.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("External raw results are empty")
    by_method: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_instance: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_method[row["method"]].append(row)
        by_instance[row["instance_id"]][row["method"]] = row

    reference_rows = next(iter(by_method.values()))
    random_rows = []
    for row in reference_rows:
        metrics = random_event_expectation(
            int(row["formula_count"]),
            int(row["supported_source_formula_count"]),
        )
        random_rows.append({"instance_id": row["instance_id"], **metrics})

    summary_rows = []
    for method, group in sorted(by_method.items()):
        summary_rows.append({
            "method": method,
            "events": len(group),
            "top1": statistics.fmean(float(row["top1"]) for row in group),
            "top3": statistics.fmean(float(row["top3"]) for row in group),
            "top5": statistics.fmean(float(row["top5"]) for row in group),
            "mrr": statistics.fmean(float(row["mrr"]) for row in group),
            "exam": statistics.fmean(float(row["exam"]) for row in group),
        })
    summary_rows.append({
        "method": "random_expected_exact",
        "events": len(random_rows),
        "top1": statistics.fmean(row["top1"] for row in random_rows),
        "top3": statistics.fmean(row["top3"] for row in random_rows),
        "top5": statistics.fmean(row["top5"] for row in random_rows),
        "mrr": statistics.fmean(row["mrr"] for row in random_rows),
        "exam": statistics.fmean(row["exam"] for row in random_rows),
    })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = args.output.with_suffix(".summary.csv")
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    comparisons = {}
    comparison_pairs = (
        ("formulaguard_v3", "formulaguard"),
        ("formulaguard_v3", "warder_like"),
        ("formulaguard_v3_real", "formulaguard"),
        ("formulaguard_v3_real", "formulaguard_v3"),
        ("formulaguard_v3_real", "warder_like"),
    )
    for left, right in comparison_pairs:
        if left not in by_method or right not in by_method:
            continue
        paired = []
        for methods in by_instance.values():
            if left in methods and right in methods:
                paired.append(float(methods[left]["mrr"]) - float(methods[right]["mrr"]))
        comparisons[f"{left}_minus_{right}"] = {
            "events": len(paired),
            "mean_mrr_difference": statistics.fmean(paired) if paired else None,
            "bootstrap_95_ci": bootstrap_mean_difference(paired),
            "better_events": sum(value > 0 for value in paired),
            "equal_events": sum(value == 0 for value in paired),
            "worse_events": sum(value < 0 for value in paired),
            "confirmatory": len(paired) >= args.minimum_quantitative_events,
        }

    v3_rows = by_method.get("formulaguard_v3", [])
    evidence_counts = {
        value: sum(row.get("candidate_evidence", "") == value for row in v3_rows)
        for value in ("positive", "weak", "")
    }
    v3_real_rows = by_method.get("formulaguard_v3_real", [])
    diagnostic_status_counts = {
        value: sum(row.get("diagnostic_status", "") == value for row in v3_real_rows)
        for value in ("counterfactual_supported", "pattern_only", "insufficient_evidence", "")
    }
    payload = {
        "events": len(by_instance),
        "quantitative_reporting_allowed": len(by_instance) >= args.minimum_quantitative_events,
        "exact_random_expectation": next(row for row in summary_rows if row["method"] == "random_expected_exact"),
        "paired_comparisons": comparisons,
        "v3_candidate_evidence_counts": evidence_counts,
        "v3_real_diagnostic_status_counts": diagnostic_status_counts,
        "interpretation_rule": (
            "For multi-cell events, compare against the exact first-hit expectation for m labeled "
            "formula cells among n formulas; a single seeded random ranking is not a stable baseline."
        ),
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
