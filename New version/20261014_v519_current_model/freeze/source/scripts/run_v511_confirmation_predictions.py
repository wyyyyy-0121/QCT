"""Run the frozen V5.1.1 model on label-free confirmation PUBLIC."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_v51_confirmation_predictions import (
    git,
    load_public,
    prepare_source,
    safe_path,
    sha256_file,
    write_json,
)

_SOURCE_ROOT = ""


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def combined_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def predict_one(task: tuple[dict[str, str], str]) -> dict[str, object]:
    from formulaguard.v5_1_1_development import (
        MODEL_VERSION,
        v5_1_1_development_scores,
    )
    from formulaguard.workbook import WorkbookModel

    row, workbook_path = task
    model = WorkbookModel.from_xlsx(Path(workbook_path))
    before = dict(model.formulas)
    results = v5_1_1_development_scores(model)
    if model.formulas != before:
        raise ValueError(f"model mutated workbook: {row['case_id']}")
    if {result.cell for result in results} != set(model.formula_cells):
        raise ValueError(f"incomplete ranking: {row['case_id']}")
    groups: dict[str, tuple[str, str]] = {}
    ranking = []
    for rank, result in enumerate(results, 1):
        if not math.isfinite(float(result.score)):
            raise ValueError(f"non-finite score: {row['case_id']}")
        evidence = dict(result.evidence)
        group_id = str(evidence.get("group_id", ""))
        if group_id:
            groups[group_id] = (
                str(evidence.get("group_state", "")),
                str(evidence.get("group_reason", "")),
            )
        ranking.append(
            {
                "rank": rank,
                "sheet": result.cell[0],
                "cell": result.cell[1],
                "score": result.score,
                "candidate_formula": result.candidate_formula,
                "evidence": evidence,
            }
        )
    return {
        "protocol": "v511_natural_confirmation_prediction_shard_v1",
        "model": "v5_1_1_development",
        "model_version": MODEL_VERSION,
        "case_id": row["case_id"],
        "cluster_id": row["cluster_id"],
        "workbook_sha256": row["workbook_sha256"],
        "formula_count": len(ranking),
        "candidate_count": sum(item["candidate_formula"] is not None for item in ranking),
        "accepted_group_count": sum(state == "accepted" for state, _ in groups.values()),
        "ranking": ranking,
    }


def init_worker(source_root: str) -> None:
    global _SOURCE_ROOT
    _SOURCE_ROOT = source_root
    sys.path.insert(0, source_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--public-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    model_spec = lock["models"]["v5_1_1_development"]
    public = args.public.resolve()
    rows = load_public(public, args.public_archive.resolve())
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output: {args.output}")
    args.output.mkdir(parents=True)
    shards_dir = args.output / "shards"
    shards_dir.mkdir()
    with tempfile.TemporaryDirectory(prefix="v511-confirmation-") as temporary:
        resolved, tree = prepare_source(model_spec, Path(temporary))
        tasks = [(row, str(safe_path(public, row["workbook_path"]))) for row in rows]
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(args.workers, len(tasks)),
            initializer=init_worker,
            initargs=(temporary,),
        ) as executor:
            for record in executor.map(predict_one, tasks):
                write_json(shards_dir / f"{record['case_id']}.json", record)
    paths = list(shards_dir.glob("*.json"))
    if len(paths) != len(rows):
        raise SystemExit("prediction shard count differs from PUBLIC")
    metadata = {
        "protocol": "v511_natural_confirmation_prediction_metadata_v1",
        "model": "v5_1_1_development",
        "resolved_commit": resolved,
        "source_tree": tree,
        "parameters": model_spec["parameters"],
        "public_archive_sha256": sha256_file(args.public_archive.resolve()),
        "labels_read": [],
        "workers": min(args.workers, len(tasks)),
        "runner_commit": git("rev-parse", "HEAD").strip(),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    write_json(args.output / "prediction_metadata.json", metadata)
    write_json(
        args.output / "prediction_lock.json",
        {
            "protocol": "v511_natural_confirmation_prediction_lock_v1",
            "model": "v5_1_1_development",
            "cases": len(rows),
            "combined_shards_sha256": combined_hash(paths),
            "metadata_sha256": sha256_file(args.output / "prediction_metadata.json"),
            "labels_read": [],
            "locked": True,
        },
    )
    print((args.output / "prediction_lock.json").read_text(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
