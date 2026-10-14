"""Audit only label-free V5-Core manifests and workbooks before prediction lock."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_v5_core_dataset import PROFILE_COUNTS, sha256


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit_root(root: Path) -> dict:
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    profile = manifest["profile"]
    full_expected = PROFILE_COUNTS[profile]
    subset_limit = manifest.get("subset_limit")
    expected = min(full_expected, int(subset_limit)) if subset_limit is not None else full_expected
    reasons: list[str] = []
    if profile == "clean":
        rows = json.loads((root / "clean_manifest.json").read_text(encoding="utf-8"))
        id_key, path_key, hash_key = "clean_id", "workbook", "sha256"
    else:
        rows = read_jsonl(root / "instances.jsonl")
        id_key, path_key, hash_key = "instance_id", "mutant_workbook", "mutant_sha256"
    identifiers = [row[id_key] for row in rows]
    if len(rows) != expected:
        reasons.append(f"public row count {len(rows)} != {expected}")
    if len(identifiers) != len(set(identifiers)):
        reasons.append("duplicate public instance ids")
    for row in rows:
        workbook = root / row[path_key]
        if not workbook.exists():
            reasons.append(f"missing workbook {row[id_key]}")
        elif sha256(workbook) != row[hash_key]:
            reasons.append(f"changed workbook {row[id_key]}")
    return {
        "root": str(root.resolve()),
        "profile": profile,
        "expected": expected,
        "observed": len(rows),
        "workbook_hashes_verified": len(rows) - len([item for item in reasons if "workbook" in item]),
        "label_files_opened": [],
        "passed": not reasons,
        "reasons": reasons[:100],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audits = [audit_root(root) for root in args.roots]
    payload = {
        "protocol": "v5_core_label_free_public_input_audit_v1",
        "datasets": audits,
        "label_files_opened": [],
        "hard_gate_passed": all(item["passed"] for item in audits),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if not payload["hard_gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
