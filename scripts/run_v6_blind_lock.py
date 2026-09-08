"""Hash-lock joint frozen V4/V6 predictions for the third-party 600 cases."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from formulaguard.v6 import v6_prepared_v4_scores, v6_scores
from formulaguard.workbook import WorkbookModel
from scripts.verify_v6_freeze import verify


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task(payload):
    public_text, output_text, row, variant = payload
    public, output = Path(public_text), Path(output_text)
    path = public / row["workbook"]
    model = WorkbookModel.from_xlsx(path)
    rankings = {}
    v6 = v6_scores(model, variant=variant)
    base = v6_prepared_v4_scores(model, candidate_limit=15)
    for method, results in (("v4", base), ("v6", v6)):
        rankings[method] = [
            {
                "rank": rank,
                "cell": result.cell_label,
                "score": result.score,
                "candidate_formula": result.candidate_formula or "",
                "evidence": {
                    **{
                        key: result.evidence.get(key, "")
                        for key in (
                        "model_version", "v4_rank", "v6_rank", "semantic_tier", "family_support",
                        "family_margin", "boundary_support", "boundary_margin", "candidate_sources",
                        "candidate_edit_kinds", "candidate_reference_quality", "semantic_energy_gain", "counterfactual_delta",
                        "counterfactual_irg", "global_harm", "promotion_target", "promotion_reason",
                        "propagation_path", "localization_seconds",
                        )
                    },
                    "candidate_formulas": [
                        item.get("formula", "")
                        for item in result.evidence.get("candidate_portfolio", [])[:25]
                    ],
                },
            }
            for rank, result in enumerate(results, 1)
        ]
    record = {
        "instance_id": row["instance_id"],
        "workbook": row["workbook"],
        "workbook_sha256": sha256(path),
        "formula_count": len(model.formulas),
        "rankings": rankings,
    }
    shard = output / "shards" / f"{row['instance_id']}.json"
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return row["instance_id"]


def audit_locked_shard(path: Path, row: dict, public: Path) -> None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Blind lock cannot read shard {path}: {exc}") from exc
    if record.get("instance_id") != row["instance_id"] or record.get("workbook") != row["workbook"]:
        raise SystemExit(f"Blind lock found mismatched shard identity: {path}")
    if record.get("workbook_sha256") != sha256(public / row["workbook"]):
        raise SystemExit(f"Blind lock found a changed workbook: {path}")
    formula_count = record.get("formula_count")
    rankings = record.get("rankings", {})
    if not isinstance(formula_count, int) or formula_count < 1 or set(rankings) != {"v4", "v6"}:
        raise SystemExit(f"Blind lock found incomplete methods: {path}")
    cell_sets = []
    for method in ("v4", "v6"):
        ranking = rankings[method]
        cells = [item.get("cell") for item in ranking]
        if len(ranking) != formula_count or len(set(cells)) != formula_count:
            raise SystemExit(f"Blind lock found incomplete ranking: {path} {method}")
        if [item.get("rank") for item in ranking] != list(range(1, formula_count + 1)):
            raise SystemExit(f"Blind lock found invalid rank sequence: {path} {method}")
        cell_sets.append(set(cells))
    if cell_sets[0] != cell_sets[1]:
        raise SystemExit(f"Blind lock found inconsistent V4/V6 formula cells: {path}")
    required = {
        "model_version", "v4_rank", "v6_rank", "semantic_tier",
        "semantic_energy_gain", "counterfactual_delta", "counterfactual_irg",
        "global_harm", "promotion_reason", "propagation_path", "candidate_formulas",
    }
    if any(not required <= set(item.get("evidence", {})) for item in rankings["v6"]):
        raise SystemExit(f"Blind lock found incomplete V6 evidence: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", type=Path, default=Path("data/v6_third_party_public"))
    parser.add_argument("--output", type=Path, default=Path("results/v6_independent_600_locked"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    config = verify()
    manifest = args.public / "manifest.csv"
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["instance_id", "workbook"]:
            raise SystemExit("Blind lock refused: public manifest must have exactly instance_id,workbook")
        rows = list(reader)
    if len(rows) != 600 or len({row["instance_id"] for row in rows}) != 600:
        raise SystemExit("Blind lock refused: exactly 600 unique cases are required")
    public_resolved = args.public.resolve()
    workbook_paths = []
    for row in rows:
        candidate = (args.public / row["workbook"]).resolve()
        if public_resolved not in candidate.parents or candidate.suffix.lower() != ".xlsx" or not candidate.is_file():
            raise SystemExit(f"Blind lock refused: unsafe or missing workbook path: {row['workbook']}")
        workbook_paths.append(candidate)
    if len(workbook_paths) != len(set(workbook_paths)):
        raise SystemExit("Blind lock refused: workbook paths must be unique")
    forbidden = [path for path in args.public.rglob("*") if path.is_file() and any(token in path.name.lower() for token in ("label", "secret", "answer", "original")) and path.name != "secret_precommit_sha256.txt"]
    if forbidden:
        raise SystemExit(f"Blind lock refused: forbidden label-like public files: {forbidden[:3]}")
    precommit_path = args.public / "secret_precommit_sha256.txt"
    if not precommit_path.is_file():
        raise SystemExit("Blind lock refused: public precommit file is missing")
    args.output.mkdir(parents=True, exist_ok=True); (args.output / "shards").mkdir(exist_ok=True)
    metadata = {
        "protocol": "v6_joint_blind_600_label_free_lock",
        "selected_variant": config["selected_variant"],
        "freeze_implementation_commit": config["implementation_commit"],
        "frozen_config_sha256": sha256(ROOT / "research/frozen_config_v6.json"),
        "manifest_sha256": sha256(manifest),
        "precommit_sha256_file": sha256(precommit_path),
        "workbooks": [{"instance_id": row["instance_id"], "workbook": row["workbook"], "sha256": sha256(args.public / row["workbook"])} for row in rows],
        "label_paths_read": [],
        "labels_forbidden_until_lock": True,
        "workers_requested": args.workers,
    }
    metadata_path = args.output / "joint_prediction_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("Blind resume refused: inputs or frozen configuration changed")
        if not args.resume:
            raise SystemExit("Blind output exists; pass --resume")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    pending = []
    for row in rows:
        shard = args.output / "shards" / f"{row['instance_id']}.json"
        if shard.exists():
            record = json.loads(shard.read_text(encoding="utf-8"))
            if record["workbook_sha256"] != sha256(args.public / row["workbook"]):
                raise SystemExit(f"Blind resume refused: invalid shard {shard}")
        else:
            pending.append((str(args.public), str(args.output), row, config["selected_variant"]))
    workers = min(args.workers, max(1, len(pending)))
    print(f"V6 blind scheduling: {workers} workers; {len(pending)} pending.", flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        for index, instance_id in enumerate(executor.map(task, pending, chunksize=1), 1):
            print(f"[{index}/{len(pending)}] {instance_id}", flush=True)
    shard_paths = sorted((args.output / "shards").glob("*.json"))
    expected_ids = {row["instance_id"] for row in rows}
    if {path.stem for path in shard_paths} != expected_ids:
        raise SystemExit("Blind lock refused: shard instance set differs from the 600-case manifest")
    rows_by_id = {row["instance_id"]: row for row in rows}
    for path in shard_paths:
        audit_locked_shard(path, rows_by_id[path.stem], args.public)
    combined = hashlib.sha256()
    for path in shard_paths:
        combined.update(path.name.encode()); combined.update(bytes.fromhex(sha256(path)))
    lock = {
        "protocol": "v6_joint_blind_prediction_sha256_lock",
        "locked": True,
        "cases": 600,
        "combined_shards_sha256": combined.hexdigest(),
        "metadata_sha256": sha256(metadata_path),
        "full_ranking_audit_passed": True,
        "instruction": "Labels may be released only after this file exists and all hashes verify.",
    }
    (args.output / "prediction_lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "prediction_lock.json")


if __name__ == "__main__":
    main()
