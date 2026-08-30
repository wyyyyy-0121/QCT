#!/usr/bin/env python3
"""Acquire and verify the exact public ForTaP source and base checkpoint."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from pathlib import Path


REPOSITORY = "https://github.com/microsoft/TUTA_table_understanding.git"
COMMIT = "4de8bba4e9bf6a89b2e131bfb471b4db2c45b951"
CHECKPOINT_DRIVE_ID = "1ojtIb1aYarMZpxGqiL7HN-8Xx0JD3O5E"
CHECKPOINT_SHA256 = "42c2166afb60fedf833fcdbc4469dd6e23611f786aa7220a20375117c6c5a4a1"


def run(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)
    return completed.stdout.strip()


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire_source(destination: Path) -> None:
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPOSITORY, str(destination)])
        run(["git", "checkout", "--detach", COMMIT], cwd=destination)
    if not (destination / ".git").is_dir():
        raise SystemExit("FCRL source destination exists but is not a Git checkout")
    head = run(["git", "rev-parse", "HEAD"], cwd=destination)
    if head != COMMIT:
        raise SystemExit(f"FCRL source commit mismatch: {head}")
    tracked_changes = run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=destination)
    if tracked_changes:
        raise SystemExit("FCRL source checkout has tracked modifications")


def acquire_checkpoint(destination: Path) -> None:
    if not destination.exists():
        try:
            import gdown
        except ImportError as exc:
            raise SystemExit("Install requirements-fcrl.txt before checkpoint acquisition") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        gdown.download(id=CHECKPOINT_DRIVE_ID, output=str(temporary), quiet=False)
        if not temporary.is_file():
            raise SystemExit("ForTaP checkpoint download did not create an artifact")
        temporary.replace(destination)
    actual = sha256_file(destination)
    if actual != CHECKPOINT_SHA256:
        raise SystemExit(f"ForTaP base checkpoint hash mismatch: {actual}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/external/model_discovery/raw/TUTA_table_understanding"),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("data/external/model_discovery/raw/fcrl_checkpoints/fortap.bin"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("results/fcrl_u0/acquisition_receipt.json"),
    )
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    checkpoint = args.checkpoint.resolve()
    acquire_source(source_root)
    acquire_checkpoint(checkpoint)

    import torch

    license_path = source_root / "LICENSE"
    receipt = {
        "protocol": "formulaguard_fcrl_acquisition_v1",
        "source": {
            "repository": REPOSITORY,
            "commit": run(["git", "rev-parse", "HEAD"], cwd=source_root),
            "license": "MIT",
            "license_sha256": sha256_file(license_path),
        },
        "checkpoint": {
            "role": "ForTaP base formula-pretrained encoder",
            "google_drive_id": CHECKPOINT_DRIVE_ID,
            "bytes": checkpoint.stat().st_size,
            "sha256": sha256_file(checkpoint),
            "enron_finetuned": False,
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "protected_data_inputs": [],
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
