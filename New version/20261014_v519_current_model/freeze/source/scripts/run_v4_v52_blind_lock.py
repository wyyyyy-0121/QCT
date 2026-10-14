"""Create a joint, label-free prediction lock for frozen V4 and V5.2."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.localize import v4_default_parameters, v4_scores
from formulaguard.v52 import v52_default_parameters, v52_from_v4
from formulaguard.workbook import WorkbookModel
from scripts.freeze_v4_model import verify_model_source_hashes
from scripts.run_external_evaluation import sha256_file
from scripts.v52_blind_protocol import FORBIDDEN_LABEL_FIELDS, validate_public_manifest


def _ranking_hash(cells: list[str]) -> str:
    return hashlib.sha256("\n".join(cells).encode("utf-8")).hexdigest()


def _one_path(model: WorkbookModel, cell) -> str:
    graph = model.dependency_graph()
    candidates = []
    for sink in graph.sinks(model.formula_cells):
        path = graph.shortest_path(cell, sink)
        if path and len(path) > 1:
            candidates.append(path)
    if not candidates:
        return ""
    path = min(candidates, key=lambda value: (len(value), value))
    return " -> ".join(f"{sheet}!{address}" for sheet, address in path)


def _predict(task: tuple[str, str, str, str, int]):
    workbook_text, instance_id, workbook_label, variant, candidate_limit = task
    model = WorkbookModel.from_xlsx(Path(workbook_text))
    started = time.perf_counter()
    v4 = v4_scores(model, candidate_limit=candidate_limit)
    decision = v52_from_v4(
        model, v4, variant=variant, candidate_limit=candidate_limit
    )
    elapsed = time.perf_counter() - started
    cells = [result.cell_label for result in v4]
    order_hash = _ranking_hash(cells)
    ranking_rows = []
    for rank, result in enumerate(v4, 1):
        ranking_rows.append({
            "instance_id": instance_id,
            "workbook": workbook_label,
            "method": "formulaguard_v4",
            "rank": rank,
            "formula_count": len(v4),
            "cell": result.cell_label,
            "score": result.score,
            "candidate_formula": result.candidate_formula or "",
            "diagnostic_status": result.evidence.get("diagnostic_status", ""),
            "formula_rank": result.evidence.get("formula_rank", ""),
            "base_rank": result.evidence.get("base_rank", ""),
            "candidate_delta": result.evidence.get("candidate_delta", ""),
            "intervention_responsibility_gain": result.evidence.get(
                "intervention_responsibility_gain", ""
            ),
            "candidate_support": result.evidence.get("candidate_support", ""),
            "candidate_source": result.evidence.get("candidate_source", ""),
            "propagation_path": _one_path(model, result.cell) if rank <= 5 else "",
            "runtime_seconds": elapsed,
        })
    rescue = decision.rescue
    rescue_result = rescue.result if rescue else None
    decision_row = {
        "instance_id": instance_id,
        "workbook": workbook_label,
        "variant": variant,
        "formula_count": len(v4),
        "v4_order_sha256": order_hash,
        "v52_core_order_sha256": _ranking_hash(
            [result.cell_label for result in decision.core_ranking]
        ),
        "core_top5": ";".join(cells[:5]),
        "review_set": ";".join(item.cell_label for item in decision.review_set),
        "rescue_status": decision.status,
        "rescue_reason": decision.reason,
        "eligible_candidate_count": len(decision.eligible),
        "rescue_cell": rescue_result.cell_label if rescue_result else "",
        "rescue_v4_rank": rescue.v4_rank if rescue else "",
        "rescue_formula_rank": rescue.formula_rank if rescue else "",
        "rescue_irg": rescue.irg if rescue else "",
        "rescue_delta": rescue.delta if rescue else "",
        "rescue_repair_sources": ",".join(rescue.repair_sources) if rescue else "",
        "rescue_reference_quality": rescue.reference_quality if rescue else "",
        "rescue_candidate_formula": rescue_result.candidate_formula if rescue_result else "",
        "rescue_propagation_path": _one_path(model, rescue_result.cell) if rescue_result else "",
        "runtime_seconds": elapsed,
    }
    return instance_id, ranking_rows, decision_row


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _git_head(root: Path) -> str:
    candidates = ["git"]
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    if bundled.is_file():
        candidates.insert(0, str(bundled))
    for executable in candidates:
        try:
            return subprocess.run(
                [executable, "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            continue
    raise ValueError("Unable to resolve the Git commit")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lock joint V4/V5.2 predictions without labels")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--v4-config", type=Path, required=True)
    parser.add_argument("--v52-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty lock directory: {args.output}")
    try:
        v4_config = json.loads(args.v4_config.read_text(encoding="utf-8"))
        if v4_config.get("v4_parameters") != v4_default_parameters():
            raise ValueError("Running V4 parameters differ from the frozen configuration")
        verify_model_source_hashes(
            {"source_sha256": v4_config.get("model_source_sha256")}, root
        )
        v52_config = json.loads(args.v52_config.read_text(encoding="utf-8"))
        variant = str(v52_config["selected_variant"])
        if v52_config.get("v52_parameters") != v52_default_parameters(variant):
            raise ValueError("Running V5.2 parameters differ from the frozen configuration")
        verify_model_source_hashes(
            {"source_sha256": v52_config.get("model_source_sha256")}, root
        )
        rows, workbook_hashes = validate_public_manifest(args.manifest, expected_events=15)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Joint blind prediction refused: {exc}") from exc

    tasks = []
    for row in rows:
        workbook = (args.manifest.parent / row["workbook"]).resolve()
        tasks.append((str(workbook), row["instance_id"], row["workbook"], variant, 15))
    workers = max(1, min(args.workers or min(24, os.cpu_count() or 1), len(tasks)))
    print(f"[scheduler] independent_workbooks=15 workers={workers}", flush=True)
    ranking_rows = []
    decision_rows = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_predict, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            instance_id, rankings, decision = future.result()
            ranking_rows.extend(rankings)
            decision_rows.append(decision)
            print(f"[{index}/15] {instance_id} :: v4 + v5.2-{variant}", flush=True)
    order = {row["instance_id"]: index for index, row in enumerate(rows)}
    ranking_rows.sort(key=lambda row: (order[str(row["instance_id"])], int(row["rank"])))
    decision_rows.sort(key=lambda row: order[str(row["instance_id"])])
    if any(row["v4_order_sha256"] != row["v52_core_order_sha256"] for row in decision_rows):
        raise SystemExit("V5.2 core differs from V4; lock refused")

    args.output.mkdir(parents=True, exist_ok=True)
    rankings_path = args.output / "v4_full_rankings.csv"
    decisions_path = args.output / "v52_decisions.csv"
    _write_csv(rankings_path, ranking_rows)
    _write_csv(decisions_path, decision_rows)
    source_paths = [
        root / "formulaguard/v52.py",
        root / "formulaguard/localize.py",
        root / "scripts/run_v4_v52_blind_lock.py",
        root / "scripts/score_v4_v52_blind.py",
        root / "scripts/v52_blind_protocol.py",
    ]
    metadata = {
        "protocol": "joint_label_free_v4_v52_prediction_then_sha256_lock",
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "events": 15,
        "worker_processes": workers,
        "scheduler_unit": "one_label_free_workbook_joint_prediction",
        "candidate_limit": 15,
        "selected_variant": variant,
        "v4_config_sha256": sha256_file(args.v4_config),
        "v52_config_sha256": sha256_file(args.v52_config),
        "git_commit": _git_head(root),
        "workbook_sha256": workbook_hashes,
        "source_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): sha256_file(path)
            for path in source_paths if path.is_file()
        },
        "label_inputs": [],
        "label_access_policy": "only_exact_public_manifest_columns_and_public_xlsx_paths_are_accepted",
        "forbidden_label_fields": sorted(FORBIDDEN_LABEL_FIELDS),
        "core_non_interference_verified": True,
    }
    metadata_path = args.output / "joint_prediction_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    lock = {
        "lock_version": 2,
        "files": {
            "v4_rankings": {"file": rankings_path.name, "sha256": sha256_file(rankings_path)},
            "v52_decisions": {"file": decisions_path.name, "sha256": sha256_file(decisions_path)},
            "metadata": {"file": metadata_path.name, "sha256": sha256_file(metadata_path)},
        },
        "instruction": "Do not reveal labels or edit locked files before this lock succeeds.",
    }
    lock_path = args.output / "prediction_lock.json"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    print(lock_path)


if __name__ == "__main__":
    main()
