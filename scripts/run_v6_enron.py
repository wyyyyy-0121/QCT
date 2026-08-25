"""Resumable V4/V6 retrospective evaluation on the fixed Enron test events."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ENRON_MANIFEST = ROOT / "data/external/enron/manifest.csv"
EXPECTED_RETROSPECTIVE_EVENTS = 30

from formulaguard.localize import v4_scores
from formulaguard.v6 import v6_prepared_v4_scores, v6_scores
from formulaguard.workbook import WorkbookModel


def sha256(path: Path):
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


def parse_sources(text: str):
    cells = []
    for value in text.split(";"):
        if "!" in value:
            sheet, address = value.rsplit("!", 1)
            cells.append((sheet.strip("'"), address.replace("$", "").upper()))
    return cells


def included_events(manifest: Path) -> list[dict[str, str]]:
    """Return every evaluation-ready Enron event in the selected inventory."""
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("include", "1") == "1"]


def task(payload):
    root_text, relative, variant, shard_text = payload
    root, shard = Path(root_text), Path(shard_text)
    path = root / relative
    model = WorkbookModel.from_xlsx(path)
    rankings = {}
    v6 = v6_scores(model, variant=variant)
    base = v6_prepared_v4_scores(model, candidate_limit=15)
    for method, results in (("v4", base), (f"v6_{variant}", v6)):
        rankings[method] = [
            {
                "rank": rank,
                "cell": result.cell_label,
                "candidate_formula": result.candidate_formula or "",
                "promotion_target": result.evidence.get("promotion_target", 0),
            }
            for rank, result in enumerate(results, 1)
        ]
    record = {
        "workbook": relative,
        "sha256": sha256(path),
        "formula_count": len(model.formulas),
        "rankings": rankings,
    }
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return relative


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/external/enron"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_ENRON_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=("a", "b", "c"), required=True)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    events = included_events(args.manifest)
    if args.manifest.resolve() == DEFAULT_ENRON_MANIFEST.resolve() and len(events) != EXPECTED_RETROSPECTIVE_EVENTS:
        raise SystemExit(
            "Default V6 Enron inventory must contain exactly "
            f"{EXPECTED_RETROSPECTIVE_EVENTS} evaluation-ready events; found {len(events)}"
        )
    workbooks = sorted({row["workbook"] for row in events})
    args.output.mkdir(parents=True, exist_ok=True)
    shard_dir = args.output / "shards"
    shard_dir.mkdir(exist_ok=True)
    metadata = {
        "protocol": "v6_enron_retrospective_only",
        "variant": args.variant,
        "manifest_sha256": sha256(args.manifest),
        "events": len(events),
        "workbooks": len(workbooks),
        "event_inventory": "all_evaluation_ready_events",
        "expected_default_events": EXPECTED_RETROSPECTIVE_EVENTS,
        "retrospective_only": True,
        "v6_source_sha256": sha256(ROOT / "formulaguard/v6.py"),
        "v4_source_sha256": sha256(ROOT / "formulaguard/localize.py"),
        "method_spec_sha256": sha256(ROOT / "research/V6_METHOD_SPEC.md"),
        "git_commit": git_commit(),
        "workers_requested": args.workers,
    }
    metadata_path = args.output / "enron_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("Enron resume refused: metadata changed")
        if not args.resume:
            raise SystemExit("Enron output exists; pass --resume")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    pending = []
    lookup = {}
    for index, relative in enumerate(workbooks):
        shard = shard_dir / f"workbook_{index:03d}.json"
        lookup[relative] = shard
        if shard.exists():
            record = json.loads(shard.read_text(encoding="utf-8"))
            if record["sha256"] != sha256(args.root / relative):
                raise SystemExit(f"Enron resume refused: workbook changed: {relative}")
        else:
            pending.append((str(args.root), relative, args.variant, str(shard)))
    workers = min(args.workers, max(1, len(pending)))
    print(f"V6 Enron scheduling: {workers} workers; {len(pending)} pending.", flush=True)
    if workers == 1:
        evaluated = map(task, pending)
        for index, relative in enumerate(evaluated, 1):
            print(f"[{index}/{len(pending)}] {relative}", flush=True)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            for index, relative in enumerate(executor.map(task, pending, chunksize=1), 1):
                print(f"[{index}/{len(pending)}] {relative}", flush=True)
    records = {relative: json.loads(path.read_text(encoding="utf-8")) for relative, path in lookup.items()}
    if set(records) != set(workbooks):
        raise SystemExit("Enron merge refused: workbook shard set is incomplete")
    for relative, record in records.items():
        expected_methods = {"v4", f"v6_{args.variant}"}
        if record.get("workbook") != relative or set(record.get("rankings", {})) != expected_methods:
            raise SystemExit(f"Enron completion audit failed: {relative}")
        formula_count = record.get("formula_count")
        cell_sets = []
        for method in expected_methods:
            ranking = record["rankings"][method]
            cells = [row.get("cell") for row in ranking]
            if (
                not isinstance(formula_count, int) or formula_count < 1
                or len(ranking) != formula_count or len(set(cells)) != formula_count
                or [row.get("rank") for row in ranking] != list(range(1, formula_count + 1))
            ):
                raise SystemExit(f"Enron full-ranking audit failed: {relative} {method}")
            cell_sets.append(set(cells))
        if cell_sets[0] != cell_sets[1]:
            raise SystemExit(f"Enron V4/V6 formula-cell sets differ: {relative}")
    (args.output / "enron_prediction_complete.json").write_text(json.dumps({
        "complete": True,
        "workbooks": len(workbooks),
        "events": len(events),
        "full_ranking_audit_passed": True,
        "metadata_sha256": sha256(metadata_path),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    raw = []
    for event in events:
        record = records[event["workbook"]]
        sources = set(parse_sources(event.get("source_cells") or event.get("source_cell", "")))
        for method, ranking in record["rankings"].items():
            ranks = [row["rank"] for row in ranking if tuple(row["cell"].rsplit("!", 1)) in sources]
            rank = min(ranks) if ranks else len(ranking) + 1
            raw.append({
                "instance_id": event["instance_id"],
                "method": method,
                "formula_count": record["formula_count"],
                "rank": rank,
                "top5": int(rank <= 5),
                "mrr": 1 / rank,
                "exam": rank / max(1, record["formula_count"]),
            })
    with (args.output / "enron_raw.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0]))
        writer.writeheader(); writer.writerows(raw)
    summary = {}
    for method in sorted({row["method"] for row in raw}):
        rows = [row for row in raw if row["method"] == method]
        summary[method] = {
            "events": len(rows),
            "top5": statistics.fmean(row["top5"] for row in rows),
            "mrr": statistics.fmean(row["mrr"] for row in rows),
            "exam": statistics.fmean(row["exam"] for row in rows),
        }
    payload = {"retrospective_only": True, "summary": summary, "v6_mrr_not_below_v4": summary[f"v6_{args.variant}"]["mrr"] >= summary["v4"]["mrr"]}
    (args.output / "enron_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "enron_summary.json")


if __name__ == "__main__":
    main()
