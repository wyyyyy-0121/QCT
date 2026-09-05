"""Compare independent VRER R0 audits and issue a reproduction receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.vrer import R0_PROTOCOL, sha256_file, summarize_r0

REPRODUCTION_PROTOCOL = "formulaguard_vrer_r0_reproduction_v1"
COMPARE_FIELDS = (
    "candidate_id",
    "repository",
    "revision_group",
    "source_kind",
    "accepted",
    "rejection_reasons",
    "corrected_formula_cells",
    "parseable_corrected_formula_cells",
    "diff",
    "commit_sha",
    "parent_sha",
    "evidence_quote",
    "workbook_path",
    "before_sha256",
    "after_sha256",
    "license_spdx",
    "license_sha256",
    "protected_data_inputs",
    "revealed_label_inputs",
)


def _records(receipt: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = receipt.get("records")
    if not isinstance(rows, list):
        raise TypeError("VRER R0 receipt has no records")
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("VRER R0 record is malformed")
        candidate_id = str(row.get("candidate_id", ""))
        if not candidate_id or candidate_id in result:
            raise ValueError("VRER R0 candidate identity is invalid")
        result[candidate_id] = row
    return result


def reproducibility_sample(candidate_ids: Sequence[str]) -> list[str]:
    if not candidate_ids:
        return []
    ordered = sorted(
        set(candidate_ids),
        key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
    )
    return ordered[: max(1, math.ceil(0.20 * len(ordered)))]


def compare_receipts(
    primary: Mapping[str, object], recheck: Mapping[str, object]
) -> dict[str, object]:
    for receipt in (primary, recheck):
        if receipt.get("protocol") != R0_PROTOCOL:
            raise ValueError("VRER R0 receipt protocol differs")
        if receipt.get("protected_data_inputs") != []:
            raise ValueError("VRER R0 receipt contains protected inputs")
        if receipt.get("revealed_label_inputs") != []:
            raise ValueError("VRER R0 receipt contains revealed labels")
    if primary.get("source_candidates_sha256") != recheck.get(
        "source_candidates_sha256"
    ):
        raise ValueError("VRER source candidate hashes differ")
    left = _records(primary)
    right = _records(recheck)
    if set(left) != set(right):
        raise ValueError("VRER independent candidate inventories differ")
    sample = reproducibility_sample(list(left))
    mismatches: list[dict[str, str]] = []
    for candidate_id in sample:
        for field in COMPARE_FIELDS:
            if left[candidate_id].get(field) != right[candidate_id].get(field):
                mismatches.append({"candidate_id": candidate_id, "field": field})
    return {
        "protocol": REPRODUCTION_PROTOCOL,
        "candidate_count": len(left),
        "sample_fraction": 0.20,
        "sample_count": len(sample),
        "sample_candidate_ids": sample,
        "compared_fields": list(COMPARE_FIELDS),
        "mismatches": mismatches,
        "reproducible": not mismatches,
    }


def verify(primary_path: Path, recheck_path: Path, output: Path) -> Path:
    if output.exists():
        raise ValueError("VRER reproduction output already exists")
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    recheck = json.loads(recheck_path.read_text(encoding="utf-8"))
    reproduction = compare_receipts(primary, recheck)
    records = list(_records(primary).values())
    summary = summarize_r0(
        records, reproducible_audit=bool(reproduction["reproducible"])
    )
    payload = {
        "protocol": REPRODUCTION_PROTOCOL,
        "primary_receipt_sha256": sha256_file(primary_path),
        "recheck_receipt_sha256": sha256_file(recheck_path),
        "source_candidates_sha256": primary["source_candidates_sha256"],
        "reproduction": reproduction,
        "summary": summary,
        "records": records,
        "protected_data_inputs": [],
        "revealed_label_inputs": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--recheck", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    path = verify(args.primary.resolve(), args.recheck.resolve(), args.output.resolve())
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
