"""Verify the third-party public archive and hash-lock all R2 predictions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_sha256(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_executable() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = shutil.which("git") or (str(bundled) if bundled.is_file() else None)
    if executable is None:
        raise SystemExit("Confirmation lock refused: Git is unavailable")
    return executable


def tagged_freeze_bytes() -> bytes:
    try:
        return subprocess.check_output(
            [git_executable(), "show", "v5-core-r2-lock:research/frozen_config_v5_core_r2.json"],
            cwd=ROOT,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit("Confirmation lock refused: tag v5-core-r2-lock lacks the frozen config") from exc


def parse_commitments(text: str) -> dict[str, str]:
    return dict(
        line.strip().split("=", 1)
        for line in text.splitlines()
        if "=" in line
    )


def safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for member in archive.infolist():
        parts = PurePosixPath(member.filename).parts
        if not parts or any(part in {"", ".."} for part in parts) or PurePosixPath(member.filename).is_absolute():
            raise SystemExit(f"Unsafe public archive member: {member.filename}")
        target = destination.joinpath(*parts)
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--public-zip", type=Path,
        default=Path(r"D:\FormulaGuard_R2_ThirdParty\FormulaGuard_R2_PUBLIC_780.zip"),
    )
    parser.add_argument(
        "--precommit", type=Path,
        default=Path(r"D:\FormulaGuard_R2_ThirdParty\third_party_precommit.json"),
    )
    parser.add_argument("--frozen-config", type=Path, default=Path("research/frozen_config_v5_core_r2.json"))
    parser.add_argument("--public-root", type=Path, default=Path("data/v5_core_r2_confirmation/public"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_r2_confirmation_locked"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    precommit = json.loads(args.precommit.read_text(encoding="utf-8"))
    if precommit.get("protocol") != "v5_core_r2_third_party_precommit_v1":
        raise SystemExit("Confirmation lock refused: unknown third-party precommit protocol")
    required_counts = {"total_cases": 780, "error_cases": 600, "clean_cases": 180}
    if any(int(precommit.get(key, -1)) != value for key, value in required_counts.items()):
        raise SystemExit("Confirmation lock refused: third-party counts differ from the protocol")
    if precommit.get("model_was_run") is not False:
        raise SystemExit("Confirmation lock refused: precommit does not certify model_was_run=false")
    if precommit.get("development_overlap_audit_passed") is not True:
        raise SystemExit("Confirmation lock refused: development-overlap audit was not certified")
    if precommit.get("independent_preparer") is not True:
        raise SystemExit("Confirmation lock refused: independent-preparer declaration is missing")
    if precommit.get("single_injection_and_propagation_audit_passed") is not True:
        raise SystemExit("Confirmation lock refused: data-construction audit did not pass")
    if int(precommit.get("real_structure_cases", 0)) < 150:
        raise SystemExit("Confirmation lock refused: fewer than 150 real-structure cases")
    if int(precommit.get("manual_error_cases", 0)) < 120:
        raise SystemExit("Confirmation lock refused: fewer than 120 manual/semi-manual errors")
    if precommit.get("public_zip_sha256") != sha256(args.public_zip):
        raise SystemExit("Confirmation lock refused: PUBLIC.zip differs from its pre-freeze hash")
    frozen = json.loads(args.frozen_config.read_text(encoding="utf-8"))
    if frozen.get("pressure_safety_passed") is not True:
        raise SystemExit("Confirmation lock refused: pressure safety was not frozen as passed")
    if frozen.get("confirmation_results_seen") is not False or frozen.get("post_confirmation_retuning_allowed") is not False:
        raise SystemExit("Confirmation lock refused: no-retuning declarations are missing")
    if hashlib.sha256(tagged_freeze_bytes()).hexdigest() != sha256(args.frozen_config):
        raise SystemExit("Confirmation lock refused: local freeze differs from v5-core-r2-lock")
    for relative, expected in frozen.get("source_sha256", {}).items():
        if sha256(ROOT / relative) != expected:
            raise SystemExit(f"Frozen R2 source changed: {relative}")

    with zipfile.ZipFile(args.public_zip) as archive:
        try:
            manifest_bytes = archive.read("manifest.csv")
            commitments_bytes = archive.read("secret_precommit_sha256.txt")
        except KeyError as exc:
            raise SystemExit("PUBLIC.zip lacks manifest.csv or secret_precommit_sha256.txt") from exc
        reader = csv.DictReader(manifest_bytes.decode("utf-8-sig").splitlines())
        if reader.fieldnames != ["instance_id", "workbook"]:
            raise SystemExit("Public manifest must contain exactly instance_id,workbook")
        manifest = list(reader)
        if any("\\" in row["workbook"] or ".." in PurePosixPath(row["workbook"]).parts
               for row in manifest):
            raise SystemExit("Public manifest contains unsafe or non-portable workbook paths")
        if len({row["workbook"] for row in manifest}) != len(manifest):
            raise SystemExit("Each confirmation event must use a distinct public workbook")
        expected_members = {
            "manifest.csv", "secret_precommit_sha256.txt",
            *(row["workbook"] for row in manifest),
        }
        observed_members = {item.filename for item in archive.infolist() if not item.is_dir()}
        if any("\\" in name or ".." in PurePosixPath(name).parts for name in observed_members):
            raise SystemExit("PUBLIC.zip contains unsafe or non-portable member names")
        if observed_members != expected_members:
            raise SystemExit("PUBLIC.zip contains missing, extra, or secret-bearing files")
    if len(manifest) != 780 or len({row["instance_id"] for row in manifest}) != 780:
        raise SystemExit("Public confirmation manifest must contain 780 unique identifiers")
    commitments = parse_commitments(commitments_bytes.decode("utf-8"))
    for key in (
        "secret_zip_sha256", "labels_csv_sha256", "exceptions_csv_sha256",
        "design_ledger_csv_sha256", "provenance_csv_sha256", "declaration_json_sha256",
    ):
        if commitments.get(key) != precommit.get(key):
            raise SystemExit(f"Public/third-party secret commitment differs for {key}")

    if not (args.public_root / "manifest.csv").exists():
        if args.public_root.exists() and any(args.public_root.iterdir()):
            raise SystemExit(f"Public extraction root is non-empty: {args.public_root}")
        with zipfile.ZipFile(args.public_zip) as archive:
            safe_extract(archive, args.public_root)
    if sha256(args.public_root / "manifest.csv") != hashlib.sha256(manifest_bytes).hexdigest():
        raise SystemExit("Extracted public manifest differs from PUBLIC.zip")
    if sha256(args.public_root / "secret_precommit_sha256.txt") != hashlib.sha256(commitments_bytes).hexdigest():
        raise SystemExit("Extracted public secret commitment differs from PUBLIC.zip")
    with zipfile.ZipFile(args.public_zip) as archive:
        for row in manifest:
            path = (args.public_root / row["workbook"]).resolve()
            try:
                path.relative_to(args.public_root.resolve())
            except ValueError as exc:
                raise SystemExit(f"Public workbook escapes extraction root: {row['workbook']}") from exc
            if not path.is_file() or sha256(path) != archive_sha256(archive, row["workbook"]):
                raise SystemExit(f"Missing or changed extracted workbook: {row['workbook']}")

    args.output.mkdir(parents=True, exist_ok=True)
    runtime_config = args.output / "runtime_config.json"
    runtime_config.write_text(
        json.dumps(frozen["runtime_config"], ensure_ascii=False, indent=2), encoding="utf-8",
    )
    command = [
        sys.executable, "scripts/run_v5_core_r2_predictions.py",
        "--public-root", str(args.public_root),
        "--config", str(runtime_config),
        "--output", str(args.output / "predictions"),
        "--workers", str(args.workers),
    ]
    if args.resume:
        command.append("--resume")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)
    completion_path = args.output / "predictions/prediction_complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if completion.get("instances") != 780 or completion.get("full_ranking_audit_passed") is not True:
        raise SystemExit("Confirmation prediction completion receipt is invalid")
    receipt = {
        "protocol": "v5_core_r2_confirmation_prediction_lock_v1",
        "cases": 780,
        "public_zip_sha256": sha256(args.public_zip),
        "third_party_precommit_sha256": sha256(args.precommit),
        "frozen_config_sha256": sha256(args.frozen_config),
        "runtime_config_sha256": sha256(runtime_config),
        "public_manifest_sha256": sha256(args.public_root / "manifest.csv"),
        "precommit_text_sha256": sha256(args.public_root / "secret_precommit_sha256.txt"),
        "prediction_completion_sha256": sha256(completion_path),
        "prediction_shards_sha256": completion["combined_shards_sha256"],
        "methods": completion["methods"],
        "v5_core_r2_lock_tag_verified": True,
        "labels_read": [],
        "labels_may_now_be_released": True,
    }
    lock_path = args.output / "prediction_lock.json"
    lock_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(lock_path)
    print("R2 confirmation predictions are hash-locked. SECRET.zip may now be released.")


if __name__ == "__main__":
    main()
