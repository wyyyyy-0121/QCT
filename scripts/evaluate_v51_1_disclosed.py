"""Evaluate V5.1.1 on the already disclosed natural confirmation cohort.

This script is development-only.  It intentionally reads the disclosed
SECRET and must not be used as a new blind confirmation result.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.workbook import WorkbookModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.score_v51_natural_confirmation import load_secret, score_case, summarize


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = args.release.resolve()
    receipt = json.loads((release / "release_receipt.json").read_text(encoding="utf-8"))
    labels = load_secret(release / receipt["secret_archive"], receipt["secret_sha256"])
    labels_by_id = {case["case_id"]: case for case in labels["cases"]}
    with (release / "PUBLIC" / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        manifest = {row["case_id"]: row for row in csv.DictReader(stream)}
    rows = []
    for case_id, label in labels_by_id.items():
        workbook = WorkbookModel.from_xlsx(
            release / "PUBLIC" / manifest[case_id]["workbook_path"]
        )
        predictions = v5_1_1_development_scores(workbook)
        groups = {
            str(result.evidence.get("group_id")): result.evidence.get("group_state")
            for result in predictions
            if result.evidence.get("group_id")
        }
        shard = {
            "case_id": case_id,
            "accepted_group_count": sum(state == "accepted" for state in groups.values()),
            "ranking": [
                {
                    "sheet": result.cell[0],
                    "cell": result.cell[1],
                    "candidate_formula": result.candidate_formula,
                    "evidence": dict(result.evidence),
                }
                for result in predictions
            ],
        }
        rows.append(score_case(shard, label))
    result = {
        "protocol": "v51_1_disclosed_development_evaluation_v1",
        "warning": "Disclosed SECRET; not blind confirmation evidence.",
        "summary": summarize(rows),
        "case_scores": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
