"""Validate hashes, inventories, and clean-formula truth for an SG benchmark."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_hashes(dataset: Path) -> int:
    manifest = dataset / "SHA256SUMS.txt"
    entries = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        entries[relative] = digest
    actual = {
        path.relative_to(dataset).as_posix(): sha256(path)
        for path in dataset.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    if entries != actual:
        raise ValueError("SHA256SUMS.txt does not exactly match dataset files")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    labels = json.loads((dataset / "labels" / "answer_keys.json").read_text(encoding="utf-8"))
    metadata = json.loads((dataset / "metadata.json").read_text(encoding="utf-8"))
    cases = labels["cases"]
    clean_cases = {case["scenario"]: case for case in cases if case["condition"] == "clean"}
    clean_models = {
        scenario: WorkbookModel.from_xlsx(dataset / case["workbook"])
        for scenario, case in clean_cases.items()
    }
    manifest_rows = list(csv.DictReader(
        (dataset / "public" / "manifest.csv").open(encoding="utf-8", newline="")
    ))
    if [row["case_id"] for row in manifest_rows] != [case["case_id"] for case in cases]:
        raise ValueError("public manifest case order or inventory mismatch")

    total_formulas = 0
    total_errors = 0
    for case in cases:
        workbook_path = dataset / case["workbook"]
        if sha256(workbook_path) != case["sha256"]:
            raise ValueError(f"workbook hash mismatch: {case['case_id']}")
        model = WorkbookModel.from_xlsx(workbook_path)
        if len(model.formula_cells) != int(case["formula_cells"]):
            raise ValueError(f"formula inventory mismatch: {case['case_id']}")
        total_formulas += len(model.formula_cells)
        total_errors += len(case["errors"])
        clean = clean_models[case["scenario"]]
        for error in case["errors"]:
            cell = (str(error["sheet"]), str(error["cell"]))
            expected = str(error["expected_formula"])
            injected = str(error["injected_formula"])
            if normalized_formula(expected) != normalized_formula(clean.formulas.get(cell, "")):
                raise ValueError(f"answer does not match clean formula: {case['case_id']} {cell}")
            if normalized_formula(injected) != normalized_formula(model.formulas.get(cell, "")):
                raise ValueError(f"injected formula does not match workbook: {case['case_id']} {cell}")
            if normalized_formula(injected) == normalized_formula(expected):
                raise ValueError(f"injected and expected formulas are equal: {case['case_id']} {cell}")

    counts = Counter(case["condition"] for case in cases)
    if len(cases) != int(metadata["case_count"]):
        raise ValueError("metadata case count mismatch")
    if total_formulas != int(metadata["formula_cells"]):
        raise ValueError("metadata formula count mismatch")
    if total_errors != int(metadata["injected_errors"]):
        raise ValueError("metadata error count mismatch")
    if dict(counts) != metadata["conditions"]:
        raise ValueError("metadata condition counts mismatch")
    report = {
        "protocol": labels["protocol"],
        "cases": len(cases),
        "formula_cells": total_formulas,
        "errors": total_errors,
        "condition_counts": dict(counts),
        "hashed_files": validate_hashes(dataset),
        "answers_match_clean_formulas": True,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
