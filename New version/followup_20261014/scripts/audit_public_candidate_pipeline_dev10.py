"""Run the frozen paper pipeline on already revealed public workbooks.

This is a development compatibility/risk audit only.  The eleven files were
downloaded before final-model freezing and are permanently excluded from final
validation.  The worker never opens truth, score, answer, or mutation files;
there are no business labels for these workbooks, so this run deliberately
does not compute accuracy.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
RAW_ROOT = REPO / "data/external/hybridguard_candidate_audit_dev1/workbooks"
RUN = ROOT / "development/public_candidate_pipeline_dev10"
REPORT = ROOT / "development/public_candidate_audit_dev7/REPORT.json"
PYTHON = REPO / ".venv/bin/python"
TIMEOUT_SECONDS = 180

FORBIDDEN = ("truth.json", "score.json", "answer", "errata", "mutation_log",
             "input_oracle", "failure_audit", "/results/")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path):
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    if path.suffix == ".gz":
        with gzip.GzipFile(filename=str(path), mode="wb", mtime=0) as handle:
            handle.write(payload)
    else:
        path.write_bytes(payload)


def entries():
    records = read(REPORT)["records"]
    result = []
    for number, record in enumerate(records, 1):
        relative = Path(record["path"])
        path = REPO / relative
        if not path.exists():
            raise FileNotFoundError(path)
        result.append({
            "id": f"public{number:02d}",
            "origin": record["origin"],
            "discovery_label": record["discovery_label"],
            "source_url": record["url"],
            "relative_path": str(relative),
            "sha256": sha(path),
            "bytes": path.stat().st_size,
            "final_validation_eligible": False,
            "business_labels_available": False,
        })
    return result


def deny_evidence(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    name = os.fsdecode(args[0]).casefold()
    if any(token in name for token in FORBIDDEN):
        raise PermissionError("public pipeline cannot open scoring evidence: " + name)


def load_adapter():
    source = ROOT / "baseline/scripts/predict.py"
    spec = importlib.util.spec_from_file_location("frozen_hybridguard_adapter_dev10", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def worker(case_id: str, relative: str) -> None:
    """Execute one workbook in a fresh process so a timeout is retained."""
    sys.addaudithook(deny_evidence)
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "baseline/source/HybridGuard_V5_handoff_20260904/src"))
    from formulaguard.workbook import WorkbookModel
    from formulaguard.v5_structural_guard import v5_structural_guard_scores
    from structuralguard.detector import analyze_workbook
    from structuralguard.formula import profile_formula
    from selector_dev2 import select as select_dev2
    from selector_dev4 import review_guard
    from selector_dev5 import augment as augment_dev5
    from selector_dev6 import augment as augment_dev6
    from selector_dev9 import augment as augment_dev9

    path = REPO / relative
    started = time.perf_counter()
    started_cpu = time.process_time()
    model = WorkbookModel.from_xlsx(path)
    observed = {sheet + "!" + address: formula
                for (sheet, address), formula in model.formulas.items()}
    profiles = collections.Counter()
    profile_failures = []
    for (sheet, address), formula in model.formulas.items():
        try:
            profiles.update(profile_formula(formula, address, sheet).functions)
        except Exception as error:  # retain unsupported syntax evidence
            profile_failures.append({"cell": sheet + "!" + address,
                                     "error": repr(error)})

    structural = analyze_workbook(path)["results"]
    sg_rows = [dict(item, cell=item["sheet"] + "!" + item["cell"])
               for item in structural]
    fg_rows = [{"rank": rank, "cell": item.cell_label, "score": item.score,
                "candidate_formula": item.candidate_formula,
                "evidence": item.evidence}
               for rank, item in enumerate(v5_structural_guard_scores(model), 1)]
    paper = load_adapter().hybrid((model, structural, fg_rows, observed, []), {})
    dev2 = select_dev2(model, paper, fg_rows, structural, [])
    dev4 = review_guard(model, dev2)
    dev5 = augment_dev5(model, dev4, [])
    dev6 = augment_dev6(model, dev4, [])
    dev9 = augment_dev9(model, dev4, [])
    before = dict(model.formulas)
    assert model.formulas == before

    evaluation_errors = {}
    evaluated = 0
    try:
        _values, errors = model.evaluate()
        evaluation_errors = {sheet + "!" + address: str(value)
                             for (sheet, address), value in errors.items()}
        evaluated = len(observed) - len(evaluation_errors)
    except Exception as error:
        evaluation_errors = {"__workbook__": repr(error)}

    def summary(prediction):
        rows = prediction["rows"]
        proposals = [row for row in rows if row.get("status") == "propose"
                     and row.get("suggested_formula")
                     and row["suggested_formula"] != observed[row["cell"]]]
        return {
            "formula_rows": len(rows),
            "proposals": len(proposals),
            "status_counts": dict(collections.Counter(row.get("status", "?") for row in rows)),
            "reason_counts": dict(collections.Counter(row.get("reason", "unspecified") for row in rows)),
            "unsupported_rows": sum(row.get("status") == "unsupported" for row in rows),
        }

    result = {
        "id": case_id,
        "relative_path": relative,
        "input_sha256": sha(path),
        "formula_cells": len(observed),
        "sheet_names": sorted({sheet for sheet, _ in model.formulas}),
        "functions": dict(profiles),
        "profile_failures": profile_failures,
        "evaluation_errors": evaluation_errors,
        "evaluated_without_error": evaluated,
        "predictions": {"paper": paper, "dev2": dev2, "dev4": dev4,
                        "dev5": dev5, "dev6": dev6, "dev9": dev9},
        "prediction_summaries": {name: summary(prediction) for name, prediction in
                                  [("paper", paper), ("dev2", dev2), ("dev4", dev4),
                                   ("dev5", dev5), ("dev6", dev6), ("dev9", dev9)]},
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - started_cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "status": "inference_complete_unscored",
        "labels_read": [],
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def source_files():
    files = [Path(__file__), REPORT, ROOT / "baseline/scripts/predict.py"]
    files += [ROOT / "scripts" / name for name in
              ["selector_dev2.py", "selector_dev3.py", "selector_dev4.py",
               "selector_dev5.py", "selector_dev6.py", "selector_dev9.py"]]
    files += sorted((ROOT / "baseline/source").rglob("*.py"))
    return {str(path.relative_to(ROOT)): sha(path) for path in files}


def predict() -> None:
    if RUN.exists():
        raise SystemExit(f"Preserve existing dev10 run: {RUN}")
    items = entries()
    RUN.mkdir(parents=True)
    save(RUN / "registration.json", {
        "role": "revealed public workbook pipeline compatibility and risk audit",
        "origin": "11 workbooks from seven already contacted public candidate groups",
        "final_validation_eligible": False,
        "business_labels_available": False,
        "accepted_sources": 0,
        "accepted_template_families": 0,
        "selection": "all records from the previously fixed candidate-audit report",
        "score_policy": "no precision or coverage; cached values and suggestions are not truth",
        "exclusion": "the entire candidate origin set is excluded from final validation",
    })
    save(RUN / "public_index.json", items)
    save(RUN / "source_lock.json", {"version": "dev10-public-pipeline-v1",
                                     "files": source_files()})
    reports = []
    files = {}
    wall = time.perf_counter()
    cpu = time.process_time()
    for item in items:
        command = [str(PYTHON), str(Path(__file__)), "--worker", item["id"],
                   item["relative_path"]]
        started = time.perf_counter()
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True,
                                       text=True, timeout=TIMEOUT_SECONDS, check=False)
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            if completed.returncode != 0 or not lines:
                raise RuntimeError("worker_exit_%s stdout=%r stderr=%r" %
                                   (completed.returncode, completed.stdout[-2000:],
                                    completed.stderr[-2000:]))
            report = json.loads(lines[-1])
            if report.get("status") != "inference_complete_unscored":
                raise RuntimeError("worker_report_status=" + repr(report.get("status")))
            report["worker_wall_seconds"] = time.perf_counter() - started
            report["worker_stderr"] = completed.stderr[-4000:]
            target = RUN / "predictions" / (item["id"] + ".json.gz")
            save(target, report)
            files[str(target.relative_to(RUN))] = sha(target)
        except subprocess.TimeoutExpired as error:
            report = {"id": item["id"], "relative_path": item["relative_path"],
                      "input_sha256": item["sha256"], "status": "timeout",
                      "timeout_seconds": TIMEOUT_SECONDS,
                      "error": repr(error), "labels_read": []}
        except Exception as error:
            report = {"id": item["id"], "relative_path": item["relative_path"],
                      "input_sha256": item["sha256"], "status": "inference_failed",
                      "error": repr(error), "labels_read": []}
            target = RUN / "predictions" / (item["id"] + ".json.gz")
            save(target, report)
            files[str(target.relative_to(RUN))] = sha(target)
        reports.append(report)
        print(item["id"], item["origin"], item["discovery_label"], report["status"],
              report.get("formula_cells"), flush=True)
    audit = {
        "role": "revealed public workbook pipeline compatibility/risk audit",
        "version": "dev10-public-pipeline-v1",
        "cases": [{key: value for key, value in report.items()
                   if key not in {"predictions", "worker_stderr"}}
                  for report in reports],
        "case_count": len(reports),
        "status_counts": dict(collections.Counter(report["status"] for report in reports)),
        "precision": None,
        "coverage": None,
        "business_labels_available": False,
        "new_final_sources": 0,
        "new_final_families": 0,
        "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "command": [str(PYTHON), str(Path(__file__)), "predict"],
        "limitations": [
            "The eleven workbooks were revealed before model freezing and are excluded from final validation.",
            "No authoritative natural-error labels or clean-to-injected records are available.",
            "A proposal count is a risk diagnostic, not a correctness score.",
            "Unsupported formulas and evaluation failures remain in the audit and are not removed from denominators.",
        ],
    }
    save(RUN / "audit.json", audit)
    files["audit.json"] = sha(RUN / "audit.json")
    files["public_index.json"] = sha(RUN / "public_index.json")
    files["registration.json"] = sha(RUN / "registration.json")
    files["source_lock.json"] = sha(RUN / "source_lock.json")
    save(RUN / "prediction_lock.json", {
        "files": files,
        "source_lock_sha256": sha(RUN / "source_lock.json"),
        "inputs": {item["relative_path"]: item["sha256"] for item in items},
        "labels_read": [],
        "final_validation_eligible": False,
        "role": "unscored revealed public-development audit",
    })
    print("DEV10 PREDICTION LOCK COMPLETE", len(reports), flush=True)


def verify() -> None:
    lock = read(RUN / "prediction_lock.json")
    assert lock["final_validation_eligible"] is False
    assert lock["labels_read"] == []
    for relative, expected in read(RUN / "source_lock.json")["files"].items():
        assert sha(ROOT / relative) == expected, relative
    assert sha(RUN / "source_lock.json") == lock["source_lock_sha256"]
    for relative, expected in lock["files"].items():
        assert sha(RUN / relative) == expected, relative
    for relative, expected in lock["inputs"].items():
        assert sha(REPO / relative) == expected, relative
    audit = read(RUN / "audit.json")
    assert audit["precision"] is None and audit["coverage"] is None
    assert audit["case_count"] == 11
    assert audit["new_final_sources"] == audit["new_final_families"] == 0
    reports = [read(path) for path in sorted((RUN / "predictions").glob("*.json.gz"))]
    assert len(reports) == 11
    for report in reports:
        assert report["labels_read"] == []
        assert report["input_sha256"] == lock["inputs"][report["relative_path"]]
        if report["status"] == "inference_complete_unscored":
            for prediction in report["predictions"].values():
                assert len(prediction["rows"]) == report["formula_cells"]
        else:
            assert report["status"] == "inference_failed"
    print("DEV10 LOCK VERIFIED", len(reports), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", nargs="?", choices=["predict", "verify"])
    parser.add_argument("--worker", nargs=2, metavar=("ID", "RELATIVE"))
    args = parser.parse_args()
    if args.worker:
        worker(*args.worker)
    elif args.stage == "predict":
        predict()
    elif args.stage == "verify":
        verify()
    else:
        parser.error("stage is required unless --worker is used")


if __name__ == "__main__":
    main()
