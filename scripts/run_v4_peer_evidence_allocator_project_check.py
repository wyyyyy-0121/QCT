"""Run a locked safety check on the project-generated saturated 240+120 corpus."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_peer_evidence_allocator import (
    ARCHITECTURE,
    MINIMUM_V4_PREFIX,
    MODEL_VERSION,
    REVIEW_BUDGET,
    v4_peer_evidence_allocator_scores,
)
from formulaguard.v5_psl_protocol import (
    CASE_FIELDS,
    DEFAULT_WORKERS,
    audit_design,
    canonical_cell,
    combined_shards_sha256,
    parse_source_cells,
    read_csv,
    safe_path,
    sha256,
    source_rank,
    validate_complete_ranking,
)
from formulaguard.workbook import WorkbookModel
from scripts.run_v4_static_fifth_blind import _bootstrap
from scripts.run_v4_static_fifth_project_blind import (
    _project_rows,
    _release_inventory,
    _release_summary,
)


CANDIDATE_PROTOCOL = "v4_peer_evidence_allocator_project_check_candidate_lock_v1"
PREDICTION_PROTOCOL = "v4_peer_evidence_allocator_project_prediction_v1"
RUN_PROTOCOL = "v4_peer_evidence_allocator_project_prediction_run_v1"
COMPLETION_PROTOCOL = "v4_peer_evidence_allocator_project_prediction_completion_v1"
LOCK_PROTOCOL = "v4_peer_evidence_allocator_project_prediction_lock_v1"
COMMITMENT_PROTOCOL = "v4_peer_evidence_allocator_project_git_commitment_v1"
SCORE_PROTOCOL = "v4_peer_evidence_allocator_project_score_v1"
METHODS = ("v4_r1", "evidence_allocator")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()


def verify_candidate_lock(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != CANDIDATE_PROTOCOL or payload.get("candidate_locked") is not True:
        raise ValueError("peer allocator candidate lock is absent or invalid")
    expected_model = {
        "model_version": MODEL_VERSION,
        "architecture": ARCHITECTURE,
        "review_budget": REVIEW_BUDGET,
        "minimum_v4_prefix": MINIMUM_V4_PREFIX,
    }
    if payload.get("model") != expected_model:
        raise ValueError("peer allocator candidate lock model differs")
    if (
        payload.get("formal_version") is not None
        or payload.get("protected_labels_read_before_lock") is not False
        or payload.get("post_lock_tuning_on_project_corpus_forbidden") is not True
        or payload.get("comparative_improvement_claim_allowed") is not False
    ):
        raise ValueError("peer allocator project-check boundary differs")
    sources = payload.get("source_sha256")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("candidate source inventory is empty")
    for relative, expected in sources.items():
        if sha256(safe_path(ROOT, str(relative))) != expected:
            raise ValueError(f"candidate source changed after lock: {relative}")
    receipt = safe_path(ROOT, str(payload["public_development_receipt"]))
    if sha256(receipt) != payload.get("public_development_receipt_sha256"):
        raise ValueError("public development receipt changed after candidate lock")
    if _git("merge-base", "--is-ancestor", str(payload["model_source_commit"]), "HEAD") != "":
        raise ValueError("candidate source commit is not an ancestor of HEAD")
    return payload


def _ranking(cells: Sequence[str]) -> list[dict[str, object]]:
    return [{"rank": rank, "cell": cell} for rank, cell in enumerate(cells, start=1)]


def predict_workbook(workbook: Path, instance_id: str, workbook_label: str) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(workbook)
    candidate = v4_peer_evidence_allocator_scores(model, candidate_limit=15)
    candidate_cells = [row.cell_label for row in candidate]
    v4_cells = [
        row.cell_label
        for row in sorted(candidate, key=lambda row: int(row.evidence["original_v4_rank"]))
    ]
    return {
        "protocol": PREDICTION_PROTOCOL,
        "instance_id": instance_id,
        "workbook": workbook_label,
        "workbook_sha256": sha256(workbook),
        "formula_count": len(model.formulas),
        "methods": {
            "v4_r1": {"model_version": "v4-dev-r1", "ranking": _ranking(v4_cells)},
            "evidence_allocator": {"model_version": MODEL_VERSION, "ranking": _ranking(candidate_cells)},
        },
        "changed": candidate_cells != v4_cells,
        "label_inputs": [],
        "protected_label_inputs": [],
    }


def audit_prediction_shard(
    path: Path,
    row: Mapping[str, str],
    raw_root: Path,
    *,
    recompute: bool,
) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("protocol") != PREDICTION_PROTOCOL
        or record.get("instance_id") != row["instance_id"]
        or record.get("workbook") != row["workbook"]
        or record.get("label_inputs") != []
        or record.get("protected_label_inputs") != []
    ):
        raise ValueError(f"prediction boundary failed: {path.name}")
    workbook = safe_path(raw_root, row["workbook"])
    if record.get("workbook_sha256") != sha256(workbook):
        raise ValueError(f"prediction workbook changed: {path.name}")
    model = WorkbookModel.from_xlsx(workbook)
    formula_cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
    if record.get("formula_count") != len(formula_cells):
        raise ValueError(f"prediction formula count differs: {path.name}")
    methods = record.get("methods")
    if not isinstance(methods, dict) or set(methods) != set(METHODS):
        raise ValueError(f"prediction methods differ: {path.name}")
    expected_versions = {"v4_r1": "v4-dev-r1", "evidence_allocator": MODEL_VERSION}
    for method, version in expected_versions.items():
        if methods[method].get("model_version") != version:
            raise ValueError(f"prediction model version differs: {method}")
        validate_complete_ranking(methods[method]["ranking"], formula_cells)
    v4_cells = [canonical_cell(item["cell"]) for item in methods["v4_r1"]["ranking"]]
    candidate_cells = [
        canonical_cell(item["cell"]) for item in methods["evidence_allocator"]["ranking"]
    ]
    if record.get("changed") is not (candidate_cells != v4_cells):
        raise ValueError(f"prediction changed flag differs: {path.name}")
    if recompute:
        expected = predict_workbook(workbook, row["instance_id"], row["workbook"])
        if record != expected:
            raise ValueError(f"prediction does not reproduce: {path.name}")
    return record


def _prediction_task(task: tuple[str, str, str, str]) -> str:
    raw_text, output_text, instance_id, workbook_label = task
    raw_root, output = Path(raw_text), Path(output_text)
    row = {"instance_id": instance_id, "workbook": workbook_label}
    shard = output / "shards" / f"{instance_id}.json"
    if shard.exists():
        audit_prediction_shard(shard, row, raw_root, recompute=False)
        return instance_id
    record = predict_workbook(safe_path(raw_root, workbook_label), instance_id, workbook_label)
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, shard)
    return instance_id


def _reproduction_task(task: tuple[str, str, str, str]) -> str:
    raw_text, shard_text, instance_id, workbook_label = task
    audit_prediction_shard(
        Path(shard_text),
        {"instance_id": instance_id, "workbook": workbook_label},
        Path(raw_text),
        recompute=True,
    )
    return instance_id


def predict_run(
    release_root: Path,
    candidate_lock_path: Path,
    output: Path,
    *,
    workers: int,
) -> Path:
    candidate = verify_candidate_lock(candidate_lock_path)
    entries = _release_inventory(release_root, verify_all=False)
    release = _release_summary(release_root, entries)
    rows = _project_rows(release_root, entries)
    allowed = {"shards", "prediction_metadata.json", "prediction_complete.json"}
    if output.exists() and {path.name for path in output.iterdir()} - allowed:
        raise ValueError("prediction output contains unexpected files")
    (output / "shards").mkdir(parents=True, exist_ok=True)
    metadata = {
        "protocol": RUN_PROTOCOL,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "release_protocol": release["protocol"],
        "release_inventory_sha256": sha256(release_root / "SHA256SUMS.txt"),
        "release_summary_sha256": entries["RELEASE_SUMMARY.json"],
        "cases_sha256_commitment": entries["raw_360/cases.csv"],
        "instances": len(rows),
        "methods": list(METHODS),
        "workers": workers,
        "dataset_origin": "project_generated",
        "labels_parsed": [],
    }
    metadata_path = output / "prediction_metadata.json"
    encoded = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
    if metadata_path.exists() and metadata_path.read_bytes() != encoded:
        raise ValueError("prediction metadata differs")
    metadata_path.write_bytes(encoded)
    tasks = [
        (str(release_root / "raw_360"), str(output), row["instance_id"], row["workbook"])
        for row in rows
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        futures = [executor.submit(_prediction_task, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            future.result()
            if index % 25 == 0 or index == len(tasks):
                print(f"peer allocator project predictions {index}/{len(tasks)}", flush=True)
    rows_by_id = {row["instance_id"]: row for row in rows}
    shards = sorted((output / "shards").glob("*.json"))
    if len(shards) != len(rows) or {path.stem for path in shards} != set(rows_by_id):
        raise ValueError("prediction shards do not cover the release")
    for path in shards:
        audit_prediction_shard(
            path, rows_by_id[path.stem], release_root / "raw_360", recompute=False,
        )
    completion = {
        "protocol": COMPLETION_PROTOCOL,
        "complete": True,
        "instances": len(rows),
        "methods": list(METHODS),
        "metadata_sha256": sha256(metadata_path),
        "combined_shards_sha256": combined_shards_sha256(shards),
        "full_ranking_audit_passed": True,
        "labels_parsed": [],
    }
    completion_path = output / "prediction_complete.json"
    encoded = (json.dumps(completion, ensure_ascii=False, indent=2) + "\n").encode()
    if completion_path.exists() and completion_path.read_bytes() != encoded:
        raise ValueError("prediction completion differs")
    completion_path.write_bytes(encoded)
    return completion_path


def verify_prediction_run(
    release_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    *,
    recompute: bool,
    workers: int,
) -> dict[str, object]:
    candidate = verify_candidate_lock(candidate_lock_path)
    entries = _release_inventory(release_root, verify_all=False)
    release = _release_summary(release_root, entries)
    rows = _project_rows(release_root, entries)
    metadata_path = predictions / "prediction_metadata.json"
    completion_path = predictions / "prediction_complete.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    required = {
        "protocol": RUN_PROTOCOL,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "release_protocol": release["protocol"],
        "release_inventory_sha256": sha256(release_root / "SHA256SUMS.txt"),
        "release_summary_sha256": entries["RELEASE_SUMMARY.json"],
        "cases_sha256_commitment": entries["raw_360/cases.csv"],
        "instances": len(rows),
        "methods": list(METHODS),
        "dataset_origin": "project_generated",
        "labels_parsed": [],
    }
    for field, expected in required.items():
        if metadata.get(field) != expected:
            raise ValueError(f"prediction metadata differs: {field}")
    expected_files = {
        "prediction_metadata.json", "prediction_complete.json",
        *(f"shards/{row['instance_id']}.json" for row in rows),
    }
    observed = {
        path.relative_to(predictions).as_posix()
        for path in predictions.rglob("*") if path.is_file() or path.is_symlink()
    }
    if any(path.is_symlink() for path in predictions.rglob("*")) or observed != expected_files:
        raise ValueError("prediction file inventory differs")
    rows_by_id = {row["instance_id"]: row for row in rows}
    shards = sorted((predictions / "shards").glob("*.json"))
    if recompute:
        tasks = [
            (
                str(release_root / "raw_360"), str(path), path.stem,
                rows_by_id[path.stem]["workbook"],
            )
            for path in shards
        ]

        with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
            futures = [executor.submit(_reproduction_task, task) for task in tasks]
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                future.result()
                if index % 25 == 0 or index == len(tasks):
                    print(f"peer allocator project reproduction {index}/{len(tasks)}", flush=True)
    else:
        for path in shards:
            audit_prediction_shard(
                path, rows_by_id[path.stem], release_root / "raw_360", recompute=False,
            )
    combined = combined_shards_sha256(shards)
    expected_completion = {
        "protocol": COMPLETION_PROTOCOL,
        "complete": True,
        "instances": len(rows),
        "methods": list(METHODS),
        "metadata_sha256": sha256(metadata_path),
        "combined_shards_sha256": combined,
        "full_ranking_audit_passed": True,
        "labels_parsed": [],
    }
    if completion != expected_completion:
        raise ValueError("prediction completion differs")
    return {
        "protocol": LOCK_PROTOCOL,
        "locked": True,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "instances": len(rows),
        "methods": list(METHODS),
        "release_inventory_sha256": required["release_inventory_sha256"],
        "cases_sha256_commitment": required["cases_sha256_commitment"],
        "prediction_metadata_sha256": sha256(metadata_path),
        "prediction_completion_sha256": sha256(completion_path),
        "combined_shards_sha256": combined,
        "full_ranking_reproduction_passed": recompute,
        "labels_parsed": [],
        "post_lock_prediction_changes_forbidden": True,
    }


def write_prediction_lock(
    release_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    output: Path,
    *,
    workers: int,
) -> Path:
    if output.exists():
        raise ValueError("prediction lock already exists")
    payload = verify_prediction_run(
        release_root, candidate_lock_path, predictions, recompute=True, workers=workers,
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _verify_git_commitment(
    path: Path,
    prediction_lock_path: Path,
    lock: Mapping[str, object],
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "protocol": COMMITMENT_PROTOCOL,
        "candidate_id": lock["candidate_id"],
        "prediction_lock_sha256": sha256(prediction_lock_path),
        "combined_shards_sha256": lock["combined_shards_sha256"],
        "release_inventory_sha256": lock["release_inventory_sha256"],
        "cases_sha256_commitment": lock["cases_sha256_commitment"],
        "labels_parsed_before_commitment": [],
        "post_commitment_tuning_forbidden": True,
    }
    if payload != expected:
        raise ValueError("Git prediction commitment differs")
    relative = path.resolve().relative_to(ROOT)
    _git("cat-file", "-e", f"HEAD:{relative.as_posix()}")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(relative)], cwd=ROOT).returncode:
        raise ValueError("Git prediction commitment has uncommitted changes")


def _template_macro(rows: Sequence[Mapping[str, object]], field: str) -> float:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["template_id"])].append(float(row[field]))
    return statistics.fmean(statistics.fmean(values) for values in groups.values())


def score_rows(
    cases: Sequence[Mapping[str, str]],
    predictions: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    controls = controls_changed = 0
    for case in cases:
        record = json.loads(
            (predictions / "shards" / f"{case['instance_id']}.json").read_text(encoding="utf-8")
        )
        if case["case_kind"] == "control":
            controls += 1
            controls_changed += int(bool(record["changed"]))
            continue
        sources = set(parse_source_cells(case["source_cells"]))
        v4_rank = source_rank(record["methods"]["v4_r1"]["ranking"], sources)
        candidate_rank = source_rank(
            record["methods"]["evidence_allocator"]["ranking"], sources,
        )
        rows.append({
            "instance_id": case["instance_id"],
            "template_id": case["template_id"],
            "error_type": case["error_type"],
            "v4_rank": v4_rank if v4_rank is not None else "",
            "candidate_rank": candidate_rank if candidate_rank is not None else "",
            "v4_top5": int(v4_rank is not None and v4_rank <= REVIEW_BUDGET),
            "candidate_top5": int(candidate_rank is not None and candidate_rank <= REVIEW_BUDGET),
            "v4_mrr": 1.0 / v4_rank if v4_rank else 0.0,
            "candidate_mrr": 1.0 / candidate_rank if candidate_rank else 0.0,
        })
    v4_top5 = _template_macro(rows, "v4_top5")
    candidate_top5 = _template_macro(rows, "candidate_top5")
    v4_mrr = _template_macro(rows, "v4_mrr")
    candidate_mrr = _template_macro(rows, "candidate_mrr")
    recovered = sum(int(row["candidate_top5"]) > int(row["v4_top5"]) for row in rows)
    lost = sum(int(row["candidate_top5"]) < int(row["v4_top5"]) for row in rows)
    by_error_type = {}
    for error_type in sorted({str(row["error_type"]) for row in rows}):
        selected = [row for row in rows if row["error_type"] == error_type]
        before = statistics.fmean(float(row["v4_top5"]) for row in selected)
        after = statistics.fmean(float(row["candidate_top5"]) for row in selected)
        by_error_type[error_type] = {
            "cases": len(selected),
            "v4_top5": before,
            "candidate_top5": after,
            "delta_pp": 100.0 * (after - before),
        }
    bootstrap = _bootstrap(rows)
    safety_gates = {
        "v4_baseline_saturated": v4_top5 == 1.0,
        "all_v4_top5_hits_retained": lost == 0,
        "candidate_top5_not_below_v4": candidate_top5 >= v4_top5,
        "mrr_nonnegative": candidate_mrr >= v4_mrr,
        "every_error_type_nonnegative": all(
            row["delta_pp"] >= 0.0 for row in by_error_type.values()
        ),
        "review_budget_equal_to_v4": True,
    }
    return {
        "error_cases": len(rows),
        "control_cases": controls,
        "review_budget_per_workbook": REVIEW_BUDGET,
        "v4_top5": v4_top5,
        "candidate_top5": candidate_top5,
        "top5_delta_pp": 100.0 * (candidate_top5 - v4_top5),
        "v4_mrr": v4_mrr,
        "candidate_mrr": candidate_mrr,
        "mrr_delta": candidate_mrr - v4_mrr,
        "recovered_events": recovered,
        "lost_events": lost,
        "control_changed_ranking_rate_diagnostic": controls_changed / max(1, controls),
        "by_error_type": by_error_type,
        "template_cluster_bootstrap": bootstrap,
        "safety_gates": safety_gates,
        "safety_check_passed": all(safety_gates.values()),
        "comparative_improvement_established": False,
    }, rows


def score_once(
    release_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    prediction_lock_path: Path,
    git_commitment_path: Path,
    output: Path,
    *,
    workers: int,
) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError("score output is not empty")
    verify_candidate_lock(candidate_lock_path)
    external_lock = json.loads(prediction_lock_path.read_text(encoding="utf-8"))
    verified = verify_prediction_run(
        release_root, candidate_lock_path, predictions, recompute=False, workers=workers,
    )
    verified["full_ranking_reproduction_passed"] = True
    if external_lock != verified or external_lock.get("protocol") != LOCK_PROTOCOL:
        raise ValueError("external prediction lock does not reproduce")
    _verify_git_commitment(git_commitment_path, prediction_lock_path, external_lock)
    entries = _release_inventory(release_root, verify_all=True)
    if sha256(release_root / "SHA256SUMS.txt") != external_lock["release_inventory_sha256"]:
        raise ValueError("release inventory differs from prediction lock")
    output.mkdir(parents=True, exist_ok=True)
    start = {
        "protocol": "v4_peer_evidence_allocator_project_scoring_started_v1",
        "prediction_lock_sha256": sha256(prediction_lock_path),
        "git_commitment_sha256": sha256(git_commitment_path),
        "prediction_lock_verified_before_labels_parsed": True,
        "post_result_tuning_forbidden": True,
    }
    (output / "scoring_started.json").write_text(
        json.dumps(start, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    raw_root = release_root / "raw_360"
    cases = read_csv(raw_root / "cases.csv", exact_fields=CASE_FIELDS)
    declaration = json.loads((raw_root / "third_party_declaration.json").read_text(encoding="utf-8"))
    design = audit_design(cases, declaration, declaration_profile="project_generated")
    released = _project_rows(release_root, entries)
    id_by_workbook = {row["workbook"]: row["instance_id"] for row in released}
    transformed = [{**case, "instance_id": id_by_workbook[case["workbook"]]} for case in cases]
    summary, event_rows = score_rows(transformed, predictions)
    private_events = output / "private_events.csv"
    with private_events.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(event_rows[0]))
        writer.writeheader()
        writer.writerows(event_rows)
    result = {
        "protocol": SCORE_PROTOCOL,
        "design": design,
        "summary": summary,
        "prediction_lock_sha256": sha256(prediction_lock_path),
        "labels_parsed_only_after_committed_prediction_lock": True,
        "dataset_origin": "project_generated",
        "dataset_saturated_for_v4_top5": summary["v4_top5"] == 1.0,
        "formal_external_validation_claimed": False,
        "formal_model_name_authorized": None,
        "post_result_tuning_on_this_corpus_forbidden": True,
    }
    result_path = output / "summary.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "receipt.json").write_text(json.dumps({
        "protocol": "v4_peer_evidence_allocator_project_score_receipt_v1",
        "summary_sha256": sha256(result_path),
        "private_events_sha256": sha256(private_events),
        "safety_check_passed": summary["safety_check_passed"],
        "claim_scope": "project_generated_saturated_safety_check",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    predict_parser = subparsers.add_parser("predict")
    predict_parser.add_argument("--release", type=Path, required=True)
    predict_parser.add_argument("--candidate-lock", type=Path, required=True)
    predict_parser.add_argument("--output", type=Path, required=True)
    predict_parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    lock_parser = subparsers.add_parser("lock")
    lock_parser.add_argument("--release", type=Path, required=True)
    lock_parser.add_argument("--candidate-lock", type=Path, required=True)
    lock_parser.add_argument("--predictions", type=Path, required=True)
    lock_parser.add_argument("--output", type=Path, required=True)
    lock_parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("--release", type=Path, required=True)
    score_parser.add_argument("--candidate-lock", type=Path, required=True)
    score_parser.add_argument("--predictions", type=Path, required=True)
    score_parser.add_argument("--prediction-lock", type=Path, required=True)
    score_parser.add_argument("--git-commitment", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)
    score_parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args(argv)
    if getattr(args, "workers", 1) < 1:
        raise SystemExit("workers must be positive")
    try:
        if args.command == "predict":
            path = predict_run(
                args.release.resolve(), args.candidate_lock.resolve(), args.output.resolve(),
                workers=args.workers,
            )
        elif args.command == "lock":
            path = write_prediction_lock(
                args.release.resolve(), args.candidate_lock.resolve(),
                args.predictions.resolve(), args.output.resolve(), workers=args.workers,
            )
        else:
            path = score_once(
                args.release.resolve(), args.candidate_lock.resolve(),
                args.predictions.resolve(), args.prediction_lock.resolve(),
                args.git_commitment.resolve(), args.output.resolve(), workers=args.workers,
            )
    except (OSError, ValueError, KeyError, AssertionError, json.JSONDecodeError) as exc:
        raise SystemExit(f"peer allocator project {args.command} refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
