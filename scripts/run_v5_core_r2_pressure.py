"""Retrospective pressure test for V5-Core R2 / R2-R1.

This runner is deliberately restricted to data whose labels were already
revealed before the run.  It is not a blind-validation or model-selection
tool.  Its purpose is to check whether a development correction that improved
controlled synthetic data causes a safety regression on two historical,
heterogeneous cohorts: the 100-case V4/V5.2 set and the fixed Enron inventory.

The R2 adapter mirrors the bounded-parser policy used by the historical
V5-Core Enron evaluation: unsupported formulas retain their cached workbook
values and are appended to the complete ranking without repair evidence.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import parse_formula
from formulaguard.localize import LocalizationResult, v4_scores
from formulaguard.v5_core_r2 import v5_core_r2_scores
from formulaguard.workbook import WorkbookModel


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sources(text: str) -> set[tuple[str, str]]:
    sources: set[tuple[str, str]] = set()
    for value in str(text or "").split(";"):
        value = value.strip()
        if "!" not in value:
            continue
        sheet, address = value.rsplit("!", 1)
        sources.add((sheet.strip("'"), address.replace("$", "").upper()))
    return sources


def supported_model(model: WorkbookModel) -> tuple[WorkbookModel, tuple[tuple[str, str], ...]]:
    supported: dict[tuple[str, str], str] = {}
    unsupported: list[tuple[str, str]] = []
    for cell, formula in model.formulas.items():
        try:
            parse_formula(formula)
        except Exception:
            unsupported.append(cell)
        else:
            supported[cell] = formula
    return WorkbookModel(model.cells, supported, source=model.source), tuple(sorted(unsupported))


def compatible_r2_scores(
    model: WorkbookModel,
    *,
    config: dict[str, object],
    stage: str,
) -> tuple[list[LocalizationResult], tuple[tuple[str, str], ...]]:
    compatible, unsupported = supported_model(model)
    ranked = v5_core_r2_scores(compatible, stage=stage, config=config) if compatible.formulas else []
    for cell in unsupported:
        ranked.append(LocalizationResult(
            cell=cell,
            score=0.0,
            candidate_formula=None,
            evidence={
                "model_version": str(config.get("model_version", "v5-core-r2")),
                "compatibility_adapter": "cached_value_no_candidate_complete_ranking_tail",
                "evidence_tier": "unsupported_no_candidate",
            },
        ))
    return ranked, unsupported


def ranking_rows(values: list[LocalizationResult]) -> list[dict[str, object]]:
    return [
        {
            "rank": rank,
            "cell": item.cell_label,
            "candidate_formula": item.candidate_formula or "",
            "status": str(item.evidence.get("diagnostic_status", "")),
        }
        for rank, item in enumerate(values, 1)
    ]


def run_workbook(payload: tuple[str, str, dict[str, object], str]) -> str:
    root_text, relative, config, shard_text = payload
    root, shard = Path(root_text), Path(shard_text)
    path = root / relative
    model = WorkbookModel.from_xlsx(path)
    source, unsupported = compatible_r2_scores(model, config=config, stage="source")
    full, second_unsupported = compatible_r2_scores(model, config=config, stage="full")
    if unsupported != second_unsupported:
        raise RuntimeError(f"Parser-supported subset changed between R2 stages: {relative}")
    record = {
        "workbook": relative,
        "sha256": sha256(path),
        "formula_count": len(model.formulas),
        "unsupported_formula_count": len(unsupported),
        "rankings": {
            "v4": ranking_rows(v4_scores(model, candidate_limit=15)),
            "r2_source": ranking_rows(source),
            "r2_full": ranking_rows(full),
        },
    }
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return relative


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True,
                        help="CSV with instance_id, workbook when available, and source_cells/source_cell columns.")
    parser.add_argument("--workbook-manifest", type=Path,
                        help="Optional public instance_id,workbook mapping when revealed event rows omit workbook.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    events = read_rows(args.events)
    required = {"instance_id"}
    missing = required - set(events[0] if events else {})
    if missing:
        raise SystemExit(f"Events CSV missing required columns: {', '.join(sorted(missing))}")
    if args.workbook_manifest:
        manifest_rows = read_rows(args.workbook_manifest)
        mapping = {row["instance_id"]: row["workbook"] for row in manifest_rows}
        if len(mapping) != len(manifest_rows) or any(not value for value in mapping.values()):
            raise SystemExit("Workbook manifest must have one non-empty workbook per instance_id")
        for row in events:
            if not row.get("workbook"):
                row["workbook"] = mapping.get(row["instance_id"], "")
    if any(not row.get("workbook") for row in events):
        raise SystemExit("Every event must provide workbook directly or through --workbook-manifest")
    if not any("source_cells" in row or "source_cell" in row for row in events):
        raise SystemExit("Events CSV needs source_cells or source_cell")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    workbooks = sorted({row["workbook"] for row in events})
    args.output.mkdir(parents=True, exist_ok=True)
    shard_root = args.output / "shards"
    shard_root.mkdir(exist_ok=True)
    metadata = {
        "protocol": "v5_core_r2_revealed_retrospective_pressure_v1",
        "retrospective_only": True,
        "not_for_model_selection": True,
        "events": len(events),
        "workbooks": len(workbooks),
        "workers_requested": args.workers,
        "events_sha256": sha256(args.events),
        "workbook_manifest_sha256": sha256(args.workbook_manifest) if args.workbook_manifest else None,
        "config_sha256": sha256(args.config),
        "model_source_sha256": sha256(ROOT / "formulaguard" / "v5_core_r2.py"),
    }
    metadata_path = args.output / "metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("Pressure-test resume refused: inputs or configuration changed")
        if not args.resume:
            raise SystemExit("Output exists; pass --resume to verify and continue")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    shards: dict[str, Path] = {}
    pending: list[tuple[str, str, dict[str, object], str]] = []
    for index, relative in enumerate(workbooks):
        shard = shard_root / f"workbook_{index:03d}.json"
        shards[relative] = shard
        if shard.exists():
            record = json.loads(shard.read_text(encoding="utf-8"))
            if record.get("sha256") != sha256(args.root / relative):
                raise SystemExit(f"Workbook changed since shard creation: {relative}")
        else:
            pending.append((str(args.root), relative, config, str(shard)))
    workers = min(max(1, args.workers), max(1, len(pending)))
    print(f"R2 pressure-test scheduling: {workers} workers; {len(pending)} pending workbooks.", flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_workbook, payload) for payload in pending]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            print(f"[{index}/{len(futures)}] {future.result()}", flush=True)

    records = {relative: json.loads(path.read_text(encoding="utf-8")) for relative, path in shards.items()}
    raw: list[dict[str, object]] = []
    for event in events:
        record = records[event["workbook"]]
        sources = parse_sources(event.get("source_cells") or event.get("source_cell") or "")
        if not sources:
            raise SystemExit(f"No valid source cells in event {event['instance_id']}")
        for method, ranking in record["rankings"].items():
            ranks = [int(row["rank"]) for row in ranking if tuple(str(row["cell"]).rsplit("!", 1)) in sources]
            rank = min(ranks) if ranks else len(ranking) + 1
            raw.append({
                "instance_id": event["instance_id"], "workbook": event["workbook"],
                "error_type": event.get("error_type", ""), "method": method,
                "rank": rank, "top1": int(rank == 1), "top3": int(rank <= 3),
                "top5": int(rank <= 5), "mrr": 1 / rank,
                "exam": (rank - 1) / max(1, int(record["formula_count"])),
            })
    write_csv(args.output / "event_ranks.csv", raw, list(raw[0]))
    summary: dict[str, dict[str, float | int]] = {}
    for method in sorted({str(row["method"]) for row in raw}):
        rows = [row for row in raw if row["method"] == method]
        summary[method] = {
            "events": len(rows),
            "top1": statistics.fmean(int(row["top1"]) for row in rows),
            "top3": statistics.fmean(int(row["top3"]) for row in rows),
            "top5": statistics.fmean(int(row["top5"]) for row in rows),
            "mrr": statistics.fmean(float(row["mrr"]) for row in rows),
            "exam": statistics.fmean(float(row["exam"]) for row in rows),
        }
    paired: dict[str, dict[str, int | float]] = {}
    v4_ranks = {str(row["instance_id"]): int(row["rank"]) for row in raw if row["method"] == "v4"}
    for method in ("r2_source", "r2_full"):
        ranks = {str(row["instance_id"]): int(row["rank"]) for row in raw if row["method"] == method}
        deltas = [v4_ranks[key] - ranks[key] for key in sorted(v4_ranks)]
        paired[method] = {
            "improved_events": sum(value > 0 for value in deltas),
            "harmed_events": sum(value < 0 for value in deltas),
            "unchanged_events": sum(value == 0 for value in deltas),
            "mean_rank_gain": statistics.fmean(deltas),
        }
    report = {
        **metadata,
        "summary": summary,
        "paired_vs_v4": paired,
        "r2_full_mrr_not_below_v4_by_more_than_001": summary["r2_full"]["mrr"] + 0.01 >= summary["v4"]["mrr"],
        "compatibility_policy": "parser-supported formulas use R2 unchanged; unsupported formulas append at ranking tail",
    }
    output = args.output / "pressure_summary.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
