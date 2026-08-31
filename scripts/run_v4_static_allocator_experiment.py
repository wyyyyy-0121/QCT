"""Evaluate the exploratory coverage-gated V4/static slot allocator."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_static_allocator import (
    ARCHITECTURE,
    DEFAULT_V4_PREFIX,
    MODEL_VERSION,
    REVIEW_BUDGET,
    UNSUPPORTED_V4_PREFIX,
    static_allocation_decision,
)
from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    DEFAULT_V4,
    load_event_rows,
    load_shards,
    reject_protected,
    sha256,
    stable_hash,
)
from scripts.run_v4_rrc_required_baselines import write_immutable
from scripts.run_v4_static_fifth_experiment import (
    DEFAULT_STATIC,
    git_commit,
    load_static,
    relative,
    score,
)


PROTOCOL = "formulaguard_v4_static_allocator_exploratory_v1"
DEFAULT_OUTPUT = ROOT / "results/v4_static_allocator_exploratory"


def predict(
    v4: Mapping[str, Mapping[str, object]],
    static: Mapping[str, Mapping[str, object]],
    output_dir: Path,
) -> dict[str, dict[str, object]]:
    if set(v4) != set(static):
        raise ValueError("V4 and static unit inventories differ")
    predictions: dict[str, dict[str, object]] = {}
    for unit_id in sorted(v4):
        v4_cells = [str(row["cell"]) for row in v4[unit_id]["ranking"]]
        static_payload = static[unit_id]["v5_psl_static_anchor"]
        static_cells = [str(cell) for cell in static_payload["ranking"]]
        static_state = str(static_payload["state"])
        decision = static_allocation_decision(
            v4_cells, static_cells, static_state=static_state,
        )
        payload: dict[str, object] = {
            "protocol": PROTOCOL,
            "model_version": MODEL_VERSION,
            "unit_id": unit_id,
            "workbook_sha256": v4[unit_id]["workbook_sha256"],
            "ranking": list(decision.ranking),
            "top5": list(decision.top5),
            "static_state": static_state,
            "v4_prefix_quota": decision.v4_prefix,
            "static_candidates": list(decision.static_candidates),
            "displaced_v4_cells": list(decision.displaced_v4_cells),
            "changed": decision.changed,
            "label_inputs": [],
            "protected_data_inputs": [],
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
        path = output_dir / "shards" / (unit_id.split(":", 1)[1] + ".json")
        write_immutable(path, encoded)
        predictions[unit_id] = payload
    return predictions


def run(
    *,
    events_path: Path,
    v4_dir: Path,
    static_dir: Path,
    output_dir: Path,
) -> Path:
    for path in (events_path, v4_dir, static_dir, output_dir):
        reject_protected(path)
    v4, v4_complete = load_shards(v4_dir, kind="V4")
    static, static_receipt = load_static(static_dir)
    predictions = predict(v4, static, output_dir)

    events = load_event_rows(events_path)
    summary, event_rows = score(events, predictions)
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(event_rows, key=lambda row: str(row["event_id"]))
    ).encode()
    write_immutable(output_dir / "event_scores.jsonl", event_bytes)
    shard_hash = hashlib.sha256()
    for path in sorted((output_dir / "shards").glob("*.json")):
        shard_hash.update(path.name.encode() + b"\0" + bytes.fromhex(sha256(path)))
    prefix_counts: dict[str, int] = {}
    for row in predictions.values():
        key = str(row["v4_prefix_quota"])
        prefix_counts[key] = prefix_counts.get(key, 0) + 1
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "source_lock_git_commit": git_commit(),
        "model": {
            "version": MODEL_VERSION,
            "architecture": ARCHITECTURE,
            "review_budget": REVIEW_BUDGET,
            "default_v4_prefix": DEFAULT_V4_PREFIX,
            "unsupported_v4_prefix": UNSUPPORTED_V4_PREFIX,
            "formal_v5_authorized": False,
        },
        "parameter_selection_disclosure": {
            "role": "exploratory_public_development",
            "selected_condition": "static_state_equals_unsupported",
            "condition_source": "label_free_formula_evaluation_coverage_state",
            "observed_labels_used_for_condition_selection": True,
            "learned_weights": 0,
            "numeric_thresholds": 0,
        },
        "inputs": {
            "events_for_scoring_only": {
                "path": relative(events_path),
                "sha256": sha256(events_path),
            },
            "v4": {
                "path": relative(v4_dir),
                "combined_shards_sha256": v4_complete["combined_shards_sha256"],
            },
            "static": {
                "path": relative(static_dir),
                "receipt_sha256": static_receipt["receipt_sha256"],
            },
        },
        "counts": {
            "units": len(predictions),
            "events": len(events),
            "error_events": len(event_rows),
            "changed_units": sum(bool(row["changed"]) for row in predictions.values()),
            "v4_prefix_allocations": prefix_counts,
        },
        "summary": summary,
        "artifacts": {
            "event_scores": {
                "path": relative(output_dir / "event_scores.jsonl"),
                "sha256": hashlib.sha256(event_bytes).hexdigest(),
            },
            "combined_shards_sha256": shard_hash.hexdigest(),
        },
        "label_boundary": {
            "prediction_label_inputs": [],
            "labels_opened_after_all_prediction_shards": True,
        },
        "protected_data_inputs": [],
        "project_generated_240_120_used_for_selection": False,
        "next_confirmation_requires_new_non_saturated_data": True,
    }
    payload["receipt_sha256"] = stable_hash(payload)
    receipt = output_dir / "receipt.json"
    write_immutable(
        receipt,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(),
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    receipt = run(
        events_path=args.events.resolve(),
        v4_dir=args.v4.resolve(),
        static_dir=args.static.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
