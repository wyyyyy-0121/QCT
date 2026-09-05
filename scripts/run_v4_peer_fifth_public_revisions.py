"""Predict then score peer-fifth on held-out public XLSX revisions."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_peer_fifth import (
    MODEL_VERSION,
    REVIEW_BUDGET,
    v4_peer_fifth_scores,
)
from formulaguard.v5_psl_protocol import (
    canonical_cell,
    combined_shards_sha256,
    safe_path,
    sha256,
)
from formulaguard.workbook import WorkbookModel

DATA_PROTOCOL = "formulaguard_public_xlsx_revision_evidence_v1"
PREDICTION_PROTOCOL = "v4_peer_fifth_public_revision_prediction_v1"
RUN_PROTOCOL = "v4_peer_fifth_public_revision_run_v1"
COMPLETION_PROTOCOL = "v4_peer_fifth_public_revision_completion_v1"
SCORE_PROTOCOL = "v4_peer_fifth_public_revision_score_v1"
MODEL_SOURCE_COMMIT = "d930e6376c5f08d294d17d27392d08f8f5666aab"
CASE_FIELDS = (
    "revision_case_id", "workbook_id", "repository", "commit_sha", "parent_sha",
    "committed_at", "commit_message", "workbook_path", "sheet_name", "cell_address",
    "before_formula", "after_formula", "license_spdx", "commit_url", "before_url",
    "after_url", "before_sha256", "after_sha256",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _manifest(data_root: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    path = data_root / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != DATA_PROTOCOL:
        raise ValueError("public revision manifest protocol differs")
    counts = payload.get("counts", {})
    workbooks = payload.get("workbooks")
    if not isinstance(workbooks, list) or len(workbooks) != 4:
        raise ValueError("public revision manifest requires four workbook pairs")
    if counts.get("workbook_pairs") != 4 or counts.get("formula_revision_cells") != 8:
        raise ValueError("public revision manifest counts differ")
    boundaries = payload.get("claim_boundaries", {})
    if (
        boundaries.get("public_version_revision_evidence") is not True
        or boundaries.get("formal_blind_test") is not False
        or boundaries.get("post_revision_semantic_correctness_independently_proven") is not False
    ):
        raise ValueError("public revision claim boundaries differ")
    ids = [str(row.get("workbook_id", "")) for row in workbooks]
    if not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("public revision workbook identifiers are invalid")
    return payload, sorted(workbooks, key=lambda row: str(row["workbook_id"]))


def _rank(ranking: Sequence[str], target: str) -> int | None:
    canonical_target = canonical_cell(target)
    for rank, cell in enumerate(ranking, start=1):
        if canonical_cell(cell) == canonical_target:
            return rank
    return None


def predict(data_root: Path, output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError("prediction output must be empty")
    manifest, workbooks = _manifest(data_root)
    if _git("merge-base", "--is-ancestor", MODEL_SOURCE_COMMIT, "HEAD") != "":
        raise ValueError("peer-fifth model source commit is not an ancestor of HEAD")
    (output / "shards").mkdir(parents=True, exist_ok=True)
    metadata = {
        "protocol": RUN_PROTOCOL,
        "model_version": MODEL_VERSION,
        "model_source_commit": MODEL_SOURCE_COMMIT,
        "model_source_sha256": sha256(ROOT / "formulaguard/v4_peer_fifth.py"),
        "manifest_sha256": sha256(data_root / "manifest.json"),
        "data_protocol": manifest["protocol"],
        "workbooks": len(workbooks),
        "label_inputs": [],
        "cases_csv_read": False,
    }
    metadata_path = output / "prediction_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    for row in workbooks:
        workbook_id = str(row["workbook_id"])
        before_file = str(row["before_file"])
        path = safe_path(data_root, before_file)
        if sha256(path) != row.get("before_sha256"):
            raise ValueError(f"before workbook hash differs: {workbook_id}")
        model = WorkbookModel.from_xlsx(path)
        candidate = v4_peer_fifth_scores(model)
        candidate_cells = [item.cell_label for item in candidate]
        v4_cells = [
            item.cell_label
            for item in sorted(candidate, key=lambda item: int(item.evidence["original_v4_rank"]))
        ]
        record = {
            "protocol": PREDICTION_PROTOCOL,
            "workbook_id": workbook_id,
            "before_file": before_file,
            "before_sha256": row["before_sha256"],
            "formula_count": len(model.formulas),
            "methods": {
                "v4_r1": {"ranking": v4_cells},
                "v4_peer_fifth": {"ranking": candidate_cells},
            },
            "ranking_changed": candidate_cells != v4_cells,
            "label_inputs": [],
            "cases_csv_read": False,
        }
        (output / "shards" / f"{workbook_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    shards = sorted((output / "shards").glob("*.json"))
    completion = {
        "protocol": COMPLETION_PROTOCOL,
        "complete": True,
        "workbooks": len(workbooks),
        "metadata_sha256": sha256(metadata_path),
        "combined_shards_sha256": combined_shards_sha256(shards),
        "label_inputs": [],
        "cases_csv_read": False,
        "score_authorized_after_git_commit": True,
    }
    completion_path = output / "prediction_complete.json"
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return completion_path


def _verify_predictions(data_root: Path, predictions: Path) -> dict[str, object]:
    _manifest_payload, workbooks = _manifest(data_root)
    metadata_path = predictions / "prediction_metadata.json"
    completion_path = predictions / "prediction_complete.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if (
        metadata.get("protocol") != RUN_PROTOCOL
        or metadata.get("model_source_commit") != MODEL_SOURCE_COMMIT
        or metadata.get("model_source_sha256") != sha256(ROOT / "formulaguard/v4_peer_fifth.py")
        or metadata.get("manifest_sha256") != sha256(data_root / "manifest.json")
        or metadata.get("label_inputs") != []
        or metadata.get("cases_csv_read") is not False
    ):
        raise ValueError("prediction metadata differs")
    expected_files = {
        "prediction_metadata.json", "prediction_complete.json",
        *(f"shards/{row['workbook_id']}.json" for row in workbooks),
    }
    observed = {
        path.relative_to(predictions).as_posix()
        for path in predictions.rglob("*") if path.is_file() or path.is_symlink()
    }
    if any(path.is_symlink() for path in predictions.rglob("*")) or observed != expected_files:
        raise ValueError("prediction file inventory differs")
    shards = sorted((predictions / "shards").glob("*.json"))
    if completion != {
        "protocol": COMPLETION_PROTOCOL,
        "complete": True,
        "workbooks": len(workbooks),
        "metadata_sha256": sha256(metadata_path),
        "combined_shards_sha256": combined_shards_sha256(shards),
        "label_inputs": [],
        "cases_csv_read": False,
        "score_authorized_after_git_commit": True,
    }:
        raise ValueError("prediction completion differs")
    for row in workbooks:
        path = predictions / "shards" / f"{row['workbook_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        formula_cells = {
            canonical_cell(f"{sheet}!{address}")
            for sheet, address in WorkbookModel.from_xlsx(
                safe_path(data_root, str(row["before_file"])),
            ).formula_cells
        }
        for method in ("v4_r1", "v4_peer_fifth"):
            ranking = record["methods"][method]["ranking"]
            observed = [canonical_cell(cell) for cell in ranking]
            if len(observed) != len(set(observed)) or set(observed) != formula_cells:
                raise ValueError(f"incomplete {method} ranking: {row['workbook_id']}")
        if record.get("label_inputs") != [] or record.get("cases_csv_read") is not False:
            raise ValueError("prediction shard crossed the label boundary")
    relative = completion_path.resolve().relative_to(ROOT)
    _git("cat-file", "-e", f"HEAD:{relative.as_posix()}")
    if subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", str(predictions)], cwd=ROOT,
        check=False,
    ).returncode:
        raise ValueError("public revision predictions are not committed")
    return completion


def summarize_rows(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_workbook: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        by_workbook[str(row["workbook_id"])].append(row)

    def macro(field: str) -> float:
        return statistics.fmean(
            statistics.fmean(float(row[field]) for row in group)
            for group in by_workbook.values()
        )

    v4_top5 = macro("v4_top5")
    candidate_top5 = macro("candidate_top5")
    v4_mrr = macro("v4_mrr")
    candidate_mrr = macro("candidate_mrr")
    recovered = sum(int(row["candidate_top5"]) > int(row["v4_top5"]) for row in rows)
    lost = sum(int(row["candidate_top5"]) < int(row["v4_top5"]) for row in rows)
    gates = {
        "top5_nonnegative": candidate_top5 >= v4_top5,
        "mrr_nonnegative": candidate_mrr >= v4_mrr,
        "no_v4_hit_lost": lost == 0,
        "at_least_one_v4_miss_recovered": recovered >= 1,
        "review_budget_equal_to_v4": True,
    }
    return {
        "revision_cells": len(rows),
        "workbooks": len(by_workbook),
        "v4_top5": v4_top5,
        "candidate_top5": candidate_top5,
        "top5_delta_pp": 100.0 * (candidate_top5 - v4_top5),
        "v4_mrr": v4_mrr,
        "candidate_mrr": candidate_mrr,
        "mrr_delta": candidate_mrr - v4_mrr,
        "recovered_events": recovered,
        "lost_events": lost,
        "gates": gates,
        "confirmation_passed": all(gates.values()),
    }


def score(data_root: Path, predictions: Path, output: Path) -> Path:
    if output.exists():
        raise ValueError("score output already exists")
    completion = _verify_predictions(data_root, predictions)
    with (data_root / "cases.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CASE_FIELDS:
            raise ValueError("public revision case schema differs")
        cases = list(reader)
    if len(cases) != 8:
        raise ValueError("public revision score requires eight formula changes")
    event_rows: list[dict[str, object]] = []
    for case in cases:
        record = json.loads(
            (predictions / "shards" / f"{case['workbook_id']}.json").read_text(encoding="utf-8")
        )
        target = canonical_cell(f"{case['sheet_name']}!{case['cell_address']}")
        v4_rank = _rank(record["methods"]["v4_r1"]["ranking"], target)
        candidate_rank = _rank(record["methods"]["v4_peer_fifth"]["ranking"], target)
        event_rows.append({
            "revision_case_id": case["revision_case_id"],
            "workbook_id": case["workbook_id"],
            "v4_rank": v4_rank,
            "candidate_rank": candidate_rank,
            "v4_top5": int(v4_rank is not None and v4_rank <= REVIEW_BUDGET),
            "candidate_top5": int(candidate_rank is not None and candidate_rank <= REVIEW_BUDGET),
            "v4_mrr": 1.0 / v4_rank if v4_rank else 0.0,
            "candidate_mrr": 1.0 / candidate_rank if candidate_rank else 0.0,
        })
    summary = summarize_rows(event_rows)
    payload = {
        "protocol": SCORE_PROTOCOL,
        "candidate_model_version": MODEL_VERSION,
        "model_source_commit": MODEL_SOURCE_COMMIT,
        "prediction_completion_sha256": sha256(predictions / "prediction_complete.json"),
        "prediction_combined_shards_sha256": completion["combined_shards_sha256"],
        "cases_sha256": sha256(data_root / "cases.csv"),
        "summary": summary,
        "events": event_rows,
        "label_boundary": {
            "predictions_committed_before_cases_read": True,
            "model_label_inputs": [],
        },
        "claim_scope": "held_out_public_version_revision_evidence",
        "formal_blind_test": False,
        "independent_semantic_correctness_proven": False,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    predict_parser = subparsers.add_parser("predict")
    predict_parser.add_argument("--data", type=Path, required=True)
    predict_parser.add_argument("--output", type=Path, required=True)
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("--data", type=Path, required=True)
    score_parser.add_argument("--predictions", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "predict":
            path = predict(args.data.resolve(), args.output.resolve())
        else:
            path = score(args.data.resolve(), args.predictions.resolve(), args.output.resolve())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"peer-fifth public revision {args.command} refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
