"""Evaluate all available FormulaGuard families on the frozen SGV1 cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def key(cell) -> tuple[str, str]:
    return str(cell[0]), str(cell[1])


def formula_key(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(str(value).split()).upper()


def average_precision(ranking: list[tuple[str, str]], truth: set[tuple[str, str]]) -> float | None:
    if not truth:
        return None
    hits = 0
    total = 0.0
    for rank, cell in enumerate(ranking, 1):
        if cell in truth:
            hits += 1
            total += hits / rank
    return total / len(truth)


def ranking_record(
    method: str,
    case: dict,
    formula_cells: list[tuple[str, str]],
    ranking: list[tuple[str, str]],
    candidates: dict[tuple[str, str], str | None],
    truth: set[tuple[str, str]],
    expected: dict[tuple[str, str], str],
    *,
    native_review: list[tuple[str, str]] | None = None,
    diagnostic_state: str | None = None,
) -> dict:
    inventory = set(formula_cells)
    if len(ranking) != len(inventory) or set(ranking) != inventory or len(set(ranking)) != len(ranking):
        raise ValueError(f"incomplete or duplicate ranking for {method}")
    reviewed = native_review if native_review is not None else []
    review_hits = sum(cell in truth for cell in reviewed)
    exact_repairs = sum(
        cell in candidates
        and formula_key(candidates[cell]) == formula_key(expected[cell])
        for cell in truth
    )
    top = {str(k): sum(cell in truth for cell in ranking[:k]) for k in (1, 5, 10, 20)}
    return {
        "status": "ok",
        "method": method,
        "case_id": case["case_id"],
        "condition": case["condition"],
        "scenario": case["scenario"],
        "workbook": case["workbook"],
        "input_sha256": case["sha256"],
        "formula_cells": len(inventory),
        "errors": len(truth),
        "average_precision": average_precision(ranking, truth),
        "top_hits": top,
        "top_recall": {name: (hits / len(truth) if truth else None) for name, hits in top.items()},
        "exact_repairs": exact_repairs,
        "candidate_count": sum(value is not None for value in candidates.values()),
        "native_review_cells": len(reviewed),
        "native_review_hits": review_hits,
        "native_review_precision": review_hits / len(reviewed) if reviewed else None,
        "native_review_recall": review_hits / len(truth) if truth else None,
        "diagnostic_state": diagnostic_state,
    }


def load_model_outputs(
    case: dict,
    dataset: Path,
    structuralguard_code: Path | None,
    methods: set[str] | None = None,
):
    workbook = dataset / case["workbook"]
    from formulaguard.workbook import WorkbookModel

    model = WorkbookModel.from_xlsx(workbook)
    output = []
    def wanted(name: str) -> bool:
        return methods is None or name in methods

    def attempt(method, function, *, review=None, state=None):
        if not wanted(method):
            return
        try:
            result = function()
            output.append((method, model.formula_cells, result, None, review, state, None))
        except Exception as exc:  # Preserve method failures in the receipt.  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
            output.append((method, model.formula_cells, None, None, None, None, f"{type(exc).__name__}: {exc}"))

    from formulaguard.localize import v4_scores

    attempt("v4_r1", lambda: v4_scores(model))
    from formulaguard.v5_structural_guard import v5_structural_guard_scores

    attempt("v5_structural_guard", lambda: v5_structural_guard_scores(model))
    from formulaguard.v4x import v4_1_scores, v4_3_scores

    attempt("v4_1_pcg", lambda: v4_1_scores(model))
    for variant in "abc":
        attempt(f"v4_3_semantic_{variant}", lambda variant=variant: v4_3_scores(model, variant=variant))
    from formulaguard.v5_core import v5_core_scores

    for head in ("rule", "learned"):
        attempt(f"v5_core_{head}", lambda head=head: v5_core_scores(model, head=head))
    from formulaguard.v5_core_r2 import v5_core_r2_scores

    for stage in ("source", "placebo", "full"):
        attempt(f"v5_core_r2_{stage}", lambda stage=stage: v5_core_r2_scores(model, stage=stage))
    from formulaguard.v5_psl import diagnose_v5_psl

    if wanted("v5_psl_full"):
        try:
            diagnosis = diagnose_v5_psl(model)
            output.append(("v5_psl_full", model.formula_cells, list(diagnosis.ranking), None, diagnosis.review_cells, diagnosis.state.value, None))
        except Exception as exc:  # Preserve method failures in the receipt.  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
            output.append(("v5_psl_full", model.formula_cells, None, None, None, None, f"{type(exc).__name__}: {exc}"))
    if structuralguard_code is not None and wanted("structuralguard"):
        code = str(structuralguard_code.resolve())
        if code not in sys.path:
            sys.path.insert(0, code)
        from structuralguard import analyze_workbook

        report = analyze_workbook(workbook)
        ranking = [(str(row["sheet"]), str(row["cell"])) for row in report["results"]]
        candidates = {
            (str(row["sheet"]), str(row["cell"])): row.get("suggested_formula")
            for row in report["results"]
        }
        reviewed = [
            (str(row["sheet"]), str(row["cell"]))
            for row in report["results"]
            if str(row.get("status")) != "low_risk"
        ]
        output.append(("structuralguard", model.formula_cells, ranking, candidates, reviewed, report["summary"].get("status"), None))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--structuralguard-code", type=Path)
    parser.add_argument("--methods", nargs="*", help="run only these method names")
    parser.add_argument("--conditions", nargs="*", help="run only these benchmark conditions")
    parser.add_argument("--case-ids", nargs="*", help="run only these case ids")
    parser.add_argument("--output", type=Path, default=Path("results/structuralguard_standard_v1/evaluation.json"))
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    labels = json.loads((dataset / "labels" / "answer_keys.json").read_text(encoding="utf-8"))
    records: list[dict] = []
    selected_conditions = set(args.conditions) if args.conditions else None
    selected_case_ids = set(args.case_ids) if args.case_ids else None
    for case in labels["cases"]:
        if selected_conditions is not None and case["condition"] not in selected_conditions:
            continue
        if selected_case_ids is not None and case["case_id"] not in selected_case_ids:
            continue
        workbook = dataset / case["workbook"]
        if sha256(workbook) != case["sha256"]:
            raise SystemExit(f"workbook hash mismatch: {case['case_id']}")
        truth = {(str(item["sheet"]), str(item["cell"])) for item in case["errors"]}
        expected = {
            (str(item["sheet"]), str(item["cell"])): str(item["expected_formula"])
            for item in case["errors"]
        }
        try:
            outputs = load_model_outputs(case, dataset, args.structuralguard_code, set(args.methods) if args.methods else None)
        except Exception as exc:  # Preserve loader failures in the receipt.  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
            records.append({
                "status": "error",
                "method": "case_loader",
                "case_id": case["case_id"],
                "condition": case["condition"],
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        for method, inventory, results, candidates, native_review, diagnostic_state, method_error in outputs:
            if method_error is not None:
                records.append({
                    "status": "error",
                    "method": method,
                    "case_id": case["case_id"],
                    "condition": case["condition"],
                    "error": method_error,
                })
                continue
            try:
                if method == "structuralguard":
                    ranking = results
                else:
                    ranking = [getattr(result, "cell", result) for result in results]
                    candidates = {
                        key(getattr(result, "cell", result)): getattr(result, "candidate_formula", None)
                        for result in results
                    }
                records.append(ranking_record(
                    method, case, inventory, [key(cell) for cell in ranking], candidates,
                    truth, expected,
                    native_review=[key(cell) for cell in native_review] if native_review is not None else None,
                    diagnostic_state=diagnostic_state,
                ))
            except Exception as exc:  # Preserve adapter failures in the receipt.  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
                records.append({
                    "status": "error",
                    "method": method,
                    "case_id": case["case_id"],
                    "condition": case["condition"],
                    "error": f"{type(exc).__name__}: {exc}",
                })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    methods = sorted({str(record["method"]) for record in records})
    summaries = []
    for method in methods:
        rows = [record for record in records if record["method"] == method]
        ok = [record for record in rows if record["status"] == "ok"]
        by_condition = {}
        for condition in ("singleton", "clean", "coherent_block", "systematic_column"):
            selected = [record for record in ok if record["condition"] == condition]
            truth_count = sum(int(record["errors"]) for record in selected)
            top5 = sum(int(record["top_hits"]["5"]) for record in selected)
            native_cells = sum(int(record["native_review_cells"]) for record in selected)
            native_hits = sum(int(record["native_review_hits"]) for record in selected)
            aps = [float(record["average_precision"]) for record in selected if record["average_precision"] is not None]
            by_condition[condition] = {
                "cases": len(selected),
                "errors": truth_count,
                "macro_average_precision": statistics.fmean(aps) if aps else None,
                "top5_hits": top5,
                "top5_recall": top5 / truth_count if truth_count else None,
                "exact_repairs": sum(int(record["exact_repairs"]) for record in selected),
                "native_review_cells": native_cells,
                "native_review_hits": native_hits,
                "native_review_precision": native_hits / native_cells if native_cells else None,
                "native_review_recall": native_hits / truth_count if truth_count else None,
            }
        summaries.append({
            "method": method,
            "status": "ok" if len(ok) == len(rows) else "partial",
            "completed_cases": len(ok),
            "failed_cases": len(rows) - len(ok),
            "failures": [record.get("error") for record in rows if record["status"] != "ok"],
            "by_condition": by_condition,
        })
    result = {
        "protocol": "structuralguard_standard_benchmark_evaluation_v1",
        "dataset_protocol": labels["protocol"],
        "source_archive_sha256": labels["source_archive_sha256"],
        "input_scope": labels["input_scope"],
        "qct_source_commit": repository_commit(),
        "structuralguard_code": str(args.structuralguard_code.resolve()) if args.structuralguard_code else None,
        "requested_methods": args.methods,
        "methods": [summary["method"] for summary in summaries],
        "summaries": summaries,
        "cases": records,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0 if all(record["status"] == "ok" for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
