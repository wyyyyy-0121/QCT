"""Promote a verified 30-event Enron correction without deleting old evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_atomic(path: Path, payload: dict):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-root", type=Path, required=True)
    parser.add_argument("--corrected-name", default="enron_corrected_30")
    parser.add_argument("--snapshot-name", default="enron_test20_snapshot")
    args = parser.parse_args()

    root = args.round_root.resolve()
    canonical = root / "enron"
    corrected = root / args.corrected_name
    snapshot = root / args.snapshot_name
    if not canonical.is_dir() or not corrected.is_dir():
        raise SystemExit("Canonical and corrected Enron directories must both exist")
    if snapshot.exists():
        raise SystemExit(f"Snapshot destination already exists: {snapshot}")

    old_completion = load(canonical / "enron_prediction_complete.json")
    corrected_completion = load(corrected / "enron_prediction_complete.json")
    old_metadata = load(canonical / "enron_metadata.json")
    corrected_metadata = load(corrected / "enron_metadata.json")
    if old_completion.get("events") != 20:
        raise SystemExit("Canonical pre-correction result is not the expected 20-event snapshot")
    if corrected_completion.get("events") != 30 or not corrected_completion.get("full_ranking_audit_passed"):
        raise SystemExit("Corrected result is not a complete 30-event ranking")
    invariant_fields = ("variant", "v6_source_sha256", "v4_source_sha256", "method_spec_sha256")
    mismatches = [field for field in invariant_fields if old_metadata.get(field) != corrected_metadata.get(field)]
    if mismatches:
        raise SystemExit(f"Promotion refused; model metadata differs: {', '.join(mismatches)}")

    old_summary_hash = sha256(canonical / "enron_summary.json")
    corrected_summary_hash = sha256(corrected / "enron_summary.json")
    canonical.rename(snapshot)
    corrected.rename(canonical)

    reuse_path = canonical / "shard_reuse_receipt.json"
    if reuse_path.exists():
        reuse = load(reuse_path)
        reuse["source"] = snapshot.as_posix()
        reuse["target"] = canonical.as_posix()
        for entry in reuse.get("reused", []):
            target_shard = canonical / "shards" / entry["target_shard"]
            record = load(target_shard)
            provenance = record.get("reuse_provenance", {})
            provenance["source_directory"] = snapshot.as_posix()
            record["reuse_provenance"] = provenance
            write_atomic(target_shard, record)
            entry["target_shard_sha256"] = sha256(target_shard)
            source_shard = snapshot / "shards" / provenance["source_shard"]
            if sha256(source_shard) != provenance["source_shard_sha256"]:
                raise SystemExit(f"Promoted reuse source hash mismatch: {source_shard}")
        write_atomic(reuse_path, reuse)

    receipt = {
        "protocol": "v6_enron_inventory_canonical_promotion_v1",
        "round_root": root.as_posix(),
        "canonical_directory": canonical.as_posix(),
        "historical_snapshot_directory": snapshot.as_posix(),
        "historical_events": old_completion["events"],
        "corrected_events": corrected_completion["events"],
        "historical_summary_sha256": old_summary_hash,
        "corrected_summary_sha256_before_promotion": corrected_summary_hash,
        "invariant_metadata": {field: corrected_metadata[field] for field in invariant_fields},
        "old_evidence_deleted": False,
    }
    receipt_path = canonical / "inventory_correction_promotion_receipt.json"
    write_atomic(receipt_path, receipt)
    print(receipt_path)


if __name__ == "__main__":
    main()
