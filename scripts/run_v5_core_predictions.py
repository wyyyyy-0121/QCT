"""Resumable, atomic, label-free V5-Core prediction runner."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.localize import v4_scores
from formulaguard.v4x import v4_3_scores
from formulaguard.v5_core import v5_core_ablation_scores, v5_core_default_parameters, v5_core_scores
from formulaguard.workbook import WorkbookModel


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = shutil.which("git") or str(bundled)
    return subprocess.check_output([executable, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def serial_result(result, rank: int, *, compact: bool = False) -> dict:
    return {
        "rank": rank,
        "cell": result.cell_label,
        "score": result.score,
        "candidate_formula": result.candidate_formula or "",
        "evidence": {} if compact else dict(result.evidence),
    }


def _method_set(learned_config: dict | None, baselines: bool, ablations: tuple[str, ...]) -> set[str]:
    methods = {"v5_rule"}
    if learned_config is not None:
        methods.add("v5_learned")
    if baselines:
        methods.update({"v4", "v4_3"})
    methods.update(f"v5_rule_ablation_{item}" for item in ablations)
    if learned_config is not None:
        methods.update(f"v5_learned_ablation_{item}" for item in ablations)
    return methods


def task(payload):
    benchmark_text, output_text, row, rule_config, learned_config, baselines, ablations = payload
    benchmark, output = Path(benchmark_text), Path(output_text)
    workbook = benchmark / row["mutant_workbook"]
    model = WorkbookModel.from_xlsx(workbook)
    rankings: dict[str, list[dict]] = {}
    method_seconds: dict[str, float] = {}
    started = time.perf_counter()
    rule = v5_core_scores(model, head="rule", config=rule_config)
    rankings["v5_rule"] = [serial_result(item, rank) for rank, item in enumerate(rule, 1)]
    method_seconds["v5_rule"] = float(rule[0].evidence.get("localization_seconds", 0.0)) if rule else 0.0
    if learned_config is not None:
        learned = v5_core_scores(model, head="learned", config=learned_config)
        rankings["v5_learned"] = [serial_result(item, rank) for rank, item in enumerate(learned, 1)]
        method_seconds["v5_learned"] = float(learned[0].evidence.get("localization_seconds", 0.0)) if learned else 0.0
    for ablation in ablations:
        values = v5_core_ablation_scores(model, ablation, head="rule", config=rule_config)
        rankings[f"v5_rule_ablation_{ablation}"] = [
            serial_result(item, rank, compact=True) for rank, item in enumerate(values, 1)
        ]
        method_seconds[f"v5_rule_ablation_{ablation}"] = float(values[0].evidence.get("localization_seconds", 0.0)) if values else 0.0
        if learned_config is not None:
            learned_values = v5_core_ablation_scores(
                model, ablation, head="learned", config=learned_config,
            )
            rankings[f"v5_learned_ablation_{ablation}"] = [
                serial_result(item, rank, compact=True)
                for rank, item in enumerate(learned_values, 1)
            ]
            method_seconds[f"v5_learned_ablation_{ablation}"] = (
                float(learned_values[0].evidence.get("localization_seconds", 0.0))
                if learned_values else 0.0
            )
    if baselines:
        baseline_v4 = v4_scores(model, candidate_limit=15)
        baseline_v43 = v4_3_scores(model, variant="b")
        rankings["v4"] = [serial_result(item, rank, compact=True) for rank, item in enumerate(baseline_v4, 1)]
        rankings["v4_3"] = [serial_result(item, rank, compact=True) for rank, item in enumerate(baseline_v43, 1)]
        method_seconds["v4"] = float(baseline_v4[0].evidence.get("localization_seconds", 0.0)) if baseline_v4 else 0.0
        method_seconds["v4_3"] = float(baseline_v43[0].evidence.get("localization_seconds", 0.0)) if baseline_v43 else 0.0
    record = {
        "instance_id": row["instance_id"],
        "workbook": row["mutant_workbook"],
        "workbook_sha256": hash_file(workbook),
        "formula_count": len(model.formulas),
        "rankings": rankings,
        "method_seconds": method_seconds,
        "wall_seconds": time.perf_counter() - started,
    }
    shard = output / "shards" / f"{row['instance_id']}.json"
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return row["instance_id"]


def audit_shard(path: Path, row: dict, benchmark: Path, methods: set[str]) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("instance_id") != row["instance_id"]:
        raise SystemExit(f"Wrong instance in {path}")
    if record.get("workbook_sha256") != hash_file(benchmark / row["mutant_workbook"]):
        raise SystemExit(f"Workbook changed for {path}")
    if set(record.get("rankings", {})) != methods:
        raise SystemExit(f"Incomplete methods in {path}")
    formula_count = int(record["formula_count"])
    reference_cells = None
    for method, ranking in record["rankings"].items():
        cells = [item["cell"] for item in ranking]
        if len(ranking) != formula_count or len(set(cells)) != formula_count:
            raise SystemExit(f"Incomplete ranking in {path}: {method}")
        if [item["rank"] for item in ranking] != list(range(1, formula_count + 1)):
            raise SystemExit(f"Invalid ranks in {path}: {method}")
        if reference_cells is None:
            reference_cells = set(cells)
        elif set(cells) != reference_cells:
            raise SystemExit(f"Inconsistent cells in {path}: {method}")
        if method in {"v5_rule", "v5_learned"}:
            required = {
                "regime_id", "candidate_portfolio", "structural_evidence",
                "causal_evidence", "graph_recovery_evidence", "replication_evidence",
                "exception_likelihood", "feature_vector", "propagation_path",
                "evaluated_candidate_features",
            }
            if any(not required <= set(item["evidence"]) for item in ranking):
                raise SystemExit(f"Incomplete V5 evidence in {path}: {method}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="Deprecated alias for --learned-config")
    parser.add_argument("--rule-config", type=Path)
    parser.add_argument("--learned-config", type=Path)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--baselines", action="store_true")
    parser.add_argument("--ablations", nargs="*", default=[])
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.clean:
        clean_rows = json.loads((args.benchmark / "clean_manifest.json").read_text(encoding="utf-8"))
        rows = [
            {"instance_id": item["clean_id"], "mutant_workbook": item["workbook"]}
            for item in clean_rows
        ]
        public_manifest = args.benchmark / "clean_manifest.json"
    else:
        rows = read_jsonl(args.benchmark / "instances.jsonl")
        public_manifest = args.benchmark / "instances.jsonl"
    if args.offset:
        rows = rows[args.offset:]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("No public V5-Core workbooks found")
    learned_path = args.learned_config or args.config
    rule_config = json.loads(args.rule_config.read_text(encoding="utf-8")) if args.rule_config else None
    learned_config = json.loads(learned_path.read_text(encoding="utf-8")) if learned_path else None
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "shards").mkdir(exist_ok=True)
    source_paths = [ROOT / "formulaguard/v5_core.py", ROOT / "research/V5_CORE_METHOD_SPEC.md"]
    metadata = {
        "protocol": "v5_core_label_free_predictions_v1",
        "benchmark": str(args.benchmark.resolve()),
        "instances_sha256": hash_file(public_manifest),
        "dataset_manifest_sha256": hash_file(args.benchmark / "dataset_manifest.json"),
        "source_sha256": {path.name: hash_file(path) for path in source_paths if path.exists()},
        "rule_config_sha256": hash_file(args.rule_config) if args.rule_config else None,
        "learned_config_sha256": hash_file(learned_path) if learned_path else None,
        "git_commit": git_commit(),
        "parameters": v5_core_default_parameters(),
        "instance_count": len(rows),
        "clean_control_mode": args.clean,
        "baselines": args.baselines,
        "ablations": args.ablations,
        "workers_requested": args.workers,
        "offset": args.offset,
        "label_files_read": [],
    }
    metadata_path = args.output / "prediction_metadata.json"
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous != metadata:
            raise SystemExit("Resume refused: inputs, code, commit, config, or workbooks changed")
        if not args.resume:
            raise SystemExit("Output exists; pass --resume to verify and continue")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    methods = _method_set(learned_config, args.baselines, tuple(args.ablations))
    pending = []
    for row in rows:
        shard = args.output / "shards" / f"{row['instance_id']}.json"
        if shard.exists():
            audit_shard(shard, row, args.benchmark, methods)
        else:
            pending.append(row)
    worker_count = min(args.workers, max(1, len(pending)))
    print(
        f"V5-Core scheduling: {worker_count} workers; {len(pending)} pending; "
        f"{len(rows) - len(pending)} resumed.", flush=True,
    )
    payloads = [
        (str(args.benchmark), str(args.output), row, rule_config, learned_config, args.baselines, tuple(args.ablations))
        for row in pending
    ]
    if worker_count == 1:
        for index, payload in enumerate(payloads, 1):
            print(f"[{index}/{len(payloads)}] {task(payload)}", flush=True)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(task, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"[{index}/{len(payloads)}] {future.result()}", flush=True)
    expected = {row["instance_id"] for row in rows}
    shards = sorted((args.output / "shards").glob("*.json"))
    observed = {path.stem for path in shards}
    if observed != expected:
        raise SystemExit(f"Merge refused: missing={len(expected-observed)}, extra={len(observed-expected)}")
    rows_by_id = {row["instance_id"]: row for row in rows}
    for shard in shards:
        audit_shard(shard, rows_by_id[shard.stem], args.benchmark, methods)
    digest = hashlib.sha256()
    for shard in shards:
        digest.update(shard.name.encode("utf-8"))
        digest.update(bytes.fromhex(hash_file(shard)))
    completion = {
        "protocol": "v5_core_atomic_prediction_completion_v1",
        "complete": True,
        "instances": len(rows),
        "workers_requested": args.workers,
        "combined_shards_sha256": digest.hexdigest(),
        "metadata_sha256": hash_file(metadata_path),
        "full_ranking_audit_passed": True,
        "labels_may_be_read_by_separate_scorer": True,
    }
    completion_path = args.output / "prediction_complete.json"
    completion_path.write_text(json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8")
    print(completion_path)


if __name__ == "__main__":
    main()
