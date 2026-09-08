"""Audit the revealed, hash-locked V4/V5.2 independent case set.

This is a reporting audit, not a model-selection tool.  It consumes only the
scored events emitted after ``verify_joint_lock`` has succeeded and writes
deterministic, event-level uncertainty summaries for the evidence ledger.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_external_results import (
    bootstrap_mean_difference,
    random_event_expectation,
)

SEED = 20260819
DRAWS = 10_000


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _metric_summary(values: list[float]) -> dict[str, object]:
    return {
        "estimate": _mean(values),
        "bootstrap_95_ci": bootstrap_mean_difference(values, seed=SEED, draws=DRAWS),
    }


def _source_count(row: dict[str, str]) -> int:
    return len([cell for cell in row.get("source_cells", "").split(";") if cell.strip()])


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a scored V4/V5.2 independent case set")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-events", type=int, default=15)
    args = parser.parse_args()

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    rows = _read_csv(args.events)
    ids = [row.get("instance_id", "") for row in rows]
    if len(rows) != args.expected_events or len(set(ids)) != args.expected_events or any(not value for value in ids):
        raise SystemExit("Independent audit requires exactly the expected number of unique scored event IDs")
    if not summary.get("prediction_lock_verified"):
        raise SystemExit("Independent audit refused: the prediction lock was not verified")
    if metadata.get("events") != args.expected_events or metadata.get("label_inputs") != []:
        raise SystemExit("Independent audit refused: lock metadata does not prove label-free prediction")

    v4 = {
        metric: [float(row[f"v4_{metric}"]) for row in rows]
        for metric in ("top1", "top3", "top5", "mrr", "exam")
    }
    random_rows = [
        random_event_expectation(int(row["formula_count"]), _source_count(row))
        for row in rows
    ]
    random_metrics = {
        metric: [float(row[metric]) for row in random_rows]
        for metric in ("top1", "top3", "top5", "mrr", "exam")
    }
    summary_match = all(
        abs(_mean(v4[metric]) - float(summary["v4"][metric])) < 1e-12
        for metric in v4
    )
    if not summary_match:
        raise SystemExit("Independent audit refused: event metrics do not match scored summary")

    repair_evaluable = [float(row["v4_repair_evaluable"]) for row in rows]
    repair_exact = [float(row["v4_repair_exact"]) for row in rows]
    rescue_active = [float(row["rescue_active"]) for row in rows]
    rescue_correct = [float(row["rescue_correct"]) for row in rows]
    incremental = [float(row["incremental_rescue_hit"]) for row in rows]
    review6 = [float(row["review6_hit"]) for row in rows]
    exception_exposure = [float(row["correct_exception_exposure"]) for row in rows]
    core_non_interference = all(row["core_non_interference"] == "1" for row in rows)

    selected_gates = summary["formal_auxiliary_module_gates"]
    output = {
        "protocol": "v4_v52_independent_result_audit_after_label_release",
        "scope": summary.get(
            "scope", f"{args.expected_events}_event_independent_validation_case_set"
        ),
        "not_for_model_selection": True,
        "input_files": {
            "summary": str(args.summary.resolve()),
            "events": str(args.events.resolve()),
            "joint_prediction_metadata": str(args.metadata.resolve()),
        },
        "integrity": {
            "unique_event_ids": len(set(ids)) == args.expected_events,
            "exact_expected_event_count": len(rows) == args.expected_events,
            "prediction_lock_verified_by_scorer": bool(summary["prediction_lock_verified"]),
            "label_free_lock_metadata": metadata.get("label_inputs") == [],
            "core_top5_exactly_v4": core_non_interference,
            "summary_matches_event_rows": summary_match,
        },
        "uncertainty": {
            "bootstrap_seed": SEED,
            "bootstrap_draws": DRAWS,
            "event_resampling": True,
        },
        "v4": {metric: _metric_summary(values) for metric, values in v4.items()},
        "uniform_random_reference_only": {
            "metrics": {metric: _metric_summary(values) for metric, values in random_metrics.items()},
            "v4_minus_random_mrr": _metric_summary([
                observed - expected for observed, expected in zip(v4["mrr"], random_metrics["mrr"])
            ]),
            "claim_boundary": "This is an exact event-aware uniform-ranking reference, not an empirical no-truth baseline.",
        },
        "repair": {
            "evaluable_events": int(sum(repair_evaluable)),
            "exact_events": int(sum(repair_exact)),
            "exact_over_all_events": _metric_summary(repair_exact),
            "exact_among_evaluable_events": (
                sum(repair_exact) / sum(repair_evaluable) if sum(repair_evaluable) else None
            ),
        },
        "v52_supplemental_review": {
            "rescue_activation_rate": _metric_summary(rescue_active),
            "rescue_correct_over_all_events": _metric_summary(rescue_correct),
            "incremental_rescue_hits": int(sum(incremental)),
            "incremental_review6_rate": _metric_summary(incremental),
            "review6_hit_rate": _metric_summary(review6),
            "correct_exception_exposure_rate": _metric_summary(exception_exposure),
            "rescue_precision": (sum(rescue_correct) / sum(rescue_active) if sum(rescue_active) else 0.0),
            "formal_auxiliary_module_gates": selected_gates,
            "supported": all(bool(value) for value in selected_gates.values()),
            "claim_boundary": "Review@6 is a supplemental human-review measure and is not a Top-5 localization metric.",
        },
        "v6_decision": {
            "recommended_now": False,
            "reason": (
                "The locked independent case set supports V4 localization and the preregistered "
                "V5.2-B supplemental module.  Starting a V6 from these revealed labels would contaminate "
                "this independent set and is not justified by a repeated, unaddressed failure signature."
            ),
            "future_requirement": (
                "A future main-ranker revision requires a preregistered mechanism hypothesis, a separate "
                "development set, and a new independent test set."
            ),
        },
        "small_sample_warning": summary.get("small_sample_warning"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
