"""Independently verify and seal complete V5-PSL prediction shards."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl_protocol import (
    PREDICTION_METHODS,
    combined_shards_sha256,
    sha256,
    validate_public_manifest,
)
from scripts.run_v5_psl_predictions import (
    FORBIDDEN_SECRET_NAMES,
    _validate_public_metadata,
    _verify_public_commitments,
    audit_prediction_shard,
    git_head,
    verify_candidate_lock,
)


def _validate_prediction_inventory(
    predictions: Path,
    rows: list[dict[str, str]],
    prediction_lock_path: Path | None,
) -> None:
    expected_files = {
        "prediction_metadata.json",
        "prediction_complete.json",
        *(f"shards/{row['instance_id']}.json" for row in rows),
    }
    if prediction_lock_path is not None and prediction_lock_path.exists():
        try:
            expected_files.add(
                prediction_lock_path.resolve().relative_to(predictions.resolve()).as_posix()
            )
        except ValueError:
            pass
    observed_files = {
        path.relative_to(predictions).as_posix()
        for path in predictions.rglob("*") if path.is_file() or path.is_symlink()
    }
    symlinks = sorted(
        path.relative_to(predictions).as_posix()
        for path in predictions.rglob("*") if path.is_symlink()
    )
    if symlinks:
        raise ValueError(f"Prediction directory contains symbolic links: {symlinks}")
    if observed_files != expected_files:
        raise ValueError(
            "Prediction directory file inventory differs: "
            f"missing={sorted(expected_files - observed_files)}, "
            f"extra={sorted(observed_files - expected_files)}"
        )


def verify_prediction_run(
    public_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    *,
    prediction_lock_path: Path | None = None,
) -> dict[str, object]:
    candidate = verify_candidate_lock(candidate_lock_path)
    rows = validate_public_manifest(public_root / "manifest.csv", public_root)
    _validate_public_metadata(public_root, rows)
    commitments = _verify_public_commitments(public_root, candidate)
    if any((public_root / name).exists() for name in FORBIDDEN_SECRET_NAMES):
        raise ValueError("A secret component is present in the public directory")
    if any((predictions / name).exists() for name in FORBIDDEN_SECRET_NAMES):
        raise ValueError("A secret component is present in the prediction directory")

    _validate_prediction_inventory(predictions, rows, prediction_lock_path)

    metadata_path = predictions / "prediction_metadata.json"
    completion_path = predictions / "prediction_complete.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    expected_metadata = {
        "protocol": "v5_psl_label_free_prediction_run_v1",
        "manifest_sha256": sha256(public_root / "manifest.csv"),
        "public_metadata_sha256": sha256(public_root / "public_metadata.json"),
        "precommit_sha256": sha256(public_root / "secret_precommit_sha256.txt"),
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "candidate_id": candidate["candidate_id"],
        "git_commit": git_head(),
        "prediction_methods": list(PREDICTION_METHODS),
        "instance_count": len(rows),
        "label_inputs": [],
        "secret_files_read": [],
        "public_archive_sha256": candidate[
            "third_party_commitments_received_before_lock"
        ]["public_archive_sha256"],
    }
    for field, expected in expected_metadata.items():
        if metadata.get(field) != expected:
            raise ValueError(f"Prediction metadata field changed: {field}")
    if completion.get("protocol") != "v5_psl_prediction_completion_v1":
        raise ValueError("Prediction completion protocol is invalid")
    if completion.get("complete") is not True or completion.get("full_ranking_audit_passed") is not True:
        raise ValueError("Prediction completion or full-ranking audit is missing")
    if completion.get("metadata_sha256") != sha256(metadata_path):
        raise ValueError("Prediction metadata changed after completion")
    if completion.get("methods") != list(PREDICTION_METHODS):
        raise ValueError("Prediction completion method inventory changed")

    rows_by_id = {row["instance_id"]: row for row in rows}
    shards = sorted((predictions / "shards").glob("*.json"))
    if len(shards) != len(rows) or {path.stem for path in shards} != set(rows_by_id):
        raise ValueError("Prediction shards do not cover the public manifest exactly")
    for path in shards:
        audit_prediction_shard(
            path, rows_by_id[path.stem], public_root, recompute=True,
        )
    combined = combined_shards_sha256(shards)
    if completion.get("combined_shards_sha256") != combined:
        raise ValueError("Prediction shards changed after completion")
    if completion.get("instances") != len(rows):
        raise ValueError("Prediction completion count is invalid")

    return {
        "protocol": "v5_psl_prediction_lock_v1",
        "locked": True,
        "locked_at_utc": datetime.now(UTC).isoformat(),
        "candidate_id": candidate["candidate_id"],
        "git_commit": git_head(),
        "instances": len(rows),
        "methods": list(PREDICTION_METHODS),
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "manifest_sha256": sha256(public_root / "manifest.csv"),
        "public_metadata_sha256": sha256(public_root / "public_metadata.json"),
        "secret_precommit_sha256": sha256(public_root / "secret_precommit_sha256.txt"),
        "secret_archive_commitment": commitments["SECRET.zip"],
        "public_archive_commitment": candidate[
            "third_party_commitments_received_before_lock"
        ]["public_archive_sha256"],
        "prediction_metadata_sha256": sha256(metadata_path),
        "prediction_completion_sha256": sha256(completion_path),
        "combined_shards_sha256": combined,
        "full_ranking_audit_passed": True,
        "labels_read": [],
        "secret_files_read": [],
        "secret_release_authorized": True,
        "post_lock_prediction_changes_forbidden": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and seal V5-PSL predictions")
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--candidate-lock", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    predictions = args.predictions.resolve()
    output = args.output.resolve() if args.output else predictions / "prediction_lock.json"
    if output.exists():
        raise SystemExit(f"Prediction lock already exists; refusing to rewrite it: {output}")
    try:
        payload = verify_prediction_run(
            args.public.resolve(), args.candidate_lock.resolve(), predictions,
            prediction_lock_path=output,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V5-PSL prediction lock refused: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(f"prediction_lock_sha256={sha256(output)}")


if __name__ == "__main__":
    main()
