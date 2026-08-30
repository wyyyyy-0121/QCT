#!/usr/bin/env python3
"""Freeze the trained FCRL U1 decoder before any internal-test decoding."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import torch

from formulaguard.fcrl_torch import (
    EXPECTED_CHECKPOINT_SHA256,
    EXPECTED_SOURCE_COMMIT,
)
from formulaguard.fcrl_u1 import sha256_file, stable_hash
from scripts.build_fcrl_u1_corpus import (
    DEFAULT_CORPUS_MANIFEST,
    DEFAULT_CORPUS_RECEIPT,
    DEFAULT_FORTAP_SOURCE,
    DEFAULT_INPUT_ROOT,
    DEFAULT_INTAKE_MANIFEST,
    EXPECTED_GROUPS,
    write_json_atomic,
)
from scripts.train_fcrl_u1 import (
    DEFAULT_CHECKPOINT,
    DEFAULT_OUTPUT as DEFAULT_TRAINING_OUTPUT,
    DEFAULT_TARGET_MANIFEST,
    DEFAULT_TARGET_RECEIPT,
    load_target_contract,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_fcrl_u1_candidate_lock_v1"
DEFAULT_OUTPUT = ROOT / "research/V5_FCRL_U1_CANDIDATE_LOCK.json"
LOCKED_SOURCES = (
    "formulaguard/fcrl.py",
    "formulaguard/fcrl_torch.py",
    "formulaguard/fcrl_u1.py",
    "scripts/build_fcrl_u1_corpus.py",
    "scripts/train_fcrl_u1.py",
    "scripts/freeze_fcrl_u1_candidate.py",
    "scripts/run_fcrl_u1_locked.py",
    "scripts/score_fcrl_u1.py",
    "research/V5_FCRL_U1_IMPLEMENTATION_FREEZE.md",
    "requirements-fcrl.txt",
)


def git(*args: str, cwd: Path = ROOT) -> str:
    completed = subprocess.run(
        ("git", *args), cwd=cwd, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def require_clean_tracked_worktree() -> None:
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked worktree must be clean before FCRL candidate freeze")


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("FCRL candidate artifact must remain under the repository root") from exc


def verified_training_receipt(
    path: Path,
    *,
    target_manifest: Path,
    target_receipt: Path,
    selected_decoder: Path,
    implementation_commit: str,
) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if (
        payload.get("protocol") != "formulaguard_fcrl_u1_training_v1"
        or payload.get("complete") is not True
        or payload.get("git_commit") != implementation_commit
        or payload.get("target_manifest_sha256") != sha256_file(target_manifest)
        or payload.get("target_receipt_sha256") != sha256_file(target_receipt)
        or payload.get("selected_decoder_sha256") != sha256_file(selected_decoder)
        or payload.get("selected_decoder_bytes") != selected_decoder.stat().st_size
        or payload.get("internal_test_decoded") is not False
        or payload.get("protected_data_inputs") != []
        or payload.get("answer_workbook_inputs") != []
        or payload.get("fault_label_inputs") != []
        or payload.get("v4_rank_inputs") != []
        or not isinstance(payload.get("history"), list)
        or int(payload.get("best_epoch", 0)) < 1
    ):
        raise ValueError("FCRL training receipt is incomplete, changed, or unsafe")
    return payload


def build_candidate_lock(
    *,
    target_manifest: Path,
    target_receipt: Path,
    corpus_manifest: Path,
    corpus_receipt: Path,
    intake_manifest: Path,
    input_root: Path,
    fortap_source: Path,
    checkpoint: Path,
    training_receipt: Path,
    selected_decoder: Path,
) -> dict[str, object]:
    require_clean_tracked_worktree()
    implementation_commit = git("rev-parse", "HEAD")
    manifest, targets = load_target_contract(target_manifest, target_receipt)
    receipt = json.loads(target_receipt.read_text(encoding="ascii"))
    training = verified_training_receipt(
        training_receipt,
        target_manifest=target_manifest,
        target_receipt=target_receipt,
        selected_decoder=selected_decoder,
        implementation_commit=implementation_commit,
    )
    if receipt.get("git_commit") != implementation_commit:
        raise ValueError("FCRL corpus was not built from the current implementation commit")
    if receipt.get("split_structure_groups") != EXPECTED_GROUPS:
        raise ValueError("FCRL corpus no longer covers every frozen structure group")
    if sha256_file(checkpoint) != EXPECTED_CHECKPOINT_SHA256:
        raise ValueError("FCRL base checkpoint changed")
    if git("rev-parse", "HEAD", cwd=fortap_source) != EXPECTED_SOURCE_COMMIT:
        raise ValueError("ForTaP source commit changed")
    for source in LOCKED_SOURCES:
        path = ROOT / source
        if not path.is_file() or git("ls-files", "--error-unmatch", source) != source:
            raise ValueError(f"locked FCRL source is absent or untracked: {source}")

    artifacts = {
        "target_manifest": target_manifest,
        "target_receipt": target_receipt,
        "corpus_manifest": corpus_manifest,
        "corpus_receipt": corpus_receipt,
        "intake_manifest": intake_manifest,
        "base_checkpoint": checkpoint,
        "training_receipt": training_receipt,
        "selected_decoder": selected_decoder,
    }
    artifact_records = {
        name: {
            "path": relative_path(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for name, path in artifacts.items()
    }
    source_hashes = {source: sha256_file(ROOT / source) for source in LOCKED_SOURCES}
    split_targets = receipt.get("split_targets")
    if not isinstance(split_targets, dict) or set(split_targets) != set(EXPECTED_GROUPS):
        raise ValueError("FCRL split target counts are incomplete")
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "candidate_locked": True,
        "formal_version": None,
        "implementation_commit": implementation_commit,
        "fortap_source_commit": EXPECTED_SOURCE_COMMIT,
        "artifacts": artifact_records,
        "source_sha256": source_hashes,
        "source_paths": {
            "input_root": relative_path(input_root),
            "fortap_source": relative_path(fortap_source),
        },
        "corpus": {
            "targets": len(targets),
            "split_targets": split_targets,
            "split_structure_groups": receipt["split_structure_groups"],
            "global_frequency_top5_train_only": manifest["global_frequency_top5_train_only"],
        },
        "selection": {
            "best_epoch": training["best_epoch"],
            "epochs_completed": training["epochs_completed"],
            "best_calibration_structure_group_macro_top5": training[
                "best_calibration_structure_group_macro_top5"
            ],
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count(),
            "cuda_device_name": (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
            ),
        },
        "internal_test_decoded": False,
        "public_prediction_lock_complete": False,
        "protected_data_inputs": [],
    }
    payload["candidate_id"] = "fcrl-u1:" + stable_hash(payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-manifest", type=Path, default=DEFAULT_TARGET_MANIFEST)
    parser.add_argument("--target-receipt", type=Path, default=DEFAULT_TARGET_RECEIPT)
    parser.add_argument("--corpus-manifest", type=Path, default=DEFAULT_CORPUS_MANIFEST)
    parser.add_argument("--corpus-receipt", type=Path, default=DEFAULT_CORPUS_RECEIPT)
    parser.add_argument("--intake-manifest", type=Path, default=DEFAULT_INTAKE_MANIFEST)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--fortap-source", type=Path, default=DEFAULT_FORTAP_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument(
        "--training-receipt",
        type=Path,
        default=DEFAULT_TRAINING_OUTPUT / "training_receipt.json",
    )
    parser.add_argument(
        "--selected-decoder",
        type=Path,
        default=DEFAULT_TRAINING_OUTPUT / "selected_decoder.bin",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("FCRL candidate lock output already exists")
        payload = build_candidate_lock(
            target_manifest=args.target_manifest,
            target_receipt=args.target_receipt,
            corpus_manifest=args.corpus_manifest,
            corpus_receipt=args.corpus_receipt,
            intake_manifest=args.intake_manifest,
            input_root=args.input_root,
            fortap_source=args.fortap_source,
            checkpoint=args.checkpoint,
            training_receipt=args.training_receipt,
            selected_decoder=args.selected_decoder,
        )
        write_json_atomic(args.output, payload)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"FCRL U1 candidate freeze refused: {exc}") from exc
    print(args.output)
    print(f"candidate_id={payload['candidate_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
