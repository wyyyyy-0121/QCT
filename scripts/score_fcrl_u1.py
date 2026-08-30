#!/usr/bin/env python3
"""Verify two locked FCRL U1 prediction runs and score the frozen gates."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

import torch

from formulaguard.fcrl_torch import EXPECTED_SOURCE_COMMIT
from formulaguard.fcrl_u1 import (
    prediction_content,
    score_u1_predictions,
    sha256_file,
    stable_hash,
)
from scripts.build_fcrl_u1_corpus import write_json_atomic
from scripts.freeze_fcrl_u1_candidate import LOCKED_SOURCES, PROTOCOL as LOCK_PROTOCOL
from scripts.train_fcrl_u1 import load_target_contract


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_fcrl_u1_score_v1"
PREDICTION_PROTOCOL = "formulaguard_fcrl_u1_predictions_v1"


def git(*args: str, cwd: Path = ROOT) -> str:
    completed = subprocess.run(
        ("git", *args), cwd=cwd, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _repo_path(text: object) -> Path:
    if not isinstance(text, str) or not text or "\\" in text or "\0" in text:
        raise ValueError("invalid FCRL candidate artifact path")
    candidate = (ROOT / text).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("FCRL candidate artifact escapes repository root") from exc
    return candidate


def _current_environment() -> dict[str, object]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


def verify_candidate_lock(
    path: Path,
    *,
    require_repository_lock: bool = True,
    require_pushed: bool = True,
) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    candidate_id = payload.get("candidate_id")
    identity = dict(payload)
    identity.pop("candidate_id", None)
    if (
        payload.get("protocol") != LOCK_PROTOCOL
        or payload.get("candidate_locked") is not True
        or payload.get("formal_version") is not None
        or payload.get("internal_test_decoded") is not False
        or payload.get("public_prediction_lock_complete") is not False
        or payload.get("protected_data_inputs") != []
        or candidate_id != "fcrl-u1:" + stable_hash(identity)
    ):
        raise ValueError("FCRL candidate lock identity is invalid")
    implementation_commit = str(payload.get("implementation_commit", ""))
    if not implementation_commit:
        raise ValueError("FCRL candidate lock has no implementation commit")
    try:
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", implementation_commit, "HEAD"),
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError("FCRL implementation commit is not an ancestor of HEAD") from exc

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("FCRL candidate artifacts are missing")
    for name, record in artifacts.items():
        if not isinstance(record, dict):
            raise ValueError(f"FCRL candidate artifact is invalid: {name}")
        artifact = _repo_path(record.get("path"))
        if (
            not artifact.is_file()
            or record.get("sha256") != sha256_file(artifact)
            or record.get("bytes") != artifact.stat().st_size
        ):
            raise ValueError(f"FCRL candidate artifact changed: {name}")
    source_hashes = payload.get("source_sha256")
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(LOCKED_SOURCES):
        raise ValueError("FCRL candidate source hash set changed")
    for source, digest in source_hashes.items():
        if sha256_file(_repo_path(source)) != digest:
            raise ValueError(f"FCRL locked source changed: {source}")
    source_paths = payload.get("source_paths")
    if not isinstance(source_paths, dict):
        raise ValueError("FCRL source paths are missing")
    fortap_source = _repo_path(source_paths.get("fortap_source"))
    _repo_path(source_paths.get("input_root"))
    if (
        payload.get("fortap_source_commit") != EXPECTED_SOURCE_COMMIT
        or git("rev-parse", "HEAD", cwd=fortap_source) != EXPECTED_SOURCE_COMMIT
    ):
        raise ValueError("FCRL ForTaP source commit changed")
    if payload.get("environment") != _current_environment():
        raise ValueError("FCRL frozen environment changed")

    if require_repository_lock:
        relative = path.resolve().relative_to(ROOT).as_posix()
        if git("ls-files", "--error-unmatch", relative) != relative:
            raise ValueError("FCRL candidate lock is not tracked")
        subprocess.run(
            ("git", "diff", "--quiet", "HEAD", "--", relative), cwd=ROOT, check=True
        )
        if git("status", "--porcelain", "--untracked-files=no"):
            raise ValueError("tracked worktree changed after FCRL candidate lock")
    if require_pushed:
        try:
            upstream = git("rev-parse", "@{upstream}")
        except subprocess.SubprocessError as exc:
            raise ValueError("FCRL branch has no upstream") from exc
        if upstream != git("rev-parse", "HEAD"):
            raise ValueError("FCRL candidate-lock commit has not been pushed")
    return payload


def load_prediction_file(path: Path, candidate_id: str) -> tuple[list[dict[str, object]], str]:
    payload = json.loads(path.read_text(encoding="ascii"))
    rows = payload.get("predictions")
    if (
        payload.get("protocol") != PREDICTION_PROTOCOL
        or payload.get("complete") is not True
        or payload.get("candidate_id") != candidate_id
        or payload.get("protected_data_inputs") != []
        or not isinstance(rows, list)
    ):
        raise ValueError("FCRL locked prediction file is incomplete or unsafe")
    content = prediction_content(rows)
    digest = stable_hash(content)
    if payload.get("prediction_sha256") != digest or payload.get("targets") != len(content):
        raise ValueError("FCRL locked prediction hash or count changed")
    return content, digest


def score(
    candidate_lock_path: Path,
    first_predictions: Path,
    second_predictions: Path,
    *,
    require_repository_lock: bool = True,
    require_pushed: bool = True,
) -> dict[str, object]:
    candidate = verify_candidate_lock(
        candidate_lock_path,
        require_repository_lock=require_repository_lock,
        require_pushed=require_pushed,
    )
    artifacts = candidate["artifacts"]
    assert isinstance(artifacts, dict)
    target_manifest = _repo_path(artifacts["target_manifest"]["path"])
    target_receipt = _repo_path(artifacts["target_receipt"]["path"])
    manifest, targets = load_target_contract(target_manifest, target_receipt)
    first, first_hash = load_prediction_file(first_predictions, str(candidate["candidate_id"]))
    second, second_hash = load_prediction_file(second_predictions, str(candidate["candidate_id"]))
    score_payload = score_u1_predictions(
        targets,
        manifest["global_frequency_top5_train_only"],
        first,
        repeated_prediction_hash_match=first_hash == second_hash and first == second,
    )
    return {
        "protocol": PROTOCOL,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256_file(candidate_lock_path),
        "first_prediction_file_sha256": sha256_file(first_predictions),
        "second_prediction_file_sha256": sha256_file(second_predictions),
        "first_prediction_content_sha256": first_hash,
        "second_prediction_content_sha256": second_hash,
        **score_payload,
        "protected_data_inputs": [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-lock", type=Path, required=True)
    parser.add_argument("--first-predictions", type=Path, required=True)
    parser.add_argument("--second-predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("FCRL U1 score output already exists")
        payload = score(
            args.candidate_lock,
            args.first_predictions,
            args.second_predictions,
        )
        write_json_atomic(args.output, payload)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"FCRL U1 scoring refused: {exc}") from exc
    print(args.output)
    print(f"passed={payload['passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
