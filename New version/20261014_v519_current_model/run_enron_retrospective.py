"""Run frozen V519 on the previously reviewed Enron inputs, then score labels."""

import argparse
import csv
import gzip
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PYTHON = ROOT / ".venv/bin/python"
OUT = ROOT / "New version/20261014_v519_enron_retrospective"
LOCK = ROOT / "New version/20261014_v519_current_model/freeze/source_lock.json"
MANIFEST = ROOT / "data/external/enron/manifest.csv"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now():
    return datetime.now(timezone.utc).isoformat()


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def worker(workbook, backend, output):
    from formulaguard.formula import FormulaSyntaxError, parse_formula
    from formulaguard.v5_1_5_development import model_binding
    from formulaguard.v5_1_9_development import diagnose_v5_1_9_development
    from formulaguard.workbook import WorkbookModel

    started = time.perf_counter()
    model = WorkbookModel.from_xlsx(workbook)
    before = model_binding(model)
    supported = 0
    for formula in model.formulas.values():
        try:
            parse_formula(formula)
            supported += 1
        except FormulaSyntaxError:
            pass
    loaded = time.perf_counter()
    diagnosis = diagnose_v5_1_9_development(
        model, localization_backend=backend, repair_policy="structural",
        documents=(), approvals={}, as_of=date(2026, 10, 14),
    )
    completed = time.perf_counter()
    assert model_binding(model) == before
    payload = {"backend": backend, "workbook_sha256": sha(workbook),
               "formula_cells": len(model.formulas), "supported_formula_cells": supported,
               "load_seconds": loaded - started, "diagnosis_seconds": completed - loaded,
               "model_unchanged": True, "documents": [], "approvals": {},
               "as_of": "2026-10-14", "diagnosis": asdict(diagnosis),
               "formulas": [[*cell, formula] for cell, formula in sorted(model.formulas.items())]}
    with gzip.open(output, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def run_task(task, timeout):
    ident, backend, workbook = task
    target = OUT / f"predictions/{ident}_{backend}.json.gz"
    log = OUT / f"logs/{ident}_{backend}.log"
    argv = [str(PYTHON), str(Path(__file__).resolve()), "worker", "--workbook", str(workbook),
            "--backend", backend, "--output", str(target)]
    started = time.perf_counter()
    with log.open("w") as handle:
        try:
            proc = subprocess.run(argv, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
            status = "completed" if proc.returncode == 0 else "runtime_error"
            code = proc.returncode
        except subprocess.TimeoutExpired:
            status, code = "timeout", None
    return {"id": ident, "backend": backend, "status": status, "exit_code": code,
            "elapsed_seconds": time.perf_counter() - started,
            "prediction": target.relative_to(OUT).as_posix() if status == "completed" else None,
            "prediction_sha256": sha(target) if status == "completed" else None,
            "argv": argv}


def evaluate():
    from formulaguard.benchmark import parse_cell_label
    from formulaguard.formula import FormulaSyntaxError, parse_formula
    from scripts.evaluate_v519_confirmation import verify_lock

    verify_lock(LOCK)
    OUT.mkdir(exist_ok=False)
    (OUT / "predictions").mkdir()
    (OUT / "logs").mkdir()
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8-sig")))
    assert len(rows) == 36 and sum(r["include"] == "1" for r in rows) == 30
    (OUT / "ORIGINAL_MANIFEST.csv").write_bytes(MANIFEST.read_bytes())
    paths = sorted({(MANIFEST.parent / r["workbook"]).resolve() for r in rows if r["include"] == "1"})
    inputs = [{"id": hashlib.sha256(p.relative_to(ROOT).as_posix().encode()).hexdigest()[:20],
               "path": str(p), "sha256": sha(p)} for p in paths]
    tasks = [(r["id"], b, Path(r["path"])) for r in inputs for b in ("v4", "v511")]
    save(OUT / "PROTOCOL.json", {"written_at": now(), "model": "V5.1.9-development",
         "scope": "previously revealed Enron retrospective regression, not a new held-out dataset",
         "source_lock": str(LOCK), "source_lock_sha256": sha(LOCK),
         "original_events": 36, "preincluded_events": 30, "preexcluded_events": 6,
         "unique_workbooks": len(paths), "backends": ["v4", "v511"], "workers": 4,
         "timeout_seconds_per_workbook_and_backend": 180,
         "documents": [], "approvals": {}, "inputs": inputs,
         "metrics": ["any-labeled-source Top1/Top5/Top10 event hit", "labeled cell recall at 10"],
         "denominators": "all 30 preincluded events; timeouts/errors are misses in the conservative rate; successful-input rates are separately reported",
         "repair_accuracy": "not scored: no correct formulas in the existing manifest",
         "label_boundary": "workers receive only workbook path/backend; scoring reads cell labels after prediction lock"})
    completed = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run_task, task, 180) for task in tasks]
        for future in as_completed(futures):
            record = future.result()
            completed.append(record)
            save(OUT / "EXECUTION_PROGRESS.json", completed)
            print(f"Enron {len(completed)}/{len(tasks)}: {record['backend']} {record['id']} {record['status']} {record['elapsed_seconds']:.1f}s", flush=True)
    verify_lock(LOCK)
    assert sha(MANIFEST) == sha(OUT / "ORIGINAL_MANIFEST.csv")
    assert all(sha(Path(r["path"])) == r["sha256"] for r in inputs)
    completed.sort(key=lambda r: (r["id"], r["backend"]))
    save(OUT / "PREDICTION_LOCK.json", {"completed_at": now(), "source_lock_sha256": sha(LOCK),
         "manifest_sha256": sha(MANIFEST), "labels_read_by_workers": [],
         "workbooks": len(inputs), "tasks": len(tasks), "records": completed})
    by_path = {r["path"]: r["id"] for r in inputs}
    predictions, task_by_key = {}, {(r["id"], r["backend"]): r for r in completed}
    for record in completed:
        if record["status"] == "completed":
            target = OUT / record["prediction"]
            assert sha(target) == record["prediction_sha256"]
            with gzip.open(target, "rt", encoding="utf-8") as handle:
                predictions[(record["id"], record["backend"])] = json.load(handle)
    scored = []
    for row in rows:
        included = row["include"] == "1"
        path = str((MANIFEST.parent / row["workbook"]).resolve())
        target_text = row.get("source_cells", "") or row.get("source_cell", "")
        for backend in ("v4", "v511"):
            ident = by_path.get(path)
            task = task_by_key.get((ident, backend))
            targets = {parse_cell_label(c.strip()) for c in target_text.split(";") if c.strip()} if included else set()
            raw = predictions.get((ident, backend))
            rank_by_cell = {tuple(r["cell"]): r["rank"] for r in raw["diagnosis"]["localization"]} if raw else {}
            target_ranks = sorted(rank_by_cell[c] for c in targets if c in rank_by_cell)
            formulas = {tuple(r[:2]): r[2] for r in raw["formulas"]} if raw else {}
            supported_targets = 0
            for cell in targets:
                if cell in formulas:
                    try:
                        parse_formula(formulas[cell])
                        supported_targets += 1
                    except FormulaSyntaxError:
                        pass
            scored.append({"event_id": row["instance_id"], "backend": backend,
                "preincluded": included, "preexclusion_reason": row["exclusion_reason"],
                "workbook": row["workbook"], "input_id": ident,
                "execution_status": task["status"] if task else "preexcluded",
                "labeled_cells": target_text, "labeled_cell_count": len(targets),
                "labeled_formula_cells_ranked": len(target_ranks), "supported_labeled_formula_cells": supported_targets,
                "first_labeled_rank": min(target_ranks) if target_ranks else None,
                "top1_hit": bool(target_ranks and min(target_ranks) <= 1),
                "top5_hit": bool(target_ranks and min(target_ranks) <= 5),
                "top10_hit": bool(target_ranks and min(target_ranks) <= 10),
                "labeled_cell_recall_at_10": sum(v <= 10 for v in target_ranks) / len(targets) if targets else None,
                "search_status": raw["diagnosis"]["search"]["status"] if raw else None,
                "accepted_cells_in_workbook": sum(d["accepted_formula"] is not None for d in raw["diagnosis"]["decisions"]) if raw else None,
                "formula_cells_in_workbook": raw["formula_cells"] if raw else None,
                "supported_formula_cells_in_workbook": raw["supported_formula_cells"] if raw else None,
                "diagnosis_seconds": raw["diagnosis_seconds"] if raw else None})
    write_csv(OUT / "EVENT_SCORES.csv", scored)
    summaries = {}
    for backend in ("v4", "v511"):
        eligible = [r for r in scored if r["backend"] == backend and r["preincluded"]]
        successful = [r for r in eligible if r["execution_status"] == "completed"]
        unique_raw = [p for (ident, b), p in predictions.items() if b == backend]
        summaries[backend] = {"original_events": 36, "eligible_events": len(eligible),
            "successfully_predicted_events": len(successful),
            "execution_statuses": dict(Counter(r["status"] for r in completed if r["backend"] == backend)),
            **{f"top{k}_hits": sum(r[f"top{k}_hit"] for r in eligible) for k in (1, 5, 10)},
            **{f"top{k}_rate_all_eligible": sum(r[f"top{k}_hit"] for r in eligible) / len(eligible) for k in (1, 5, 10)},
            **{f"top{k}_rate_successful_inputs": sum(r[f"top{k}_hit"] for r in successful) / len(successful) if successful else None for k in (1, 5, 10)},
            "search_statuses": dict(Counter(p["diagnosis"]["search"]["status"] for p in unique_raw)),
            "accepted_cells_across_unique_workbooks": sum(d["accepted_formula"] is not None for p in unique_raw for d in p["diagnosis"]["decisions"]),
            "repair_precision": None,
            "repair_precision_unavailable_reason": "correct formulas and exhaustive workbook-error truth are absent"}
    result = {"completed_at": now(), "model": "V5.1.9-development", "scope": "Enron historical revealed regression; no independent blind claim",
              "all_tasks_completed": all(r["status"] == "completed" for r in completed), "summaries": summaries}
    save(OUT / "RESULT.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["evaluate", "worker"])
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--backend", choices=["v4", "v511"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "worker":
        worker(args.workbook, args.backend, args.output)
    else:
        evaluate()
