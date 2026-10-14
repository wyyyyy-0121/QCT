#!/usr/bin/env python3
"""Verify byte-identical independent FSPR label-free runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

EXPECTED_FILES = {
    "calibration_records.jsonl",
    "label_free_receipt.json",
    "model.json",
    "oof_predictions.jsonl",
}
RECEIPT_HASH_FIELDS = {
    "calibration_records.jsonl": "calibration_records_sha256",
    "model.json": "model_sha256",
    "oof_predictions.jsonl": "oof_predictions_sha256",
}
ZERO_INPUT_FIELDS = (
    "fault_label_inputs",
    "revealed_localization_inputs",
    "answer_workbook_inputs",
    "task_text_inputs",
    "protected_data_inputs",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    observed = {path.name for path in root.iterdir()}
    if observed != EXPECTED_FILES:
        raise ValueError(f"unexpected FSPR run inventory: {root}")
    return {name: sha256_file(root / name) for name in sorted(EXPECTED_FILES)}


def validate_receipt(
    receipt: dict[str, object],
    hashes: dict[str, str],
    run_name: str,
) -> None:
    if receipt.get("protocol") != "formulaguard_fspr_label_free_gate_v1":
        raise ValueError(f"FSPR {run_name} receipt protocol mismatch")
    if receipt.get("complete") is not True:
        raise ValueError(f"FSPR {run_name} receipt is incomplete")
    for artifact, field in RECEIPT_HASH_FIELDS.items():
        if receipt.get(field) != hashes[artifact]:
            raise ValueError(f"FSPR {run_name} receipt hash mismatch: {artifact}")
    if any(receipt.get(field) != [] for field in ZERO_INPUT_FIELDS):
        raise ValueError(f"FSPR {run_name} receipt contains forbidden inputs")


def verify(run_a: Path, run_b: Path, output: Path) -> dict[str, object]:
    if run_a.resolve() == run_b.resolve():
        raise ValueError("FSPR reproduction requires two distinct run directories")
    hashes_a, hashes_b = file_hashes(run_a), file_hashes(run_b)
    receipt_a = json.loads((run_a / "label_free_receipt.json").read_text(encoding="ascii"))
    receipt_b = json.loads((run_b / "label_free_receipt.json").read_text(encoding="ascii"))
    validate_receipt(receipt_a, hashes_a, "run A")
    validate_receipt(receipt_b, hashes_b, "run B")
    byte_identical = hashes_a == hashes_b
    single_process_passed = bool(
        receipt_a.get("gates", {}).get("all_single_process_gates_passed")
        and receipt_b.get("gates", {}).get("all_single_process_gates_passed")
    )
    payload = {
        "protocol": "formulaguard_fspr_reproduction_v1",
        "complete": True,
        "run_a_hashes": hashes_a,
        "run_b_hashes": hashes_b,
        "byte_identical": byte_identical,
        "single_process_gates_passed": single_process_passed,
        "all_label_free_gates_passed": byte_identical and single_process_passed,
        "fault_label_inputs": [],
        "revealed_localization_inputs": [],
        "answer_workbook_inputs": [],
        "task_text_inputs": [],
        "protected_data_inputs": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    allowed = {"reproduction_receipt.json"}
    if {path.name for path in output.iterdir()} - allowed:
        raise ValueError("FSPR reproduction output contains unexpected files")
    destination = output / "reproduction_receipt.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, destination)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = verify(args.run_a.resolve(), args.run_b.resolve(), args.output.resolve())
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
