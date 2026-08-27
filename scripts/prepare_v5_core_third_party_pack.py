"""Validate and package 600 third-party V5-Core cases without running a model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_v5_core_dataset import sha256


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader(); writer.writerows({key: row.get(key, "") for key in fields} for row in rows)
    return stream.getvalue().encode("utf-8-sig")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Third-party generated V5-Core dataset root")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instances = read_jsonl(args.input / "instances.jsonl")
    labels = read_jsonl(args.input / "evaluation_labels.jsonl")
    by_id = {row["instance_id"]: row for row in labels}
    if len(instances) != 600 or len(labels) != 600 or set(by_id) != {row["instance_id"] for row in instances}:
        raise SystemExit("Third-party pack must contain exactly 600 matched events")
    counts = Counter(row["mutation_type"] for row in labels)
    if set(counts.values()) != {100} or len(counts) != 6:
        raise SystemExit(f"Six error types must have 100 cases each: {dict(counts)}")
    ledger = []
    for row in instances:
        label = by_id[row["instance_id"]]
        ledger.append({
            "instance_id": row["instance_id"],
            "template_family": row["template_family"],
            "topology": row["topology_id"],
            "regime": row["regime"],
            "manual_or_semi_manual": row.get("ambiguity") == "semi_manual",
            "cross_sheet_or_long_chain": row["topology_id"] == "cross_sheet" or int(label.get("actual_depth") or 0) >= 4,
            "non_neighbor_repair": label["mutation_type"] in {"range_boundary", "function_replacement", "absolute_reference"},
            "contains_legitimate_exception": (
                row.get("regime") == "mixed_exception"
                or row.get("ambiguity") in {"legitimate_summary", "legitimate_exception", "semi_manual_exception"}
            ),
        })
    if sum(row["manual_or_semi_manual"] for row in ledger) < 120:
        raise SystemExit("At least 120 cases must be manual or semi-manual")
    if sum(row["cross_sheet_or_long_chain"] for row in ledger) < 100:
        raise SystemExit("At least 100 cases must be cross-sheet or long-chain")
    if sum(row["non_neighbor_repair"] for row in ledger) < 100:
        raise SystemExit("At least 100 cases must not be simple neighbor translations")
    if sum(row["contains_legitimate_exception"] for row in ledger) < 60:
        raise SystemExit("At least 60 cases must contain a legitimate special formula or complex summary")

    labels_csv = csv_bytes(labels, [
        "instance_id", "source_cell", "mutation_type", "correct_formula",
        "mutated_formula", "sink_cell", "actual_depth",
    ])
    exceptions_csv = csv_bytes([], ["instance_id", "reason", "notes"])
    ledger_csv = csv_bytes(ledger, list(ledger[0]))
    args.output.mkdir(parents=True, exist_ok=True)
    secret_zip = args.output / "FormulaGuard_V5_SECRET_600.zip"
    with zipfile.ZipFile(secret_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("labels.csv", labels_csv)
        archive.writestr("exceptions.csv", exceptions_csv)
        archive.writestr("design_ledger.csv", ledger_csv)
        for row in instances:
            original = args.input / "originals" / f"{row['instance_id']}.xlsx"
            archive.write(original, f"originals/{row['instance_id']}.xlsx")
    precommit = {
        "secret_zip_sha256": sha256(secret_zip),
        "labels_csv_sha256": digest_bytes(labels_csv),
        "exceptions_csv_sha256": digest_bytes(exceptions_csv),
        "design_ledger_csv_sha256": digest_bytes(ledger_csv),
    }
    precommit_text = "".join(f"{key}={value}\n" for key, value in precommit.items())
    public_zip = args.output / "FormulaGuard_V5_PUBLIC_600.zip"
    manifest_rows = [
        {"instance_id": row["instance_id"], "workbook": f"workbooks/{row['instance_id']}.xlsx"}
        for row in instances
    ]
    manifest_csv = csv_bytes(manifest_rows, ["instance_id", "workbook"])
    with zipfile.ZipFile(public_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.csv", manifest_csv)
        archive.writestr("secret_precommit_sha256.txt", precommit_text.encode("utf-8"))
        for row in instances:
            mutant = args.input / row["mutant_workbook"]
            archive.write(mutant, f"workbooks/{row['instance_id']}.xlsx")
    receipt = {
        "protocol": "v5_core_third_party_precommit_v1",
        "public_zip": str(public_zip.resolve()),
        "public_zip_sha256": sha256(public_zip),
        **precommit,
        "cases": 600,
        "model_was_run": False,
    }
    (args.output / "third_party_precommit.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(public_zip); print(secret_zip); print(args.output / "third_party_precommit.json")


if __name__ == "__main__":
    main()
