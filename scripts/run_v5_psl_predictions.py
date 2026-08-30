"""Resumable label-free predictions for the V5-PSL independent corpus."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.localize import LocalizationResult, v4_scores
from formulaguard.v4x import v4_3_scores
from formulaguard.v5_psl import diagnose_v5_psl, v5_psl_default_parameters
from formulaguard.v5_psl_protocol import (
    DEFAULT_WORKERS,
    DIAGNOSTIC_STATES,
    PREDICTION_METHODS,
    aggregate_file_sha256,
    canonical_cell,
    canonical_json_sha256,
    combined_shards_sha256,
    deterministic_zip_sha256,
    model_output_projection,
    read_csv,
    read_sha256_commitments,
    safe_path,
    sha256,
    validate_complete_ranking,
    validate_public_manifest,
)
from formulaguard.v52 import v52_from_v4
from formulaguard.workbook import WorkbookModel
from scripts.freeze_v5_psl_candidate import BASELINE_POLICY, candidate_source_files


FORBIDDEN_SECRET_NAMES = {
    "cases.csv", "third_party_declaration.json",
    "design_audit.json", "case_validation.csv", "custodian_id_mapping.csv",
    "SECRET.zip",
}
REQUIRED_CANDIDATE_SOURCES = set(candidate_source_files())


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=False,
    )
    if completed.returncode:
        raise ValueError("Unable to resolve the Git commit")
    return completed.stdout.strip()


def git_worktree_clean() -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        raise ValueError("Unable to inspect the Git worktree")
    return not completed.stdout.strip()


def verify_candidate_lock(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol") != "v5_psl_candidate_lock_v1":
        raise ValueError("Candidate lock protocol is invalid")
    if payload.get("candidate_locked") is not True or payload.get("formal_version") is not None:
        raise ValueError("Candidate lock must be active and must not claim a formal V5 version")
    head = git_head()
    if payload.get("candidate_id") != f"v5-psl-dev1-{head[:12]}":
        raise ValueError("Candidate lock identifier differs from the locked Git commit")
    if payload.get("formal_promotion_requires_third_party_240_120_pass") is not True:
        raise ValueError("Candidate lock does not preserve the formal promotion gate")
    if payload.get("third_party_labels_seen") is not False:
        raise ValueError("Candidate lock does not attest that third-party labels remain unseen")
    if payload.get("third_party_public_seen") is not False:
        raise ValueError("Candidate lock was not created before PUBLIC release")
    commitments = payload.get("third_party_commitments_received_before_lock")
    if (
        not isinstance(commitments, dict)
        or set(commitments) != {"public_archive_sha256", "secret_archive_sha256"}
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(value))
            for value in commitments.values()
        )
        or len(set(commitments.values())) != 2
    ):
        raise ValueError("Candidate lock third-party archive commitments are invalid")
    if canonical_json_sha256(payload.get("parameters")) != canonical_json_sha256(
        v5_psl_default_parameters()
    ):
        raise ValueError("Candidate lock parameters differ from the implementation defaults")
    expected_methods = list(PREDICTION_METHODS)
    if payload.get("prediction_methods") != expected_methods:
        raise ValueError("Candidate lock baseline list differs from the protocol")
    if payload.get("baseline_policy") != BASELINE_POLICY:
        raise ValueError("Candidate lock baseline action policy differs from the protocol")
    signatures = payload.get("development_formula_change_signatures")
    if (
        not isinstance(signatures, list) or not signatures
        or any(not isinstance(value, str) for value in signatures)
        or signatures != sorted(set(signatures))
        or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in signatures)
    ):
        raise ValueError("Candidate lock development transformation inventory is invalid")
    if payload.get("development_formula_change_signatures_sha256") != canonical_json_sha256(
        sorted(signatures)
    ):
        raise ValueError("Candidate lock development transformation hash is invalid")
    if payload.get("claim_matrix_sha256") != sha256(
        ROOT / "research/V5_PSL_CLAIM_MATRIX.md"
    ):
        raise ValueError("Candidate lock claim matrix hash is invalid")
    for field in (
        "literature_reviewed_sources_sha256", "literature_gate_sha256",
        "pressure_audit_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get(field, ""))):
            raise ValueError(f"Candidate lock {field} is invalid")
    if not re.fullmatch(
        r"[0-9a-f]{64}",
        str(payload.get("development_formula_change_signatures_file_sha256", "")),
    ):
        raise ValueError("Candidate lock development signature file hash is invalid")
    environment = payload.get("environment")
    if not isinstance(environment, dict) or not environment.get("libreoffice"):
        raise ValueError("Candidate lock lacks the required LibreOffice environment record")
    if payload.get("git_commit") != head:
        raise ValueError("Current HEAD differs from the candidate lock commit")
    if payload.get("clean_git_worktree_required_for_prediction") is not True:
        raise ValueError("Candidate lock does not require a clean prediction worktree")
    if not git_worktree_clean():
        raise ValueError("Candidate-locked prediction requires a clean Git worktree")
    if payload.get("third_party_files_read") != [] or payload.get("post_lock_tuning_forbidden") is not True:
        raise ValueError("Candidate lock third-party boundary or tuning prohibition is invalid")
    if (
        payload.get("historical_source_hashes_verified") is not True
        or payload.get("tag_created_by_this_script") is not False
    ):
        raise ValueError("Candidate lock historical-source or tag boundary is invalid")
    source_hashes = payload.get("source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("Candidate lock source inventory is empty")
    if set(source_hashes) != REQUIRED_CANDIDATE_SOURCES:
        raise ValueError(
            "Candidate lock source inventory differs: "
            f"missing={sorted(REQUIRED_CANDIDATE_SOURCES - set(source_hashes))}, "
            f"extra={sorted(set(source_hashes) - REQUIRED_CANDIDATE_SOURCES)}"
        )
    for relative, expected in source_hashes.items():
        source = safe_path(ROOT, str(relative))
        if sha256(source) != expected:
            raise ValueError(f"Candidate-locked source changed: {relative}")
    return payload


def _ranking_rows(results: Sequence[LocalizationResult]) -> list[dict[str, object]]:
    return [
        {
            "rank": rank,
            "cell": result.cell_label,
            "score": result.score,
            "candidate_formula": result.candidate_formula,
            "evidence": result.evidence,
        }
        for rank, result in enumerate(results, 1)
    ]


def _fixed_review_method(
    results: Sequence[LocalizationResult],
    elapsed: float,
    *,
    model_version: str,
) -> dict[str, object]:
    return {
        "model_version": model_version,
        "state": "review",
        "action_cells": [row.cell_label for row in results[:5]],
        "ranking": _ranking_rows(results),
        "runtime_seconds": elapsed,
    }


def predict_workbook(workbook: Path, instance_id: str, workbook_label: str) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(workbook)

    started = time.perf_counter()
    v4 = v4_scores(model, candidate_limit=15)
    v4_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    review = v52_from_v4(model, v4, variant="b", candidate_limit=15)
    review_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    semantic = v4_3_scores(
        model, variant="c", base_candidate_limit=15, semantic_candidate_limit=25,
    )
    semantic_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    psl = diagnose_v5_psl(model)
    psl_elapsed = time.perf_counter() - started
    psl_payload = psl.as_dict()
    psl_payload["action_cells"] = psl_payload.pop("review_cells")
    psl_payload["runtime_seconds"] = psl_elapsed

    methods = {
        "v4_r1": _fixed_review_method(v4, v4_elapsed, model_version="v4-dev-r1"),
        "v4_2_review_b": {
            "model_version": "v4.2-review-b",
            "state": "review",
            "action_cells": [row.cell_label for row in review.review_set],
            "ranking": _ranking_rows(review.core_ranking),
            "runtime_seconds": review_elapsed,
            "decision": {
                "status": review.status,
                "reason": review.reason,
                "rescue_cell": review.rescue.result.cell_label if review.rescue else None,
                "eligible_candidates": len(review.eligible),
            },
        },
        "v4_3_semantic_c": _fixed_review_method(
            semantic, semantic_elapsed, model_version="v4.3-semantic-c",
        ),
        "v5_psl_dev1": psl_payload,
    }
    return {
        "protocol": "v5_psl_label_free_prediction_shard_v1",
        "instance_id": instance_id,
        "workbook": workbook_label,
        "workbook_sha256": sha256(workbook),
        "formula_count": len(model.formulas),
        "methods": methods,
        "label_inputs": [],
    }


def audit_prediction_shard(
    path: Path,
    public_row: Mapping[str, str],
    public_root: Path,
    *,
    recompute: bool = False,
) -> dict[str, object]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid prediction shard {path.name}: {exc}") from exc
    if record.get("protocol") != "v5_psl_label_free_prediction_shard_v1":
        raise ValueError(f"Unexpected shard protocol: {path.name}")
    if record.get("instance_id") != public_row["instance_id"]:
        raise ValueError(f"Shard instance mismatch: {path.name}")
    if record.get("workbook") != public_row["workbook"] or record.get("label_inputs") != []:
        raise ValueError(f"Shard public input boundary failed: {path.name}")
    workbook = safe_path(public_root, public_row["workbook"])
    if record.get("workbook_sha256") != sha256(workbook):
        raise ValueError(f"Shard workbook hash changed: {path.name}")
    model = WorkbookModel.from_xlsx(workbook)
    formula_cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
    canonical_formulas = {canonical_cell(cell) for cell in formula_cells}
    if record.get("formula_count") != len(formula_cells):
        raise ValueError(f"Shard formula count is invalid: {path.name}")
    methods = record.get("methods")
    if not isinstance(methods, dict) or tuple(methods) != PREDICTION_METHODS:
        raise ValueError(f"Shard method inventory is invalid: {path.name}")
    for method_name, payload in methods.items():
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid method payload {method_name}: {path.name}")
        ranking = payload.get("ranking")
        if not isinstance(ranking, list):
            raise ValueError(f"Missing complete ranking {method_name}: {path.name}")
        validate_complete_ranking(ranking, formula_cells)
        action_cells = payload.get("action_cells")
        if not isinstance(action_cells, list):
            raise ValueError(f"Invalid action cells {method_name}: {path.name}")
        canonical_actions = [canonical_cell(cell) for cell in action_cells]
        if len(canonical_actions) != len(set(canonical_actions)):
            raise ValueError(f"Invalid action cells {method_name}: {path.name}")
        if not set(canonical_actions) <= canonical_formulas:
            raise ValueError(f"Action cells are not formula cells {method_name}: {path.name}")
    v4_cells = [canonical_cell(row["cell"]) for row in methods["v4_r1"]["ranking"]]
    v42_cells = [canonical_cell(row["cell"]) for row in methods["v4_2_review_b"]["ranking"]]
    if v42_cells != v4_cells:
        raise ValueError(f"V4.2 changed the frozen V4 core order: {path.name}")
    fixed_count = min(5, len(formula_cells))
    expected_versions = {
        "v4_r1": "v4-dev-r1",
        "v4_2_review_b": "v4.2-review-b",
        "v4_3_semantic_c": "v4.3-semantic-c",
        "v5_psl_dev1": "v5-psl-dev1-rev1",
    }
    if any(
        methods[name].get("model_version") != version
        for name, version in expected_versions.items()
    ):
        raise ValueError(f"Prediction method version changed: {path.name}")
    if methods["v4_r1"].get("state") != "review":
        raise ValueError(f"V4 fixed review state failed: {path.name}")
    v4_actions = [canonical_cell(cell) for cell in methods["v4_r1"]["action_cells"]]
    if v4_actions != v4_cells[:fixed_count]:
        raise ValueError(f"V4 fixed Top-5 policy failed: {path.name}")
    semantic_cells = [
        canonical_cell(row["cell"])
        for row in methods["v4_3_semantic_c"]["ranking"]
    ]
    semantic_actions = [
        canonical_cell(cell) for cell in methods["v4_3_semantic_c"]["action_cells"]
    ]
    if (
        methods["v4_3_semantic_c"].get("state") != "review"
        or semantic_actions != semantic_cells[:fixed_count]
    ):
        raise ValueError(f"V4.3 fixed Top-5 policy failed: {path.name}")
    v42_actions = [
        canonical_cell(cell) for cell in methods["v4_2_review_b"]["action_cells"]
    ]
    if v42_actions[:fixed_count] != v4_cells[:fixed_count]:
        raise ValueError(f"V4.2 review set does not preserve V4 Top-5: {path.name}")
    if len(methods["v4_2_review_b"]["action_cells"]) not in {fixed_count, fixed_count + 1}:
        raise ValueError(f"V4.2 review budget is invalid: {path.name}")
    decision = methods["v4_2_review_b"].get("decision")
    if methods["v4_2_review_b"].get("state") != "review" or not isinstance(decision, dict):
        raise ValueError(f"V4.2 review decision is invalid: {path.name}")
    rescue = decision.get("rescue_cell")
    expected_v42_actions = v4_cells[:fixed_count] + (
        [canonical_cell(str(rescue))] if rescue is not None else []
    )
    if v42_actions != expected_v42_actions:
        raise ValueError(f"V4.2 rescue slot differs from its decision: {path.name}")
    psl = methods["v5_psl_dev1"]
    if psl.get("state") not in DIAGNOSTIC_STATES:
        raise ValueError(f"V5-PSL state is invalid: {path.name}")
    expected_actions = {"localized": 1, "review": fixed_count}.get(str(psl["state"]), 0)
    if len(psl["action_cells"]) != expected_actions:
        raise ValueError(f"V5-PSL selective action budget is invalid: {path.name}")
    psl_cells = [canonical_cell(row["cell"]) for row in psl["ranking"]]
    psl_actions = [canonical_cell(cell) for cell in psl["action_cells"]]
    if psl_actions != psl_cells[:expected_actions]:
        raise ValueError(f"V5-PSL action cells differ from its ranking: {path.name}")
    if recompute:
        expected = predict_workbook(workbook, public_row["instance_id"], public_row["workbook"])
        if model_output_projection(record) != model_output_projection(expected):
            raise ValueError(f"Prediction shard does not reproduce from the locked model: {path.name}")
    return record


def _task(payload: tuple[str, str, str, str]) -> str:
    public_text, output_text, instance_id, workbook_label = payload
    public_root = Path(public_text)
    output = Path(output_text)
    workbook = safe_path(public_root, workbook_label)
    record = predict_workbook(workbook, instance_id, workbook_label)
    shard = output / "shards" / f"{instance_id}.json"
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return instance_id


def _validate_public_metadata(public_root: Path, rows: Sequence[Mapping[str, str]]) -> dict[str, object]:
    metadata_path = public_root / "public_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("protocol") != "v5_psl_single_custodian_pack_v2":
        raise ValueError("Public package metadata protocol is invalid")
    if metadata.get("manifest_sha256") != sha256(public_root / "manifest.csv"):
        raise ValueError("Public manifest differs from package metadata")
    if metadata.get("workbook_hashes_sha256") != sha256(public_root / "workbook_hashes.csv"):
        raise ValueError("Public workbook hash inventory differs from package metadata")
    if metadata.get("secret_precommit_sha256") != sha256(
        public_root / "secret_precommit_sha256.txt"
    ):
        raise ValueError("Secret precommit differs from package metadata")
    if metadata.get("case_count") != len(rows) or metadata.get("labels_in_public_manifest") != []:
        raise ValueError("Public metadata count or label boundary is invalid")
    hash_rows = read_csv(public_root / "workbook_hashes.csv")
    if not hash_rows or tuple(hash_rows[0]) != ("instance_id", "workbook", "sha256"):
        raise ValueError("workbook_hashes.csv fields are invalid")
    if {(row["instance_id"], row["workbook"]) for row in hash_rows} != {
        (row["instance_id"], row["workbook"]) for row in rows
    }:
        raise ValueError("Workbook hash inventory differs from the public manifest")
    if len(hash_rows) != len(rows):
        raise ValueError("Workbook hash inventory contains duplicate or extra rows")
    for row in hash_rows:
        if sha256(safe_path(public_root, row["workbook"])) != row["sha256"]:
            raise ValueError(f"Public workbook hash failed: {row['instance_id']}")
    aggregate = aggregate_file_sha256(
        (row["workbook"], public_root / row["workbook"]) for row in rows
    )
    if metadata.get("workbooks_aggregate_sha256") != aggregate:
        raise ValueError("Public workbook aggregate hash differs from package metadata")
    expected_files = {
        "manifest.csv", "workbook_hashes.csv", "public_metadata.json",
        "secret_precommit_sha256.txt",
        *(row["workbook"] for row in rows),
    }
    symlinks = sorted(
        path.relative_to(public_root).as_posix()
        for path in public_root.rglob("*") if path.is_symlink()
    )
    if symlinks:
        raise ValueError(f"Public package contains symbolic links: {symlinks}")
    observed_files = {
        path.relative_to(public_root).as_posix()
        for path in public_root.rglob("*") if path.is_file()
    }
    if observed_files != expected_files:
        raise ValueError(
            f"Public package file inventory differs: "
            f"missing={sorted(expected_files - observed_files)}, "
            f"extra={sorted(observed_files - expected_files)}"
        )
    return metadata


def _verify_public_commitments(
    public_root: Path,
    candidate: Mapping[str, object],
) -> dict[str, str]:
    locked = candidate["third_party_commitments_received_before_lock"]
    if not isinstance(locked, Mapping):
        raise ValueError("Candidate lock lacks third-party archive commitments")
    commitments = read_sha256_commitments(
        public_root / "secret_precommit_sha256.txt",
        required_names=FORBIDDEN_SECRET_NAMES,
    )
    if commitments["SECRET.zip"] != locked.get("secret_archive_sha256"):
        raise ValueError("SECRET precommit differs from the candidate lock")
    if deterministic_zip_sha256(public_root) != locked.get("public_archive_sha256"):
        raise ValueError("PUBLIC archive differs from the candidate lock")
    return commitments


def main() -> None:
    parser = argparse.ArgumentParser(description="Run locked, label-free V5-PSL predictions")
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--candidate-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers", type=int, default=min(DEFAULT_WORKERS, os.cpu_count() or 1),
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    public_root = args.public.resolve()
    output = args.output.resolve()
    if (output / "prediction_lock.json").exists():
        raise SystemExit("Prediction lock already exists; prediction resume is permanently closed")
    try:
        candidate = verify_candidate_lock(args.candidate_lock.resolve())
        rows = validate_public_manifest(public_root / "manifest.csv", public_root)
        public_metadata = _validate_public_metadata(public_root, rows)
        _verify_public_commitments(public_root, candidate)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V5-PSL label-free prediction refused: {exc}") from exc

    output.mkdir(parents=True, exist_ok=True)
    (output / "shards").mkdir(exist_ok=True)
    metadata = {
        "protocol": "v5_psl_label_free_prediction_run_v1",
        "public_root": str(public_root),
        "manifest_sha256": sha256(public_root / "manifest.csv"),
        "public_metadata_sha256": sha256(public_root / "public_metadata.json"),
        "precommit_sha256": sha256(public_root / "secret_precommit_sha256.txt"),
        "candidate_lock_sha256": sha256(args.candidate_lock.resolve()),
        "candidate_id": candidate["candidate_id"],
        "git_commit": git_head(),
        "worker_processes_requested": args.workers,
        "prediction_methods": list(PREDICTION_METHODS),
        "v5_psl_parameters": json.loads(json.dumps(v5_psl_default_parameters())),
        "v4_candidate_limit": 15,
        "v4_2_variant": "b",
        "v4_3_variant": "c",
        "v4_3_semantic_candidate_limit": 25,
        "instance_count": len(rows),
        "label_inputs": [],
        "public_files_read": [
            "manifest.csv", "workbook_hashes.csv", "public_metadata.json",
            "secret_precommit_sha256.txt", "workbooks/*.xlsx",
        ],
        "secret_files_read": [],
        "filename_used_as_feature": False,
        "hidden_labels_used": False,
        "package_protocol": public_metadata["protocol"],
        "public_archive_sha256": candidate[
            "third_party_commitments_received_before_lock"
        ]["public_archive_sha256"],
    }
    metadata_path = output / "prediction_metadata.json"
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous != metadata:
            raise SystemExit("Resume refused: public inputs, candidate lock, code, or parameters changed")
        if not args.resume:
            raise SystemExit("Prediction output exists; pass --resume to audit and continue")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pending = []
    rows_by_id = {row["instance_id"]: row for row in rows}
    for row in rows:
        shard = output / "shards" / f"{row['instance_id']}.json"
        if shard.exists():
            try:
                audit_prediction_shard(shard, row, public_root, recompute=True)
            except ValueError as exc:
                raise SystemExit(f"Resume refused: {exc}") from exc
            continue
        pending.append(row)
    workers = min(args.workers, max(1, len(pending)))
    print(
        f"V5-PSL scheduling: workers={workers}; pending={len(pending)}; "
        f"resumed={len(rows) - len(pending)}",
        flush=True,
    )
    payloads = [
        (str(public_root), str(output), row["instance_id"], row["workbook"])
        for row in pending
    ]
    if workers == 1:
        for index, payload in enumerate(payloads, 1):
            print(f"[{index}/{len(payloads)}] {_task(payload)}", flush=True)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_task, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"[{index}/{len(payloads)}] {future.result()}", flush=True)

    shard_paths = sorted((output / "shards").glob("*.json"))
    if {path.stem for path in shard_paths} != set(rows_by_id):
        raise SystemExit("Prediction completion refused: shard identifiers are incomplete")
    try:
        verify_candidate_lock(args.candidate_lock.resolve())
        _validate_public_metadata(public_root, rows)
        _verify_public_commitments(public_root, candidate)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Prediction completion refused after input recheck: {exc}") from exc
    for path in shard_paths:
        try:
            audit_prediction_shard(path, rows_by_id[path.stem], public_root)
        except ValueError as exc:
            raise SystemExit(f"Prediction completion refused: {exc}") from exc
    completion = {
        "protocol": "v5_psl_prediction_completion_v1",
        "complete": True,
        "instances": len(shard_paths),
        "methods": list(PREDICTION_METHODS),
        "combined_shards_sha256": combined_shards_sha256(shard_paths),
        "metadata_sha256": sha256(metadata_path),
        "full_ranking_audit_passed": True,
        "labels_may_be_released_only_after_separate_lock_verification": True,
    }
    completion_path = output / "prediction_complete.json"
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(completion_path)


if __name__ == "__main__":
    main()
