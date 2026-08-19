"""Reveal labels only after verifying the joint V4/V5.2 prediction lock."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import parse_cell_label
from formulaguard.formula import normalized_formula
from scripts.run_external_evaluation import sha256_file
from scripts.v52_blind_protocol import verify_joint_lock


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _cells(raw: str) -> set[str]:
    cells = set()
    for item in raw.split(";"):
        if item.strip():
            sheet, address = parse_cell_label(item.strip())
            cells.add(f"{sheet}!{address.upper()}")
    return cells


def _sources(row: dict[str, str]) -> set[str]:
    result = _cells(row.get("source_cells", "") or row.get("source_cell", ""))
    if not result:
        raise ValueError(f"No source label for {row.get('instance_id', '')}")
    return result


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _metric_block(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {"events": 0}
    activations = sum(int(row["rescue_active"]) for row in rows)
    correct_rescues = sum(int(row["rescue_correct"]) for row in rows)
    return {
        "events": len(rows),
        "v4": {
            "top1": statistics.fmean(int(row["v4_top1"]) for row in rows),
            "top3": statistics.fmean(int(row["v4_top3"]) for row in rows),
            "top5": statistics.fmean(int(row["v4_top5"]) for row in rows),
            "mrr": statistics.fmean(float(row["v4_mrr"]) for row in rows),
            "exam": statistics.fmean(float(row["v4_exam"]) for row in rows),
        },
        "v52_supplemental_review": {
            "rescue_activations": activations,
            "correct_rescues": correct_rescues,
            "incremental_rescue_hits": sum(
                int(row["incremental_rescue_hit"]) for row in rows
            ),
            "rescue_precision": correct_rescues / activations if activations else 0.0,
            "review6_hits": sum(int(row["review6_hit"]) for row in rows),
            "correct_exception_exposures": sum(
                int(row["correct_exception_exposure"]) for row in rows
            ),
            "review6_is_not_top5": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the locked joint independent study")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--exceptions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-events", type=int, default=15)
    parser.add_argument("--commitment", type=Path)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty score directory: {args.output}")
    try:
        files, lock = verify_joint_lock(args.lock)
        rankings = _read_csv(files["v4_rankings"])
        decisions = _read_csv(files["v52_decisions"])
        labels = _read_csv(args.labels)
        exceptions = _read_csv(args.exceptions)
        commitment = (
            json.loads(args.commitment.read_text(encoding="utf-8"))
            if args.commitment else None
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Joint blind scoring refused: {exc}") from exc

    if args.expected_events < 1:
        raise SystemExit("expected-events must be positive")
    label_ids = [row.get("instance_id", "") for row in labels]
    if (
        len(labels) != args.expected_events
        or any(not value for value in label_ids)
        or len(set(label_ids)) != args.expected_events
    ):
        raise SystemExit(
            f"Labels must contain exactly {args.expected_events} unique non-empty "
            "instance_id values"
        )
    previous_ids: set[str] = set()
    new_ids: set[str] = set(label_ids)
    if commitment is not None:
        if int(commitment.get("expected_total_events", -1)) != args.expected_events:
            raise SystemExit("Commitment event count does not match expected-events")
        expected_labels_hash = str(commitment.get("labels_sha256", "")).upper()
        expected_exceptions_hash = str(commitment.get("exceptions_sha256", "")).upper()
        if sha256_file(args.labels).upper() != expected_labels_hash:
            raise SystemExit("Labels SHA-256 does not match the preregistered commitment")
        if sha256_file(args.exceptions).upper() != expected_exceptions_hash:
            raise SystemExit("Exceptions SHA-256 does not match the preregistered commitment")
        previous_ids = set(commitment.get("previously_revealed_ids", []))
        new_ids = set(commitment.get("new_blind_ids", []))
        if previous_ids & new_ids or previous_ids | new_ids != set(label_ids):
            raise SystemExit("Commitment cohort IDs do not partition the label IDs exactly")
    decision_by_id = {row["instance_id"]: row for row in decisions}
    exception_by_id = {
        row["instance_id"]: _cells(row.get("exception_cells", "") or row.get("exception_cell", ""))
        for row in exceptions
    }
    if set(label_ids) != set(decision_by_id) or set(label_ids) != set(exception_by_id):
        raise SystemExit("Prediction, label, and exception instance_id sets must match exactly")
    ranking_by_id: dict[str, list[dict[str, str]]] = {instance_id: [] for instance_id in label_ids}
    for row in rankings:
        ranking_by_id.setdefault(row["instance_id"], []).append(row)

    event_rows = []
    for label in labels:
        instance_id = label["instance_id"]
        sources = _sources(label)
        rows = sorted(ranking_by_id[instance_id], key=lambda row: int(row["rank"]))
        total = int(rows[0]["formula_count"])
        if (
            len(rows) != total
            or [int(row["rank"]) for row in rows] != list(range(1, total + 1))
            or len({row["cell"] for row in rows}) != total
        ):
            raise SystemExit(f"Incomplete V4 ranking for {instance_id}")
        source_rows = [row for row in rows if row["cell"] in sources]
        rank = min((int(row["rank"]) for row in source_rows), default=total + 1)
        source_row = min(source_rows, key=lambda row: int(row["rank"])) if source_rows else None
        decision = decision_by_id[instance_id]
        if decision["v4_order_sha256"] != decision["v52_core_order_sha256"]:
            raise SystemExit(f"Core non-interference failure for {instance_id}")
        rescue_cell = decision["rescue_cell"]
        rescue_active = bool(rescue_cell)
        rescue_correct = rescue_cell in sources if rescue_active else False
        incremental = bool(rescue_correct and rank > 5)
        exception_exposure = bool(
            rescue_active and rescue_cell in exception_by_id.get(instance_id, set())
        )
        correct_formula = label.get("correct_formula", "")
        repair = source_row.get("candidate_formula", "") if source_row else ""
        repair_exact = bool(
            len(sources) == 1 and correct_formula and repair
            and normalized_formula(correct_formula) == normalized_formula(repair)
        )
        rescue_repair = decision.get("rescue_candidate_formula", "")
        rescue_repair_exact = bool(
            rescue_correct and len(sources) == 1 and correct_formula and rescue_repair
            and normalized_formula(correct_formula) == normalized_formula(rescue_repair)
        )
        event_rows.append({
            "instance_id": instance_id,
            "evidence_cohort": (
                "previously_revealed" if instance_id in previous_ids else "new_independent"
            ),
            "formula_count": total,
            "source_cells": ";".join(sorted(sources)),
            "v4_rank": rank,
            "v4_top1": int(rank <= 1),
            "v4_top3": int(rank <= 3),
            "v4_top5": int(rank <= 5),
            "v4_mrr": 1.0 / rank,
            "v4_exam": rank / max(1, total),
            "v4_candidate_formula": repair,
            "v4_repair_evaluable": int(bool(correct_formula)),
            "v4_repair_exact": int(repair_exact),
            "core_non_interference": 1,
            "rescue_active": int(rescue_active),
            "rescue_cell": rescue_cell,
            "rescue_correct": int(rescue_correct),
            "incremental_rescue_hit": int(incremental),
            "review6_hit": int(rank <= 5 or rescue_correct),
            "rescue_repair_exact": int(rescue_repair_exact),
            "correct_exception_exposure": int(exception_exposure),
        })

    args.output.mkdir(parents=True, exist_ok=True)
    event_path = args.output / "independent_scored_events.csv"
    _write_csv(event_path, event_rows)
    combined = _metric_block(event_rows)
    new_rows = [row for row in event_rows if row["instance_id"] in new_ids]
    previous_rows = [row for row in event_rows if row["instance_id"] in previous_ids]
    new_review = new_rows and _metric_block(new_rows)["v52_supplemental_review"]
    activations = int(new_review["rescue_activations"]) if new_review else 0
    correct_rescues = int(new_review["correct_rescues"]) if new_review else 0
    incremental_hits = int(new_review["incremental_rescue_hits"]) if new_review else 0
    exception_exposures = int(new_review["correct_exception_exposures"]) if new_review else 0
    core_invariant = all(int(row["core_non_interference"]) for row in event_rows)
    rescue_precision = correct_rescues / activations if activations else 0.0
    gates = {
        "all_expected_events_scored": len(event_rows) == args.expected_events,
        "core_top5_exactly_v4": core_invariant,
        "at_least_two_new_incremental_rescue_hits": incremental_hits >= 2,
        "rescue_precision_at_least_50_percent": rescue_precision >= 0.50,
        "new_correct_exception_exposure_at_most_20_percent": (
            exception_exposures <= math.floor(0.20 * len(new_rows))
        ),
    }
    summary = {
        "scope": f"{args.expected_events}_event_combined_case_set_with_cohort_separation",
        "prediction_lock_verified": True,
        "events": len(event_rows),
        "v4": combined["v4"],
        "v52_supplemental_review": combined["v52_supplemental_review"],
        "new_independent_cohort": _metric_block(new_rows),
        "previously_revealed_cohort": _metric_block(previous_rows),
        "formal_auxiliary_module_gates": gates,
        "decision": (
            "v52_supported_as_safe_supplemental_review_module"
            if all(gates.values()) else "v4_remains_primary_v52_is_exploratory"
        ),
        "claim_boundary": (
            f"Only the {len(new_rows)} newly blinded events are new independent evidence; "
            f"the {len(previous_rows)} previously revealed events are reported separately."
        ),
        "lock": lock,
        "labels_sha256": sha256_file(args.labels),
        "exceptions_sha256": sha256_file(args.exceptions),
        "commitment_sha256": sha256_file(args.commitment) if args.commitment else None,
        "scored_events_sha256": sha256_file(event_path),
    }
    summary_path = args.output / "independent_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)


if __name__ == "__main__":
    main()

