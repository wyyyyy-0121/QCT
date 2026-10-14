"""Verify frozen V4 and preregistered V5 development inputs before execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_external_evaluation import sha256_file


def verify(repository_root: Path, receipt_path: Path) -> dict[str, object]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mismatches = []
    for relative, expected in dict(receipt.get("files", {})).items():
        path = repository_root / relative
        actual = sha256_file(path) if path.is_file() else None
        if actual != expected:
            mismatches.append({"file": relative, "expected": expected, "actual": actual})

    frozen_path = repository_root / "research" / "frozen_config_v4.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    for relative, expected in dict(frozen.get("model_source_sha256", {})).items():
        path = repository_root / relative
        actual = sha256_file(path) if path.is_file() else None
        if actual != expected:
            mismatches.append({
                "file": relative,
                "expected": expected,
                "actual": actual,
                "contract": "frozen_v4_model_source",
            })
    expected_enron = dict(frozen.get("development_result_sha256", {})).get("external_raw.csv")
    actual_enron = sha256_file(repository_root / "results/v4_dev_revision/external_raw.csv")
    if actual_enron != expected_enron:
        mismatches.append({
            "file": "results/v4_dev_revision/external_raw.csv",
            "expected": expected_enron,
            "actual": actual_enron,
            "contract": "frozen_v4_development_evidence",
        })
    return {
        "scope": "v5_pre_execution_integrity_check",
        "receipt": str(receipt_path.resolve()),
        "verified_files": len(dict(receipt.get("files", {}))),
        "verified_v4_sources": len(dict(frozen.get("model_source_sha256", {}))),
        "mismatches": mismatches,
        "passed": not mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify V5 development prerequisites")
    parser.add_argument(
        "--receipt", type=Path, default=Path("research/V5_REFERENCE_RECEIPT.json")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = verify(root, args.receipt.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(args.output)
    if not payload["passed"]:
        raise SystemExit("V5 prerequisite verification failed: " + json.dumps(
            payload["mismatches"], ensure_ascii=False
        ))
    print("V5 prerequisites verified.")


if __name__ == "__main__":
    main()
