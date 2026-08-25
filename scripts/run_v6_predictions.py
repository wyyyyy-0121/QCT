"""Resumable, label-free multiprocess prediction runner for V6."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.localize import v4_scores
from formulaguard.v6 import v6_ablation_scores, v6_default_parameters, v6_prepared_v4_scores, v6_scores
from formulaguard.workbook import WorkbookModel


EVIDENCE_FIELDS = (
    "model_version", "v4_rank", "v6_rank", "semantic_tier", "family_support",
    "family_margin", "boundary_support", "boundary_margin", "candidate_formula",
    "candidate_sources", "candidate_edit_kinds", "candidate_reference_quality",
    "candidate_portfolio", "semantic_energy_gain", "counterfactual_delta", "counterfactual_irg", "global_harm",
    "promotion_target", "promotion_reason", "propagation_path", "localization_seconds",
)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
        return subprocess.check_output([str(bundled), "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def serial_result(result, rank: int) -> dict:
    evidence = dict(result.evidence)
    for key in EVIDENCE_FIELDS:
        evidence.setdefault(key, [] if key in {"candidate_portfolio", "propagation_path"} else "")
    return {
        "rank": rank,
        "cell": result.cell_label,
        "score": result.score,
        "candidate_formula": result.candidate_formula or "",
        "evidence": evidence,
    }


def serial_ablation_result(result, rank: int) -> dict:
    """Keep complete ranks without duplicating the large evidence portfolio."""
    return {
        "rank": rank,
        "cell": result.cell_label,
        "score": result.score,
        "candidate_formula": result.candidate_formula or "",
        "evidence": {},
    }


def audit_complete_shard(path: Path, row: dict, benchmark: Path, expected_methods: set[str]) -> None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Completion audit cannot read shard {path}: {exc}") from exc
    if record.get("instance_id") != row["instance_id"]:
        raise SystemExit(f"Completion audit found wrong instance_id in {path}")
    if record.get("workbook") != row["mutant_workbook"]:
        raise SystemExit(f"Completion audit found wrong workbook path in {path}")
    if record.get("workbook_sha256") != hash_file(benchmark / row["mutant_workbook"]):
        raise SystemExit(f"Completion audit found changed workbook in {path}")
    formula_count = record.get("formula_count")
    rankings = record.get("rankings", {})
    if not isinstance(formula_count, int) or formula_count < 1 or set(rankings) != expected_methods:
        raise SystemExit(f"Completion audit found incomplete method set in {path}")
    reference_cells = None
    for method in sorted(expected_methods):
        ranking = rankings[method]
        cells = [item.get("cell") for item in ranking]
        ranks = [item.get("rank") for item in ranking]
        if len(ranking) != formula_count or len(set(cells)) != formula_count:
            raise SystemExit(f"Completion audit found missing or duplicate cells: {path} {method}")
        if ranks != list(range(1, formula_count + 1)):
            raise SystemExit(f"Completion audit found invalid ranks: {path} {method}")
        if reference_cells is None:
            reference_cells = set(cells)
        elif set(cells) != reference_cells:
            raise SystemExit(f"Completion audit found inconsistent formula-cell sets: {path} {method}")
        if method in {"v6_a", "v6_b", "v6_c"}:
            required = {
                "model_version", "v4_rank", "v6_rank", "semantic_tier",
                "candidate_portfolio", "semantic_energy_gain", "counterfactual_delta",
                "counterfactual_irg", "global_harm", "propagation_path",
            }
            if any(not required <= set(item.get("evidence", {})) for item in ranking):
                raise SystemExit(f"Completion audit found incomplete V6 evidence: {path} {method}")


def task(payload):
    root_text, output_text, row, variants, ablations = payload
    root, output = Path(root_text), Path(output_text)
    model = WorkbookModel.from_xlsx(root / row["mutant_workbook"])
    rankings = {}
    started = time.perf_counter()
    for variant in variants:
        results = v6_scores(model, variant=variant, base_candidate_limit=15, semantic_candidate_limit=25)
        rankings[f"v6_{variant}"] = [serial_result(result, rank) for rank, result in enumerate(results, 1)]
    for variant in variants:
        for ablation in ablations:
            results = v6_ablation_scores(model, ablation, variant=variant)
            rankings[f"v6_{variant}_ablation_{ablation}"] = [
                serial_ablation_result(result, rank) for rank, result in enumerate(results, 1)
            ]
    base = v6_prepared_v4_scores(model, candidate_limit=15)
    rankings["v4"] = [serial_result(result, rank) for rank, result in enumerate(base, 1)]
    record = {
        "instance_id": row["instance_id"],
        "workbook": row["mutant_workbook"],
        "workbook_sha256": hash_file(root / row["mutant_workbook"]),
        "formula_count": len(model.formulas),
        "rankings": rankings,
        "wall_seconds": time.perf_counter() - started,
    }
    shard = output / "shards" / f"{row['instance_id']}.json"
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return row["instance_id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=("a", "b", "c"), required=True)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--clean", action="store_true", help="Read clean_manifest.json instead of instances.jsonl")
    parser.add_argument("--ablations", nargs="*", default=[])
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.clean:
        clean_rows = json.loads((args.benchmark / "clean_manifest.json").read_text(encoding="utf-8"))
        rows = [{"instance_id": row["clean_id"], "mutant_workbook": row["workbook"]} for row in clean_rows]
        public_manifest = args.benchmark / "clean_manifest.json"
    else:
        rows = read_jsonl(args.benchmark / "instances.jsonl")
        public_manifest = args.benchmark / "instances.jsonl"
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        raise SystemExit("No public V6 instances found")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "shards").mkdir(exist_ok=True)
    inputs = {
        "protocol": "v6_label_free_predictions_v1",
        "benchmark": str(args.benchmark.resolve()),
        "instances_sha256": hash_file(public_manifest),
        "dataset_manifest_sha256": hash_file(args.benchmark / "dataset_manifest.json"),
        "dataset_completion_sha256": hash_file(args.benchmark / "dataset_build_complete.json"),
        "v6_source_sha256": hash_file(ROOT / "formulaguard/v6.py"),
        "v4_source_sha256": hash_file(ROOT / "formulaguard/localize.py"),
        "method_spec_sha256": hash_file(ROOT / "research/V6_METHOD_SPEC.md"),
        "git_commit": git_commit(),
        "variants": args.variants,
        "ablations": args.ablations,
        "parameters": v6_default_parameters(),
        "instance_count": len(rows),
        "clean_control_mode": args.clean,
        "label_files_read": [],
    }
    metadata_path = args.output / "prediction_metadata.json"
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous != inputs:
            raise SystemExit("Resume refused: input, code, commit, config, or instance list changed")
        if not args.resume:
            raise SystemExit("Output exists; pass --resume to verify and continue")
    else:
        metadata_path.write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")

    pending = []
    for row in rows:
        shard = args.output / "shards" / f"{row['instance_id']}.json"
        if shard.exists():
            try:
                record = json.loads(shard.read_text(encoding="utf-8"))
                if record["workbook_sha256"] == hash_file(args.benchmark / row["mutant_workbook"]):
                    continue
            except Exception:
                pass
            raise SystemExit(f"Resume refused: invalid existing shard {shard}")
        pending.append(row)
    worker_count = min(args.workers, max(1, len(pending)))
    print(f"V6 scheduling: {worker_count} workers; {len(pending)} pending; {len(rows)-len(pending)} resumed.", flush=True)
    payloads = [(str(args.benchmark), str(args.output), row, tuple(args.variants), tuple(args.ablations)) for row in pending]
    if worker_count == 1:
        iterator = map(task, payloads)
        for index, instance_id in enumerate(iterator, 1):
            print(f"[{index}/{len(pending)}] {instance_id}", flush=True)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(task, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                instance_id = future.result()
                print(f"[{index}/{len(pending)}] {instance_id}", flush=True)
    shard_paths = sorted((args.output / "shards").glob("*.json"))
    expected = {row["instance_id"] for row in rows}
    observed = {path.stem for path in shard_paths}
    if observed != expected:
        raise SystemExit(f"Merge refused: missing={len(expected-observed)}, extra={len(observed-expected)}")
    expected_methods = {"v4", *(f"v6_{variant}" for variant in args.variants)}
    expected_methods.update(
        f"v6_{variant}_ablation_{ablation}"
        for variant in args.variants for ablation in args.ablations
    )
    rows_by_id = {row["instance_id"]: row for row in rows}
    for path in shard_paths:
        audit_complete_shard(path, rows_by_id[path.stem], args.benchmark, expected_methods)
    digest = hashlib.sha256()
    for path in shard_paths:
        digest.update(path.name.encode()); digest.update(bytes.fromhex(hash_file(path)))
    completion = {
        "protocol": "v6_atomic_prediction_completion",
        "complete": True,
        "instances": len(rows),
        "workers_requested": args.workers,
        "combined_shards_sha256": digest.hexdigest(),
        "metadata_sha256": hash_file(metadata_path),
        "full_ranking_audit_passed": True,
        "labels_may_be_read_by_separate_scorer": True,
    }
    (args.output / "prediction_complete.json").write_text(json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "prediction_complete.json")


if __name__ == "__main__":
    main()
