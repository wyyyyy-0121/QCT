#!/usr/bin/env python3
"""Read-only workbook interface for the frozen paper and dev11 comparator.

This is a new execution interface, not a new repair algorithm. No scoring data
is read. Use a separate process and runner timeout for each workbook.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT.parent / "followup_20261014"
sys.path[:0] = [str(LEGACY / "scripts"),
               str(LEGACY / "baseline/source/HybridGuard_V5_handoff_20260904/src")]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def predict(input_path, parallel_sheets):
    from formulaguard.workbook import WorkbookModel
    from formulaguard.v5_structural_guard import v5_structural_guard_scores
    from structuralguard.detector import analyze_workbook
    from selector_dev2 import select
    from selector_dev4 import review_guard
    from selector_dev6 import augment
    from selector_dev11 import qualify
    model = WorkbookModel.from_xlsx(input_path)
    observed = {sheet + "!" + address: formula
                for (sheet, address), formula in model.formulas.items()}
    structural = analyze_workbook(input_path)["results"]
    fg = [dict(rank=rank, cell=value.cell_label, score=value.score,
               candidate_formula=value.candidate_formula, evidence=value.evidence)
          for rank, value in enumerate(v5_structural_guard_scores(model), 1)]
    spec = importlib.util.spec_from_file_location("frozen_paper_adapter",
                                                LEGACY / "baseline/scripts/predict.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    paper = adapter.hybrid((model, structural, fg, observed, parallel_sheets), {})
    dev11 = qualify(model, augment(model, review_guard(
        model, select(model, paper, fg, structural, parallel_sheets)), parallel_sheets))
    assert observed == {s + "!" + a: f for (s, a), f in model.formulas.items()}
    return {"paper": paper, "dev11": dev11, "formula_cells": len(observed),
            "observed_formulas": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parallel-sheets", nargs="*", default=[])
    args = parser.parse_args()
    source, output = args.input.resolve(), args.output.resolve()
    if not source.is_file() or source == output or output.exists():
        raise SystemExit("Input must exist and output must be new and distinct")
    before = sha(source)
    accesses = set()

    def guard(event, values):
        if event != "open" or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path == source:
            mode = values[1] if len(values) > 1 else None
            flags = values[2] if len(values) > 2 else 0
            if (isinstance(mode, str) and any(c in mode for c in "wa+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError("Source workbook is read-only")
            accesses.add(str(path))
            return
        low = str(path).casefold()
        if path.suffix in (".xlsx", ".xlsm", ".xls", ".ods") or any(
                token in low for token in ("truth", "training_labels", "author_diff", "score.json", "after.xlsx")):
            raise PermissionError("Prediction cannot read other workbooks or scoring evidence: " + str(path))

    sys.addaudithook(guard)
    result = predict(source, args.parallel_sheets)
    assert sha(source) == before
    result.update(input_sha256=before, original_unchanged=True, status="complete",
                  parallel_sheets=args.parallel_sheets, labels_read=[],
                  input_accesses=sorted(accesses), final_validation_eligible=False,
                  role="development inference; paper and dev11 unchanged")
    with output.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    print("Predicted", result["formula_cells"], "formula cells; original unchanged", flush=True)


if __name__ == "__main__":
    main()
