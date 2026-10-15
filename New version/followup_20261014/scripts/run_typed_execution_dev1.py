"""Audit typed execution semantics on the excluded Pycel fixtures.

This run compares the frozen original evaluator, the typed adapter, and the
already locked LibreOffice observations.  It has no business labels and cannot
authorize a formula repair or add a final-validation source.
"""
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "development/public_pycel_dev1"
REFERENCE = ROOT / "development/execution_reference_dev1"
RUN = ROOT / os.environ.get("TYPED_EXECUTION_RUN", "development/typed_execution_dev1")
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "baseline/source/HybridGuard_V5_handoff_20260904/src"))

from execution_reference import compare, formula_declarations, typed_value as original_typed_value
from typed_execution_adapter import ExcelError, TypedExecutionAdapter, typed_value
from formulaguard.workbook import WorkbookModel


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n")


def locked_reference_inputs():
    lock = read(REFERENCE / "execution_lock.json")
    assert sha(REFERENCE / "source_lock.json") == lock["source_lock_sha256"]
    assert sha(REFERENCE / "registration.json") == lock["registration_sha256"]
    for relative, expected in read(REFERENCE / "source_lock.json")["files"].items():
        assert sha(ROOT / relative) == expected, relative
    for relative, expected in lock["files"].items():
        assert sha(REFERENCE / relative) == expected, relative
    assert not lock["business_labels_read"] and not lock["repair_proposals_generated"]
    registration = read(REFERENCE / "registration.json")
    return lock, registration["selected_files"]


def sources():
    return [Path(__file__), ROOT / "scripts/typed_execution_adapter.py",
            ROOT / "tests/test_typed_execution_adapter.py"]


def register():
    if RUN.exists():
        raise SystemExit("Preserve typed execution evidence; select a new run")
    previous_lock, selected = locked_reference_inputs()
    files = {str(path.relative_to(ROOT)): sha(path) for path in sources()}
    save(RUN / "registration.json", {
        "role": "revealed development execution compatibility audit",
        "origin": "dgorissen/pycel pinned fixtures; permanently excluded from final validation",
        "selected_files": selected, "case_count": len(selected),
        "new_final_sources": 0, "new_final_families": 0,
        "business_labels_available": False, "business_labels_read": [],
        "repair_proposals_generated": False,
        "reference": "locked LibreOffice observations from execution_reference_dev1",
        "comparison": "typed values; numeric relative/absolute tolerance 1e-8; errors retain codes",
        "previous_execution_lock_sha256": sha(REFERENCE / "execution_lock.json"),
        "source_files": files, "python": platform.python_version(),
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    save(RUN / "source_lock.json", {
        "files": files,
        "inputs": {relative: sha(PUBLIC / "raw" / relative) for relative in selected},
        "reference_files": {relative: sha(REFERENCE / relative)
                            for relative in previous_lock["files"]},
        "reference_execution_lock_sha256": sha(REFERENCE / "execution_lock.json"),
    })
    print("Registered", len(selected), "excluded compatibility cases", flush=True)


def verify_source():
    lock = read(RUN / "source_lock.json")
    for relative, expected in lock["files"].items():
        assert sha(ROOT / relative) == expected, relative
    for relative, expected in lock["inputs"].items():
        assert sha(PUBLIC / "raw" / relative) == expected, relative
    for relative, expected in lock["reference_files"].items():
        assert sha(REFERENCE / relative) == expected, relative
    assert sha(REFERENCE / "execution_lock.json") == lock["reference_execution_lock_sha256"]
    return read(RUN / "registration.json")["selected_files"]


def adapter_typed(value, errors, key):
    if key in errors:
        return {"kind": "error", "error": str(errors[key])}
    return typed_value(value.get(key))


def execute():
    if (RUN / "execution.json").exists() or (RUN / "cases").exists():
        raise SystemExit("Preserve typed execution evidence")
    selected = verify_source()
    cases, files = [], {}
    for number, relative in enumerate(selected, 1):
        source = PUBLIC / "raw" / relative
        case_id = f"public{number:02d}"
        declarations = formula_declarations(source)
        model = WorkbookModel.from_xlsx(source)
        original_values, original_errors = model.evaluate()
        adapter = TypedExecutionAdapter.from_xlsx(source)
        typed_values, typed_errors = adapter.evaluate()
        original = {sheet + "!" + address: original_typed_value(
            original_values.get((sheet, address)), original_errors.get((sheet, address)))
                    for sheet, address in model.formulas}
        typed = {sheet + "!" + address: adapter_typed(
            typed_values, typed_errors, (sheet, address))
                 for sheet, address in model.formulas}
        output = {"id": case_id, "source_path": relative,
                  "input_sha256": sha(source),
                  "raw_formula_declarations": len(declarations),
                  "loaded_formula_cells": len(model.formulas),
                  "loaded_formula_omissions": sorted(set(declarations) - set(original)),
                  "original": original, "typed_adapter": typed,
                  "adapter_error_count": len(typed_errors),
                  "adapter_version": adapter.VERSION,
                  "source_hash_after": sha(source)}
        target = RUN / "cases" / (case_id + ".json")
        save(target, output)
        files[str(target.relative_to(RUN))] = sha(target)
        cases.append({key: value for key, value in output.items() if key not in {"original", "typed_adapter"}})
        print(case_id, relative, "formula_cells", len(model.formulas),
              "adapter_errors", len(typed_errors), flush=True)
    report = {"status": "complete", "role": "typed execution compatibility only",
              "final_validation_eligible": False, "business_labels_available": False,
              "business_labels_read": [], "repair_proposals_generated": False,
              "cases": cases, "case_count": len(cases),
              "command": [sys.executable, *sys.argv],
              "python": platform.python_version(),
              "interpretation": "Typed execution agreement is not a business-intent or repair label.",
              "source_hashes": {relative: sha(PUBLIC / "raw" / relative) for relative in selected}}
    save(RUN / "execution.json", report)
    files["execution.json"] = sha(RUN / "execution.json")
    save(RUN / "execution_lock.json", {
        "files": files, "source_lock_sha256": sha(RUN / "source_lock.json"),
        "registration_sha256": sha(RUN / "registration.json"),
        "inputs": report["source_hashes"], "business_labels_read": [],
        "repair_proposals_generated": False})


def analyze_case(entry):
    case_id = entry["id"]
    details = read(RUN / "cases" / (case_id + ".json"))
    reference = read(REFERENCE / "cases" / (case_id + "_reference.json"))
    if entry["raw_formula_declarations"] != entry["loaded_formula_cells"]:
        # Array followers and other declarations absent from the original
        # reader are retained as omissions rather than silently scored.
        pass
    counts = Counter()
    rows = []
    for label in sorted(details["original"]):
        original = details["original"][label]
        typed = details["typed_adapter"][label]
        independent = reference["cells"].get(label)
        relation = compare(typed, independent) if independent is not None else "reference_missing"
        original_relation = compare(original, typed)
        counts["typed_vs_reference_" + relation] += 1
        counts["original_vs_typed_" + original_relation] += 1
        rows.append({"cell": label, "original_model": original,
                     "typed_adapter": typed, "libreoffice": independent,
                     "original_vs_typed": original_relation,
                     "typed_vs_reference": relation})
    save(RUN / "cases" / (case_id + "_analysis.json"), {
        "id": case_id, "details": rows, "comparisons": dict(counts),
        "loaded_formula_cells": len(rows),
        "raw_formula_declarations": entry["raw_formula_declarations"],
        "loaded_formula_omissions": entry["loaded_formula_omissions"]})
    return counts, rows


def analyze():
    verify_execution()
    execution = read(RUN / "execution.json")
    totals, cases = Counter(), []
    files = {}
    for entry in execution["cases"]:
        counts, rows = analyze_case(entry)
        totals.update(counts)
        analysis = {"id": entry["id"], "comparisons": dict(counts),
                    "detail_count": len(rows)}
        cases.append(analysis)
        target = RUN / "cases" / (entry["id"] + "_analysis.json")
        files[str(target.relative_to(RUN))] = sha(target)
    report = {"status": "complete", "cases": cases, "case_count": len(cases),
              "totals": dict(totals), "business_labels_available": False,
              "precision": None, "coverage": None, "final_validation_eligible": False,
              "interpretation": "No compatibility comparison supplies a repair label.",
              "execution_lock_sha256": sha(RUN / "execution_lock.json")}
    save(RUN / "analysis.json", report)
    files["analysis.json"] = sha(RUN / "analysis.json")
    save(RUN / "analysis_lock.json", {"files": files,
                                      "analysis_sha256": sha(RUN / "analysis.json"),
                                      "execution_lock_sha256": sha(RUN / "execution_lock.json")})
    print(json.dumps(dict(totals), indent=2), flush=True)


def verify_execution():
    selected = verify_source()
    lock = read(RUN / "execution_lock.json")
    assert sha(RUN / "source_lock.json") == lock["source_lock_sha256"]
    assert sha(RUN / "registration.json") == lock["registration_sha256"]
    for relative, expected in lock["files"].items():
        assert sha(RUN / relative) == expected, relative
    assert lock["inputs"] == {relative: sha(PUBLIC / "raw" / relative) for relative in selected}
    assert not lock["business_labels_read"] and not lock["repair_proposals_generated"]


def verify():
    verify_execution()
    analysis_lock = read(RUN / "analysis_lock.json")
    for relative, expected in analysis_lock["files"].items():
        assert sha(RUN / relative) == expected, relative
    assert sha(RUN / "analysis.json") == analysis_lock["analysis_sha256"]
    assert sha(RUN / "execution_lock.json") == analysis_lock["execution_lock_sha256"]
    execution = read(RUN / "execution.json")
    analysis = read(RUN / "analysis.json")
    assert analysis["precision"] is None and analysis["coverage"] is None
    totals, case_count = Counter(), 0
    for entry in execution["cases"]:
        details = read(RUN / "cases" / (entry["id"] + ".json"))
        result = read(RUN / "cases" / (entry["id"] + "_analysis.json"))
        assert len(details["original"]) == len(result["details"])
        recomputed, _ = analyze_case(entry)
        assert dict(recomputed) == result["comparisons"]
        totals.update(recomputed); case_count += 1
    assert case_count == analysis["case_count"] == 14
    assert dict(totals) == analysis["totals"]
    output = {"all_locks_verified": True, "all_cases_replayed": True,
              "typed_adapter_results_recomputed": True,
              "business_labels_available": False, "final_validation_eligible": False,
              "precision": None, "coverage": None, "case_count": case_count,
              "totals": dict(totals), "analysis_sha256": sha(RUN / "analysis.json"),
              "verifier_sha256": sha(Path(__file__))}
    save(ROOT / "qa/TYPED_EXECUTION_DEV1_VERIFICATION_20261015.json", output)
    print(json.dumps(output, indent=2), flush=True)


if __name__ == "__main__":
    {"register": register, "execute": execute, "analyze": analyze,
     "verify": verify}[sys.argv[1]]()
