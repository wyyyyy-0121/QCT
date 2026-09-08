"""Evaluate V5.1-development on a disclosed development release only."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import zipfile
from pathlib import Path

from score_structural_guard_fresh_blind import score_case, summarize

from formulaguard.v5_1_development import (
    MODEL_VERSION,
    v5_1_development_default_parameters,
    v5_1_development_scores,
)
from formulaguard.workbook import WorkbookModel


def evaluate_one(task: tuple[dict[str, str], str, dict]) -> dict:
    row, workbook, label = task
    model = WorkbookModel.from_xlsx(Path(workbook))
    original = dict(model.formulas)
    results = v5_1_development_scores(model)
    if model.formulas != original:
        raise ValueError(f"V5.1 mutated workbook: {row['case_id']}")
    ranking = [
        {
            "rank": rank,
            "sheet": result.cell[0],
            "cell": result.cell[1],
            "score": result.score,
            "candidate_formula": result.candidate_formula,
            "evidence": dict(result.evidence),
        }
        for rank, result in enumerate(results, 1)
    ]
    shard = {
        "protocol": "structural_guard_fresh_blind_prediction_shard_v1_1",
        "model": MODEL_VERSION,
        "model_version": MODEL_VERSION,
        "case_id": row["case_id"],
        "cluster_id": row["cluster_id"],
        "workbook_sha256": row["workbook_sha256"],
        "formula_count": len(ranking),
        "candidate_count": sum(
            item["candidate_formula"] is not None for item in ranking
        ),
        "accepted_group_count": sum(
            item["evidence"].get("group_state") == "accepted" for item in ranking
        ),
        "ranking": ranking,
    }
    return score_case(shard, label)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    receipt = json.loads((args.release / "release_receipt.json").read_text())
    with zipfile.ZipFile(args.release / receipt["secret_archive"]) as archive:
        labels = json.loads(archive.read("SECRET/labels.json"))["cases"]
    labels_by_id = {label["case_id"]: label for label in labels}
    with (args.release / "PUBLIC" / "manifest.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    tasks = [
        (
            row,
            str((args.release / "PUBLIC" / row["workbook_path"]).resolve()),
            labels_by_id[row["case_id"]],
        )
        for row in rows
    ]
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(args.workers, len(tasks))
    ) as pool:
        case_scores = list(pool.map(evaluate_one, tasks))
    result = {
        "protocol": "v5_1_development_disclosed_evaluation_v1",
        "model_version": MODEL_VERSION,
        "parameters": v5_1_development_default_parameters(),
        "release_public_sha256": receipt["public_sha256"],
        "release_secret_sha256": receipt["secret_sha256"],
        "blind_claim_allowed": False,
        "summary": summarize(case_scores),
        "case_scores": case_scores,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {"protocol": result["protocol"], "summary": result["summary"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
