"""Merge locked five-method reference rows with newly computed V5 rows."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_external_evaluation import sha256_file


REFERENCE_METHODS = (
    "graph", "pattern", "formulaguard", "formulaguard_v3", "formulaguard_v4",
)
V5_METHOD = "formulaguard_v5"
ALL_METHODS = REFERENCE_METHODS + (V5_METHOD,)


def _read(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _key_audit(rows: list[dict[str, str]], methods: tuple[str, ...]) -> tuple[set[str], list[str]]:
    keys = [(row.get("instance_id", ""), row.get("method", "")) for row in rows]
    instances = {instance for instance, _ in keys if instance}
    errors = []
    if len(keys) != len(set(keys)):
        errors.append("duplicate instance-method keys")
    unexpected = sorted({method for _, method in keys} - set(methods))
    if unexpected:
        errors.append(f"unexpected methods: {unexpected}")
    expected = {(instance, method) for instance in instances for method in methods}
    missing = sorted(expected - set(keys))
    if missing:
        errors.append(f"missing keys: {missing[:10]}")
    return instances, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge locked reference rows with V5 rows")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--v5", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference, reference_fields = _read(args.reference)
    v5_rows, v5_fields = _read(args.v5)
    reference_instances, reference_errors = _key_audit(reference, REFERENCE_METHODS)
    v5_instances, v5_errors = _key_audit(v5_rows, (V5_METHOD,))
    errors = reference_errors + v5_errors
    if reference_instances != v5_instances:
        errors.append(
            "instance sets differ: "
            f"reference_only={sorted(reference_instances - v5_instances)} "
            f"v5_only={sorted(v5_instances - reference_instances)}"
        )
    if errors:
        raise SystemExit("Cannot merge development evidence: " + " | ".join(errors))

    fields = list(reference_fields)
    fields.extend(field for field in v5_fields if field not in fields)
    order = {method: index for index, method in enumerate(ALL_METHODS)}
    rows = reference + v5_rows
    rows.sort(key=lambda row: (row["instance_id"], order[row["method"]]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    receipt = {
        "scope": "locked_reference_plus_new_v5_development_rows",
        "events": len(reference_instances),
        "rows": len(rows),
        "methods": list(ALL_METHODS),
        "reference": str(args.reference.resolve()),
        "reference_sha256": sha256_file(args.reference),
        "v5": str(args.v5.resolve()),
        "v5_sha256": sha256_file(args.v5),
        "combined_sha256": sha256_file(args.output),
        "reference_rows_recomputed": False,
    }
    receipt_path = args.output.with_name(args.output.stem + "_merge_receipt.json")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
