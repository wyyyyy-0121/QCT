"""Reuse verified Enron workbook rankings across inventory-only corrections.

This helper is intentionally narrow: source and target runs must use the same
V4/V6/method-spec hashes and variant, and every reused shard must match the
current workbook hash and contain complete, duplicate-free V4/V6 rankings.
The target manifest may differ because this is used when expanding an event
inventory without changing the workbooks or localization model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def included_workbooks(manifest: Path) -> list[str]:
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("include", "1") == "1"]
    return sorted({row["workbook"] for row in rows})


def validate_record(record: dict, *, workbook: str, workbook_path: Path, variant: str) -> None:
    if record.get("workbook") != workbook:
        raise SystemExit(f"Shard workbook mismatch: {workbook}")
    if record.get("sha256") != sha256(workbook_path):
        raise SystemExit(f"Shard workbook hash mismatch: {workbook}")
    formula_count = record.get("formula_count")
    methods = {"v4", f"v6_{variant}"}
    if not isinstance(formula_count, int) or formula_count < 1:
        raise SystemExit(f"Invalid formula count: {workbook}")
    if set(record.get("rankings", {})) != methods:
        raise SystemExit(f"Unexpected method set: {workbook}")
    cell_sets = []
    for method in methods:
        ranking = record["rankings"][method]
        ranks = [row.get("rank") for row in ranking]
        cells = [row.get("cell") for row in ranking]
        if (
            len(ranking) != formula_count
            or ranks != list(range(1, formula_count + 1))
            or len(set(cells)) != formula_count
        ):
            raise SystemExit(f"Incomplete or duplicate ranking: {workbook} {method}")
        cell_sets.append(set(cells))
    if cell_sets[0] != cell_sets[1]:
        raise SystemExit(f"V4/V6 formula-cell sets differ: {workbook}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/external/enron"))
    parser.add_argument("--manifest", type=Path, default=Path("data/external/enron/manifest.csv"))
    args = parser.parse_args()

    source_meta = load_json(args.source / "enron_metadata.json")
    target_meta = load_json(args.target / "enron_metadata.json")
    invariant_fields = ("variant", "v6_source_sha256", "v4_source_sha256", "method_spec_sha256")
    mismatches = [field for field in invariant_fields if source_meta.get(field) != target_meta.get(field)]
    if mismatches:
        raise SystemExit(f"Shard reuse refused; invariant metadata differs: {', '.join(mismatches)}")
    variant = target_meta["variant"]

    source_records = {}
    source_paths = {}
    for path in sorted((args.source / "shards").glob("*.json")):
        record = load_json(path)
        workbook = record.get("workbook")
        if workbook in source_records:
            raise SystemExit(f"Duplicate source workbook shard: {workbook}")
        source_records[workbook] = record
        source_paths[workbook] = path

    target_shards = args.target / "shards"
    target_shards.mkdir(parents=True, exist_ok=True)
    reused = []
    for index, workbook in enumerate(included_workbooks(args.manifest)):
        target_path = target_shards / f"workbook_{index:03d}.json"
        if target_path.exists() or workbook not in source_records:
            continue
        workbook_path = args.root / workbook
        record = source_records[workbook]
        validate_record(record, workbook=workbook, workbook_path=workbook_path, variant=variant)
        record = dict(record)
        record["reuse_provenance"] = {
            "source_directory": args.source.as_posix(),
            "source_shard": source_paths[workbook].name,
            "source_shard_sha256": sha256(source_paths[workbook]),
            "verified_invariants": list(invariant_fields),
        }
        temporary = target_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target_path)
        reused.append({
            "workbook": workbook,
            "target_shard": target_path.name,
            "target_shard_sha256": sha256(target_path),
            "source_shard_sha256": record["reuse_provenance"]["source_shard_sha256"],
        })

    receipt = {
        "protocol": "v6_enron_verified_shard_reuse_v1",
        "source": args.source.as_posix(),
        "target": args.target.as_posix(),
        "variant": variant,
        "invariant_metadata": {field: target_meta[field] for field in invariant_fields},
        "reused_count": len(reused),
        "reused": reused,
    }
    receipt_path = args.target / "shard_reuse_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(receipt_path)
    print(f"Reused {len(reused)} verified workbook shard(s).")


if __name__ == "__main__":
    main()
