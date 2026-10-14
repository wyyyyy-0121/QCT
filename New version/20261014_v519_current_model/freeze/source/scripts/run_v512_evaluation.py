"""Freeze Python sources or run label-free V5.1.2/legacy predictions.

Execute the frozen copy of this script for evaluation; public fixtures contain
workbook contents only. Both complete rankings and source/data hashes are bound
into the prediction lock. Runs refuse to overwrite an existing destination.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.metadata
import json
import math
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.score_v512_confirmation import safe_path, sha256, validate_ranking

VOLATILE_EVIDENCE_FIELDS = frozenset({"localization_seconds"})


def stable_evidence(evidence: dict) -> dict:
    return {key: value for key, value in evidence.items() if key not in VOLATILE_EVIDENCE_FIELDS}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def source_files(root: Path):
    return sorted([
        *root.glob("formulaguard/*.py"), *root.glob("scripts/*.py"), *root.glob("tests/*.py"),
        root / "pyproject.toml", root / "research/V512_DEVELOPMENT_PLAN.md",
    ])


def verify_source(lock_path: Path) -> dict:
    lock = json.loads(lock_path.read_text())
    for relative, digest in lock["artifacts"].items():
        if sha256(safe_path(ROOT, relative)) != digest:
            raise ValueError(f"source differs from frozen lock: {relative}")
    return lock


def freeze(destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for path in source_files(ROOT):
        relative = path.relative_to(ROOT).as_posix()
        target = destination / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        artifacts[relative] = sha256(target)
    lock = {
        "protocol": "v512_source_lock_v1", "frozen_at": datetime.now(UTC).isoformat(),
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "artifacts": artifacts, "python": platform.python_version(),
        "dependencies": {name: importlib.metadata.version(name) for name in ("numpy", "openpyxl")},
        "gates": {"control_fpr_max": .10, "ambiguous_rate_max": .10, "group_precision_min": .95,
                  "unsafe_groups_max": 0, "exact_coverage_min": .50},
        "evidence_scope": "project-administered held-out structure fixtures and retrospective real workbooks",
        "labels_read": [],
    }
    write_json(destination / "source_lock.json", lock)
    print(json.dumps({"source_lock": str(destination / "source_lock.json"), "sha256": sha256(destination / "source_lock.json"), "source_files": len(artifacts)}))


def load_workbook(path: Path, kind: str):
    from formulaguard.workbook import WorkbookModel
    if kind == "xlsx":
        return WorkbookModel.from_xlsx(path)
    if kind != "model_json":
        raise ValueError("unsupported public format")
    raw = json.loads(path.read_text())
    if set(raw) != {"cells", "formulas"}:
        raise ValueError("unexpected workbook fixture fields")
    return WorkbookModel.from_cells(
        {(s, c): value for s, c, value in raw["cells"]},
        {(s, c): formula for s, c, formula in raw["formulas"]},
    )


def predict_one(task):
    row, path, name = task
    workbook = load_workbook(Path(path), row["format"])
    before = dict(workbook.formulas)
    if name == "v512":
        from formulaguard.v5_1_2_development import v5_1_2_development_scores
        results = v5_1_2_development_scores(workbook)
    elif name == "v511":
        from formulaguard.v5_1_1_development import v5_1_1_development_scores
        results = v5_1_1_development_scores(workbook)
    elif name == "v4":
        from formulaguard.localize import v4_scores
        results = v4_scores(workbook)
    else:
        raise ValueError("unknown model")
    if before != workbook.formulas:
        raise ValueError("model changed input workbook")
    ranking = []
    groups = set()
    for rank, result in enumerate(results, 1):
        if not math.isfinite(result.score):
            raise ValueError("nonfinite model score")
        evidence = stable_evidence(dict(result.evidence))
        if evidence.get("group_state") == "accepted":
            groups.add(evidence["group_id"])
        ranking.append({"rank": rank, "sheet": result.cell[0], "cell": result.cell[1],
                        "score": result.score, "candidate_formula": result.candidate_formula, "evidence": evidence})
    shard = {"case_id": row["case_id"], "model": name, "cluster_id": row["cluster_id"],
             "workbook_sha256": row["workbook_sha256"], "formula_count": len(before),
             "accepted_group_count": len(groups), "ranking": ranking}
    validate_ranking(shard, list(before))
    return shard


def predict(args):
    verify_source(args.source_lock)
    public = args.public.resolve()
    manifest = json.loads((public / "manifest.json").read_text())
    if set(manifest) != {"protocol", "cases"} or manifest["protocol"] != "v512_public_v1":
        raise ValueError("unexpected public manifest")
    rows = manifest["cases"]
    if not rows or len({r["case_id"] for r in rows}) != len(rows):
        raise ValueError("empty or duplicate public cases")
    tasks = []
    for row in rows:
        if set(row) != {"case_id", "cluster_id", "workbook_path", "workbook_sha256", "format"}:
            raise ValueError("unexpected public fields")
        # case_id is used as a filename, so validate it independently.
        if not row["case_id"].isalnum():
            raise ValueError("unsafe case identity")
        path = safe_path(public, row["workbook_path"])
        if sha256(path) != row["workbook_sha256"]:
            raise ValueError("public workbook changed")
        tasks.append((row, str(path), args.model))
    args.output.mkdir(parents=True, exist_ok=False)
    workers = min(args.workers, len(tasks))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        for index, shard in enumerate(executor.map(predict_one, tasks), 1):
            write_json(args.output / "shards" / f"{shard['case_id']}.json", shard)
            if index % 20 == 0 or index == len(rows):
                print(f"{args.model}: {index}/{len(rows)}", flush=True)
    verify_source(args.source_lock)
    for row, path, _ in tasks:
        if sha256(Path(path)) != row["workbook_sha256"]:
            raise ValueError("input changed during prediction")
    metadata = {"model": args.model, "source_lock_sha256": sha256(args.source_lock),
                "public_manifest_sha256": sha256(public / "manifest.json"), "labels_read": [],
                "workers": workers, "python": platform.python_version(),
                "excluded_volatile_evidence_fields": sorted(VOLATILE_EVIDENCE_FIELDS)}
    write_json(args.output / "prediction_metadata.json", metadata)
    write_json(args.output / "prediction_lock.json", {
        "protocol": "v512_prediction_lock_v1", "model": args.model, "cases": len(rows),
        "metadata_sha256": sha256(args.output / "prediction_metadata.json"), "labels_read": [],
        "shards": {p.relative_to(args.output).as_posix(): sha256(p) for p in sorted((args.output / "shards").glob("*.json"))},
    })
    print(json.dumps({"lock_sha256": sha256(args.output / "prediction_lock.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freezer = sub.add_parser("freeze")
    freezer.add_argument("--output", type=Path, required=True)
    predictor = sub.add_parser("predict")
    predictor.add_argument("--source-lock", type=Path, required=True)
    predictor.add_argument("--public", type=Path, required=True)
    predictor.add_argument("--model", choices=("v512", "v511", "v4"), required=True)
    predictor.add_argument("--output", type=Path, required=True)
    predictor.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.output)
    else:
        if args.workers < 1:
            parser.error("workers must be positive")
        predict(args)


if __name__ == "__main__":
    main()
