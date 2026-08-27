"""Extract a label-free 600-case public pack and hash-lock joint predictions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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


def archive_member_sha256(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundled_git() -> str:
    path = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    return "git" if subprocess.run(["where", "git"], capture_output=True).returncode == 0 else str(path)


def tagged_freeze_bytes() -> bytes:
    try:
        return subprocess.check_output(
            [bundled_git(), "show", "v5-core-lock:research/frozen_config_v5_core.json"],
            cwd=ROOT,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit("Blind lock refused: Git tag v5-core-lock does not contain the frozen configuration") from exc


def safe_extract(archive: zipfile.ZipFile, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for member in archive.infolist():
        parts = PurePosixPath(member.filename).parts
        if not parts or any(part in {"..", ""} for part in parts) or PurePosixPath(member.filename).is_absolute():
            raise SystemExit(f"Unsafe archive member: {member.filename}")
        destination = root.joinpath(*parts)
        if member.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-zip", type=Path, default=Path(r"D:\FormulaGuard_V5_ThirdParty\FormulaGuard_V5_PUBLIC_600.zip"))
    parser.add_argument("--precommit", type=Path, default=Path(r"D:\FormulaGuard_V5_ThirdParty\third_party_precommit.json"))
    parser.add_argument("--frozen-config", type=Path, default=Path("research/frozen_config_v5_core.json"))
    parser.add_argument("--public-root", type=Path, default=Path("data/v5_core_blind/public"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_blind_locked"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    precommit = json.loads(args.precommit.read_text(encoding="utf-8"))
    if precommit.get("cases") != 600 or precommit.get("model_was_run") is not False:
        raise SystemExit("Blind lock refused: invalid third-party precommit receipt")
    if precommit.get("public_zip_sha256") != sha256(args.public_zip):
        raise SystemExit("Blind lock refused: public archive differs from its pre-freeze commitment")
    frozen = json.loads(args.frozen_config.read_text(encoding="utf-8"))
    if frozen.get("third_party_results_seen") is not False or frozen.get("post_validation_retuning_allowed") is not False:
        raise SystemExit("Blind lock refused: frozen configuration lacks the no-retuning declarations")
    if hashlib.sha256(tagged_freeze_bytes()).hexdigest() != sha256(args.frozen_config):
        raise SystemExit("Blind lock refused: local frozen configuration differs from v5-core-lock")
    for relative, expected in frozen["source_sha256"].items():
        if sha256(ROOT / relative) != expected:
            raise SystemExit(f"Frozen source changed: {relative}")
    with zipfile.ZipFile(args.public_zip) as archive:
        try:
            archived_manifest_bytes = archive.read("manifest.csv")
            archived_precommit_bytes = archive.read("secret_precommit_sha256.txt")
        except KeyError as exc:
            raise SystemExit("Public archive lacks its manifest or secret precommit") from exc
        archived_reader = csv.DictReader(
            archived_manifest_bytes.decode("utf-8-sig").splitlines()
        )
        if archived_reader.fieldnames != ["instance_id", "workbook"]:
            raise SystemExit("Archived public manifest must contain exactly instance_id,workbook")
        archived_manifest = list(archived_reader)
        expected_members = {
            "manifest.csv", "secret_precommit_sha256.txt",
            *(row["workbook"] for row in archived_manifest),
        }
        observed_members = {member.filename for member in archive.infolist() if not member.is_dir()}
        if observed_members != expected_members:
            raise SystemExit("Public archive has missing, extra, or secret-bearing files")
    if not (args.public_root / "manifest.csv").exists():
        if args.public_root.exists() and any(args.public_root.iterdir()):
            raise SystemExit(f"Public extraction root is non-empty: {args.public_root}")
        with zipfile.ZipFile(args.public_zip) as archive:
            safe_extract(archive, args.public_root)
    if hashlib.sha256((args.public_root / "manifest.csv").read_bytes()).hexdigest() != hashlib.sha256(archived_manifest_bytes).hexdigest():
        raise SystemExit("Extracted public manifest differs from the committed archive")
    if hashlib.sha256((args.public_root / "secret_precommit_sha256.txt").read_bytes()).hexdigest() != hashlib.sha256(archived_precommit_bytes).hexdigest():
        raise SystemExit("Extracted secret precommit differs from the committed archive")
    with (args.public_root / "manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["instance_id", "workbook"]:
            raise SystemExit("Public manifest must contain exactly instance_id,workbook")
        manifest = list(reader)
    committed_secret = dict(
        line.strip().split("=", 1)
        for line in (args.public_root / "secret_precommit_sha256.txt").read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    for key in (
        "secret_zip_sha256", "labels_csv_sha256", "exceptions_csv_sha256",
        "design_ledger_csv_sha256", "provenance_sha256",
    ):
        if committed_secret.get(key) != precommit.get(key):
            raise SystemExit(f"Blind lock refused: public secret commitment differs for {key}")
    if len(manifest) != 600 or len({row["instance_id"] for row in manifest}) != 600:
        raise SystemExit("Public pack must contain 600 unique cases")
    for row in manifest:
        path = args.public_root / row["workbook"]
        if not path.exists() or args.public_root.resolve() not in path.resolve().parents:
            raise SystemExit(f"Missing or escaping workbook: {row['workbook']}")
    with zipfile.ZipFile(args.public_zip) as archive:
        for row in manifest:
            if sha256(args.public_root / row["workbook"]) != archive_member_sha256(archive, row["workbook"]):
                raise SystemExit(f"Extracted workbook differs from public archive: {row['workbook']}")
    instances = [
        {
            "instance_id": row["instance_id"],
            "template_family": "third_party_withheld",
            "topology_id": "withheld",
            "regime": "withheld",
            "complexity": "withheld",
            "data_split": "third_party",
            "mutant_workbook": row["workbook"],
            "mutant_sha256": sha256(args.public_root / row["workbook"]),
            "ambiguity": "withheld",
        }
        for row in manifest
    ]
    (args.public_root / "instances.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in instances), encoding="utf-8",
    )
    dataset_manifest = {
        "profile": "third_party_public", "actual_count": 600,
        "labels_present": False, "public_zip_sha256": sha256(args.public_zip),
    }
    (args.public_root / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    rule_path = args.output / "runtime_rule_config.json"
    learned_path = args.output / "runtime_learned_config.json"
    rule_path.write_text(json.dumps(frozen["rule_config"], ensure_ascii=False, indent=2), encoding="utf-8")
    learned_path.write_text(json.dumps(frozen["learned_config"], ensure_ascii=False, indent=2), encoding="utf-8")
    command = [
        sys.executable, "scripts/run_v5_core_predictions.py",
        "--benchmark", str(args.public_root), "--output", str(args.output / "predictions"),
        "--rule-config", str(rule_path), "--learned-config", str(learned_path),
        "--baselines", "--workers", str(args.workers),
    ]
    if args.resume:
        command.append("--resume")
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode:
        raise SystemExit(completed.returncode)
    completion = args.output / "predictions/prediction_complete.json"
    receipt = {
        "protocol": "v5_core_third_party_prediction_lock_v1",
        "public_zip_sha256": sha256(args.public_zip),
        "frozen_config_sha256": sha256(args.frozen_config),
        "prediction_completion_sha256": sha256(completion),
        "precommit_text_sha256": sha256(args.public_root / "secret_precommit_sha256.txt"),
        "third_party_precommit_sha256": sha256(args.precommit),
        "v5_core_lock_tag_verified": True,
        "cases": 600,
        "labels_read": [],
        "labels_may_now_be_released": True,
    }
    lock = args.output / "prediction_lock.json"
    lock.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(lock)


if __name__ == "__main__":
    main()
