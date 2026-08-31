"""Blindly confirm static-fifth on the project-generated 240+120 corpus.

This receiver keeps the project-generated corpus distinct from an independent
third-party evaluation.  Prediction and lock phases never parse cases.csv;
the score phase refuses to parse it until a committed prediction lock exists.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl_protocol import (
    CASE_FIELDS,
    DEFAULT_WORKERS,
    audit_design,
    combined_shards_sha256,
    read_csv,
    safe_path,
    sha256,
)
from scripts.build_v5_psl_third_party_pack import validate_case_pair
from scripts.run_v4_static_fifth_blind import (
    METHODS,
    _development_signatures,
    _write_private_events,
    audit_prediction_shard,
    predict_workbook,
    score_rows,
    verify_candidate_lock,
)


RUN_PROTOCOL = "v4_static_fifth_project_blind_prediction_run_v1"
COMPLETION_PROTOCOL = "v4_static_fifth_project_blind_prediction_completion_v1"
LOCK_PROTOCOL = "v4_static_fifth_project_blind_prediction_lock_v1"
COMMITMENT_PROTOCOL = "v4_static_fifth_project_blind_git_commitment_v1"
SCORE_PROTOCOL = "v4_static_fifth_project_blind_score_v1"
RELEASE_PROTOCOL = "formulaguard_project_generated_240_120_release_v1"
EXPECTED_CASES = 360


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


def _release_inventory(
    release_root: Path,
    *,
    verify_all: bool,
) -> dict[str, str]:
    inventory_path = release_root / "SHA256SUMS.txt"
    entries: dict[str, str] = {}
    for line_number, line in enumerate(
        inventory_path.read_text(encoding="utf-8").splitlines(), start=1,
    ):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"malformed release inventory line {line_number}")
        digest, relative = parts[0].lower(), parts[1].strip()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"invalid release digest at line {line_number}")
        if relative in entries:
            raise ValueError(f"duplicate release path: {relative}")
        path = safe_path(release_root, relative)
        if (verify_all or relative.startswith("raw_360/workbooks/")) and sha256(path) != digest:
            raise ValueError(f"release file changed: {relative}")
        entries[relative] = digest
    required = {
        "RELEASE_SUMMARY.json",
        "raw_360/cases.csv",
        "raw_360/third_party_declaration.json",
    }
    if not required <= set(entries):
        raise ValueError(f"release inventory lacks required paths: {sorted(required - set(entries))}")
    return entries


def _release_summary(release_root: Path, entries: Mapping[str, str]) -> dict[str, object]:
    path = release_root / "RELEASE_SUMMARY.json"
    if sha256(path) != entries["RELEASE_SUMMARY.json"]:
        raise ValueError("release summary changed after finalization")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "protocol": RELEASE_PROTOCOL,
        "dataset_validation_passed": True,
        "templates": 30,
        "cases": 360,
        "errors": 240,
        "controls": 120,
        "dataset_origin": "project_generated",
        "formal_external_validation_claimed": False,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"release summary field differs: {field}")
    return payload


def _project_rows(release_root: Path, entries: Mapping[str, str]) -> list[dict[str, str]]:
    raw_root = release_root / "raw_360"
    workbook_entries = {
        relative.removeprefix("raw_360/"): digest
        for relative, digest in entries.items()
        if relative.startswith("raw_360/workbooks/") and relative.endswith(".xlsx")
    }
    if len(workbook_entries) != EXPECTED_CASES:
        raise ValueError(f"expected 360 released workbooks, found {len(workbook_entries)}")
    rows = [
        {
            "instance_id": "qct_" + digest[:24],
            "workbook": relative,
        }
        for relative, digest in sorted(workbook_entries.items())
    ]
    if len({row["instance_id"] for row in rows}) != len(rows):
        raise ValueError("opaque workbook identifier collision")
    for row in rows:
        if sha256(safe_path(raw_root, row["workbook"])) != workbook_entries[row["workbook"]]:
            raise ValueError(f"released workbook changed: {row['workbook']}")
    return sorted(rows, key=lambda row: row["instance_id"])


def _prediction_task(task: tuple[str, str, str, str]) -> str:
    raw_text, output_text, instance_id, workbook_label = task
    raw_root, output = Path(raw_text), Path(output_text)
    row = {"instance_id": instance_id, "workbook": workbook_label}
    shard = output / "shards" / f"{instance_id}.json"
    if shard.exists():
        audit_prediction_shard(shard, row, raw_root, recompute=False)
        return instance_id
    record = predict_workbook(
        safe_path(raw_root, workbook_label), instance_id, workbook_label,
    )
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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
        raise ValueError("prediction output contains unexpected pre-existing files")
    (output / "shards").mkdir(parents=True, exist_ok=True)
    metadata = {
        "protocol": RUN_PROTOCOL,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "release_protocol": release["protocol"],
        "release_inventory_sha256": sha256(release_root / "SHA256SUMS.txt"),
        "release_summary_sha256": entries["RELEASE_SUMMARY.json"],
        "cases_sha256_commitment": entries["raw_360/cases.csv"],
        "declaration_sha256_commitment": entries["raw_360/third_party_declaration.json"],
        "instances": len(rows),
        "methods": list(METHODS),
        "workers": workers,
        "dataset_origin": "project_generated",
        "formal_external_validation_claimed": False,
        "labels_parsed": [],
    }
    metadata_path = output / "prediction_metadata.json"
    encoded = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
    if metadata_path.exists() and metadata_path.read_bytes() != encoded:
        raise ValueError("prediction metadata differs from the existing run")
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
                print(f"project blind predictions {index}/{len(tasks)}", flush=True)
    rows_by_id = {row["instance_id"]: row for row in rows}
    shards = sorted((output / "shards").glob("*.json"))
    if len(shards) != len(rows) or {path.stem for path in shards} != set(rows_by_id):
        raise ValueError("prediction shards do not cover released workbooks exactly")
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
        raise ValueError("prediction completion differs from the existing run")
    completion_path.write_bytes(encoded)
    return completion_path


def verify_prediction_run(
    release_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    *,
    recompute: bool,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, object]:
    candidate = verify_candidate_lock(candidate_lock_path)
    entries = _release_inventory(release_root, verify_all=False)
    release = _release_summary(release_root, entries)
    rows = _project_rows(release_root, entries)
    metadata_path = predictions / "prediction_metadata.json"
    completion_path = predictions / "prediction_complete.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    required_metadata = {
        "protocol": RUN_PROTOCOL,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "release_protocol": release["protocol"],
        "release_inventory_sha256": sha256(release_root / "SHA256SUMS.txt"),
        "release_summary_sha256": entries["RELEASE_SUMMARY.json"],
        "cases_sha256_commitment": entries["raw_360/cases.csv"],
        "declaration_sha256_commitment": entries["raw_360/third_party_declaration.json"],
        "instances": len(rows),
        "methods": list(METHODS),
        "dataset_origin": "project_generated",
        "formal_external_validation_claimed": False,
        "labels_parsed": [],
    }
    for field, expected in required_metadata.items():
        if metadata.get(field) != expected:
            raise ValueError(f"prediction metadata changed: {field}")
    expected_files = {
        "prediction_metadata.json",
        "prediction_complete.json",
        *(f"shards/{row['instance_id']}.json" for row in rows),
    }
    observed_files = {
        path.relative_to(predictions).as_posix()
        for path in predictions.rglob("*") if path.is_file() or path.is_symlink()
    }
    if any(path.is_symlink() for path in predictions.rglob("*")) or observed_files != expected_files:
        raise ValueError("prediction file inventory differs")
    rows_by_id = {row["instance_id"]: row for row in rows}
    shards = sorted((predictions / "shards").glob("*.json"))
    if recompute:
        tasks = [
            (
                str(release_root / "raw_360"),
                str(path),
                path.stem,
                rows_by_id[path.stem]["workbook"],
            )
            for path in shards
        ]
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(workers, len(tasks)),
        ) as executor:
            futures = [executor.submit(_reproduction_task, task) for task in tasks]
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                future.result()
                if index % 25 == 0 or index == len(tasks):
                    print(f"project blind lock reproduction {index}/{len(tasks)}", flush=True)
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
        raise ValueError("prediction completion receipt differs")
    return {
        "protocol": LOCK_PROTOCOL,
        "locked": True,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "instances": len(rows),
        "methods": list(METHODS),
        "release_inventory_sha256": required_metadata["release_inventory_sha256"],
        "release_summary_sha256": required_metadata["release_summary_sha256"],
        "cases_sha256_commitment": required_metadata["cases_sha256_commitment"],
        "declaration_sha256_commitment": required_metadata["declaration_sha256_commitment"],
        "prediction_metadata_sha256": sha256(metadata_path),
        "prediction_completion_sha256": sha256(completion_path),
        "combined_shards_sha256": combined,
        "full_ranking_reproduction_passed": recompute,
        "labels_parsed": [],
        "dataset_origin": "project_generated",
        "formal_external_validation_claimed": False,
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
    prediction_lock: Mapping[str, object],
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "protocol": COMMITMENT_PROTOCOL,
        "candidate_id": prediction_lock["candidate_id"],
        "prediction_lock_sha256": sha256(prediction_lock_path),
        "combined_shards_sha256": prediction_lock["combined_shards_sha256"],
        "release_inventory_sha256": prediction_lock["release_inventory_sha256"],
        "cases_sha256_commitment": prediction_lock["cases_sha256_commitment"],
        "labels_parsed_before_commitment": [],
        "post_commitment_tuning_forbidden": True,
    }
    if payload != expected:
        raise ValueError("Git prediction commitment differs from the external lock")
    relative = path.resolve().relative_to(ROOT)
    _git("cat-file", "-e", f"HEAD:{relative.as_posix()}")
    if subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", str(relative)], cwd=ROOT,
    ).returncode:
        raise ValueError("Git prediction commitment has uncommitted changes")


def _validate_case_task(
    task: tuple[dict[str, str], str, tuple[str, ...]],
) -> tuple[str, dict[str, object]]:
    row, raw_text, signatures = task
    evidence = validate_case_pair(
        row, Path(raw_text), development_signatures=set(signatures),
    )
    return row["instance_id"], evidence


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
        raise ValueError("one-time score output is not empty")
    candidate = verify_candidate_lock(candidate_lock_path)
    external_lock = json.loads(prediction_lock_path.read_text(encoding="utf-8"))
    verified_lock = verify_prediction_run(
        release_root, candidate_lock_path, predictions, recompute=False,
    )
    if external_lock != verified_lock or external_lock.get("protocol") != LOCK_PROTOCOL:
        raise ValueError("external prediction lock does not reproduce")
    _verify_git_commitment(git_commitment_path, prediction_lock_path, external_lock)
    entries = _release_inventory(release_root, verify_all=True)
    if sha256(release_root / "SHA256SUMS.txt") != external_lock["release_inventory_sha256"]:
        raise ValueError("release inventory differs from the prediction lock")

    output.mkdir(parents=True, exist_ok=True)
    start_path = output / "scoring_started.json"
    start = {
        "protocol": "v4_static_fifth_project_blind_scoring_started_v1",
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "prediction_lock_sha256": sha256(prediction_lock_path),
        "git_commitment_sha256": sha256(git_commitment_path),
        "release_inventory_sha256": external_lock["release_inventory_sha256"],
        "prediction_lock_verified_before_labels_parsed": True,
        "post_result_tuning_on_this_corpus_forbidden": True,
    }
    with start_path.open("x", encoding="utf-8") as handle:
        json.dump(start, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    try:
        raw_root = release_root / "raw_360"
        cases = read_csv(raw_root / "cases.csv", exact_fields=CASE_FIELDS)
        declaration = json.loads(
            (raw_root / "third_party_declaration.json").read_text(encoding="utf-8")
        )
        design = audit_design(
            cases, declaration, declaration_profile="project_generated",
        )
        release = _release_summary(release_root, entries)
        if design["counts"]["total"] != release["cases"]:
            raise ValueError("design audit differs from the frozen release summary")

        released_rows = _project_rows(release_root, entries)
        id_by_workbook = {row["workbook"]: row["instance_id"] for row in released_rows}
        transformed_cases: list[dict[str, str]] = []
        for case in cases:
            if case["workbook"] not in id_by_workbook:
                raise ValueError("case ledger references an unreleased workbook")
            transformed_cases.append({
                **case,
                "instance_id": id_by_workbook[case["workbook"]],
            })
        if {row["instance_id"] for row in transformed_cases} != set(id_by_workbook.values()):
            raise ValueError("case ledger does not cover released workbooks exactly")

        signatures = tuple(sorted(_development_signatures(candidate)))
        tasks = [
            (dict(case), str(raw_root), signatures)
            for case in cases
        ]
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(workers, len(tasks)),
        ) as executor:
            futures = [executor.submit(_validate_case_task, task) for task in tasks]
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                future.result()
                if index % 50 == 0 or index == len(tasks):
                    print(f"project blind secret audit {index}/{len(tasks)}", flush=True)

        summary, event_rows = score_rows(transformed_cases, predictions)
        _write_private_events(output / "blind_events.csv", event_rows)
        result = {
            "protocol": SCORE_PROTOCOL,
            "candidate_id": candidate["candidate_id"],
            "design": design,
            "summary": summary,
            "candidate_lock_sha256": sha256(candidate_lock_path),
            "prediction_lock_sha256": sha256(prediction_lock_path),
            "release_inventory_sha256": external_lock["release_inventory_sha256"],
            "labels_parsed_only_after_committed_prediction_lock": True,
            "all_360_cases_retained": len(cases) == EXPECTED_CASES,
            "dataset_origin": "project_generated",
            "formal_external_validation_claimed": False,
            "formal_model_name_authorized": None,
            "main_candidate_confirmation_supported": summary["promotion_allowed"],
            "post_result_tuning_on_this_corpus_forbidden": True,
        }
        result_path = output / "blind_summary.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        receipt = {
            "protocol": "v4_static_fifth_project_blind_score_receipt_v1",
            "summary_sha256": sha256(result_path),
            "private_events_sha256": sha256(output / "blind_events.csv"),
            "all_frozen_gates_passed": summary["promotion_allowed"],
            "claim_scope": "project_generated_blind_confirmation",
        }
        (output / "score_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        return result_path
    except Exception as exc:
        failure = {
            "protocol": "v4_static_fifth_project_blind_scoring_failure_v1",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "rerun_without_review_forbidden": True,
        }
        (output / "scoring_failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        raise


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
        raise SystemExit(f"static-fifth project blind {args.command} refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
