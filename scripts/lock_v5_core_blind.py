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
    parser.add_argument("--frozen-config", type=Path, default=Path("research/frozen_config_v5_core.json"))
    parser.add_argument("--public-root", type=Path, default=Path("data/v5_core_blind/public"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_blind_locked"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    frozen = json.loads(args.frozen_config.read_text(encoding="utf-8"))
    for relative, expected in frozen["source_sha256"].items():
        if sha256(ROOT / relative) != expected:
            raise SystemExit(f"Frozen source changed: {relative}")
    if not (args.public_root / "manifest.csv").exists():
        if args.public_root.exists() and any(args.public_root.iterdir()):
            raise SystemExit(f"Public extraction root is non-empty: {args.public_root}")
        with zipfile.ZipFile(args.public_zip) as archive:
            safe_extract(archive, args.public_root)
    with (args.public_root / "manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["instance_id", "workbook"]:
            raise SystemExit("Public manifest must contain exactly instance_id,workbook")
        manifest = list(reader)
    if len(manifest) != 600 or len({row["instance_id"] for row in manifest}) != 600:
        raise SystemExit("Public pack must contain 600 unique cases")
    for row in manifest:
        path = args.public_root / row["workbook"]
        if not path.exists() or args.public_root.resolve() not in path.resolve().parents:
            raise SystemExit(f"Missing or escaping workbook: {row['workbook']}")
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
        "cases": 600,
        "labels_read": [],
        "labels_may_now_be_released": True,
    }
    lock = args.output / "prediction_lock.json"
    lock.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(lock)


if __name__ == "__main__":
    main()
