"""Evaluate the exploratory V4 top-four plus peer-disagreement fifth ranker."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_peer_fifth import (
    ARCHITECTURE,
    MODEL_VERSION,
    REVIEW_BUDGET,
    V4_PREFIX,
    peer_fifth_decision,
)
from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    DEFAULT_SIGNALS,
    DEFAULT_V4,
    load_event_rows,
    load_shards,
    reject_protected,
    sha256,
    stable_hash,
)
from scripts.run_v4_rrc_required_baselines import write_immutable
from scripts.run_v4_static_fifth_experiment import git_commit, relative, score


PROTOCOL = "formulaguard_v4_peer_fifth_exploratory_v1"
DEFAULT_OUTPUT = ROOT / "results/v4_peer_fifth_exploratory"


def predict(
    v4: Mapping[str, Mapping[str, object]],
    signals: Mapping[str, Mapping[str, object]],
    output_dir: Path,
) -> dict[str, dict[str, object]]:
    if set(v4) != set(signals):
        raise ValueError("V4 and peer-signal unit inventories differ")
    predictions: dict[str, dict[str, object]] = {}
    for unit_id in sorted(v4):
        v4_cells = [str(row["cell"]) for row in v4[unit_id]["ranking"]]
        audit = signals[unit_id]["audit"]
        if audit.get("label_inputs") != []:
            raise ValueError(f"peer signal consumed labels: {unit_id}")
        peer_review = [str(cell) for cell in audit["review_cells"]["peer"]]
        decision = peer_fifth_decision(v4_cells, peer_review)
        payload: dict[str, object] = {
            "protocol": PROTOCOL,
            "model_version": MODEL_VERSION,
            "unit_id": unit_id,
            "workbook_sha256": v4[unit_id]["workbook_sha256"],
            "ranking": list(decision.ranking),
            "top5": list(decision.top5),
            "proposed_peer": decision.proposed_peer,
            "selected_peer": decision.selected_peer,
            "displaced_v4_fifth": decision.displaced_v4_fifth,
            "changed": decision.changed,
            "peer_audit_sha256": audit["audit_sha256"],
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
    signal_dir: Path,
    output_dir: Path,
) -> Path:
    for path in (events_path, v4_dir, signal_dir, output_dir):
        reject_protected(path)
    v4, v4_complete = load_shards(v4_dir, kind="V4")
    signals, signal_complete = load_shards(signal_dir, kind="peer signal")
    predictions = predict(v4, signals, output_dir)

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
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "source_lock_git_commit": git_commit(),
        "model": {
            "version": MODEL_VERSION,
            "architecture": ARCHITECTURE,
            "review_budget": REVIEW_BUDGET,
            "immutable_v4_prefix": V4_PREFIX,
            "learned_weights": 0,
            "numeric_thresholds": 0,
            "formal_v5_authorized": False,
        },
        "parameter_selection_disclosure": {
            "role": "exploratory_public_development",
            "selected_channel": "peer_disagreement",
            "selected_channel_labels_observed": True,
            "slot_policy": "first_peer_review_cell_only_else_preserve_v4",
            "alternative_static_fallback_rejected": "small_gain_with_additional_v4_hit_loss",
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
            "peer_signals": {
                "path": relative(signal_dir),
                "combined_shards_sha256": signal_complete["combined_shards_sha256"],
                "label_inputs": signal_complete["label_inputs_to_prediction"],
            },
        },
        "counts": {
            "units": len(predictions),
            "events": len(events),
            "error_events": len(event_rows),
            "changed_units": sum(bool(row["changed"]) for row in predictions.values()),
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
        "next_confirmation_requires_unseen_real_revision_data": True,
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
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    receipt = run(
        events_path=args.events.resolve(),
        v4_dir=args.v4.resolve(),
        signal_dir=args.signals.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
