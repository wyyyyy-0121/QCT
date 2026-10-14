"""Lock an Enron external-development/external-test split before evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--test-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()

    manifest = read_csv(args.manifest)
    inventory = read_csv(args.inventory)
    development = read_csv(args.development)
    fields = list(manifest[0])
    manifest_by_id = {row["instance_id"]: row for row in manifest}
    ready_ids = {
        row["instance_id"]
        for row in inventory
        if row.get("evaluation_ready", "").strip() == "1"
    }
    development_ids = [row["instance_id"] for row in development]
    if len(development_ids) != len(set(development_ids)):
        raise SystemExit("Development manifest contains duplicate instance IDs")
    if len(development_ids) != 10:
        raise SystemExit(f"Expected 10 development events, found {len(development_ids)}")
    if not set(development_ids) <= ready_ids:
        invalid = sorted(set(development_ids) - ready_ids)
        raise SystemExit(f"Development events are not evaluation-ready: {invalid}")
    if len(ready_ids) != 30:
        raise SystemExit(f"Expected 30 evaluation-ready events, found {len(ready_ids)}")

    test_ids = sorted(ready_ids - set(development_ids))
    if len(test_ids) != 20:
        raise SystemExit(f"Expected 20 untouched test events, found {len(test_ids)}")
    test_rows = [manifest_by_id[instance_id] for instance_id in test_ids]
    write_csv(args.test_output, test_rows, fields)

    audit = {
        "schema_version": 1,
        "selection_policy": (
            "Development events were selected before method results using formula_count <= 30; "
            "all other evaluation-ready events are the untouched external test set."
        ),
        "development_events": development_ids,
        "development_count": len(development_ids),
        "development_sha256": sha256(args.development),
        "test_events": test_ids,
        "test_count": len(test_ids),
        "test_sha256": sha256(args.test_output),
        "disjoint": not bool(set(development_ids) & set(test_ids)),
        "union_equals_evaluation_ready": set(development_ids) | set(test_ids) == ready_ids,
    }
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.test_output)
    print(args.audit_output)


if __name__ == "__main__":
    main()
