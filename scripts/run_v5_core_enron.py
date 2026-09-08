"""Retrospective V4/V5-Core safety evaluation on the fixed Enron events."""

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
from formulaguard.v5_core import v5_core_scores
from formulaguard.workbook import WorkbookModel


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sources(text: str) -> set[tuple[str, str]]:
    result = set()
    for value in text.split(";"):
        if "!" in value:
            sheet, address = value.rsplit("!", 1)
            result.add((sheet.strip("'"), address.replace("$", "").upper()))
    return result


def compatible_v5_core_scores(model: WorkbookModel, *, head: str, config: dict):
    """Run V5-Core on its declared syntax subset without dropping formulas.

    The historical Enron corpus contains external-workbook links, named ranges,
    array formulas, and functions outside the bounded FormulaGuard parser.  The
    frozen V5-Core model is intentionally not changed after its development
    predictions.  For this retrospective adapter, unsupported formulas retain
    their cached workbook values, receive no repair evidence, and remain at the
    end of the complete ranking.  Every parser-supported formula still follows
    the exact V5-Core code path used by the controlled experiments.
    """
    supported = {}
    unsupported = []
    for cell, formula in model.formulas.items():
        try:
            parse_formula(formula)
        except Exception:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
            unsupported.append(cell)
        else:
            supported[cell] = formula
    compatible_model = WorkbookModel(model.cells, supported, source=model.source)
    ranked = v5_core_scores(compatible_model, head=head, config=config) if supported else []
    for cell in sorted(unsupported):
        ranked.append(LocalizationResult(
            cell=cell,
            score=0.0,
            candidate_formula=None,
            evidence={
                "model_version": "v5-core-dev-r2",
                "head": head,
                "regime_type": "unsupported_external_syntax",
                "candidate_formula": "",
                "candidate_portfolio_size": 0,
                "evidence_tier": "unsupported_no_candidate",
                "compatibility_adapter": "enron_cached_value_and_complete_ranking",
            },
        ))
    return ranked, tuple(sorted(unsupported))


def task(payload):
    root_text, relative, rule_config, learned_config, shard_text = payload
    root, shard = Path(root_text), Path(shard_text)
    path = root / relative
    model = WorkbookModel.from_xlsx(path)
    rankings = {}
    rule_values, unsupported = compatible_v5_core_scores(model, head="rule", config=rule_config)
    learned_values, learned_unsupported = compatible_v5_core_scores(model, head="learned", config=learned_config)
    if unsupported != learned_unsupported:
        raise RuntimeError("Rule and learned compatibility subsets differ")
    methods = (
        ("v4", v4_scores(model, candidate_limit=15)),
        ("v5_rule", rule_values),
        ("v5_learned", learned_values),
    )
    for method, values in methods:
        rankings[method] = [
            {"rank": rank, "cell": item.cell_label, "candidate_formula": item.candidate_formula or ""}
            for rank, item in enumerate(values, 1)
        ]
    record = {
        "workbook": relative,
        "sha256": sha256(path),
        "formula_count": len(model.formulas),
        "unsupported_formula_count": len(unsupported),
        "unsupported_formula_cells": [f"{sheet}!{address}" for sheet, address in unsupported],
        "rankings": rankings,
    }
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return relative


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/external/enron"))
    parser.add_argument("--manifest", type=Path, default=Path("data/external/enron/manifest.csv"))
    parser.add_argument("--rule-config", type=Path, required=True)
    parser.add_argument("--learned-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_enron"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rule_config = json.loads(args.rule_config.read_text(encoding="utf-8"))
    learned_config = json.loads(args.learned_config.read_text(encoding="utf-8"))
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        events = [row for row in csv.DictReader(handle) if row.get("include", "1") == "1"]
    if len(events) != 30:
        raise SystemExit(f"The fixed Enron retrospective inventory must have 30 events; found {len(events)}")
    workbooks = sorted({row["workbook"] for row in events})
    args.output.mkdir(parents=True, exist_ok=True)
    shard_root = args.output / "shards"
    shard_root.mkdir(exist_ok=True)
    metadata = {
        "protocol": "v5_core_enron_retrospective_only_v1",
        "events": len(events), "workbooks": len(workbooks),
        "manifest_sha256": sha256(args.manifest),
        "rule_config_sha256": sha256(args.rule_config),
        "learned_config_sha256": sha256(args.learned_config),
        "workers_requested": args.workers,
        "retrospective_only": True,
    }
    compatibility_policy = {
        "protocol": "v5_core_enron_unsupported_formula_adapter_v1",
        "policy": "cached_value_no_candidate_complete_ranking_tail",
        "v5_core_source_sha256": sha256(ROOT / "formulaguard/v5_core.py"),
        "adapter_source_sha256": sha256(Path(__file__)),
        "changes_v5_core_source": False,
        "retrospective_only": True,
    }
    policy_path = args.output / "compatibility_policy.json"
    if policy_path.exists():
        if json.loads(policy_path.read_text(encoding="utf-8")) != compatibility_policy:
            raise SystemExit("Enron resume refused: compatibility policy changed")
    else:
        policy_path.write_text(
            json.dumps(compatibility_policy, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    metadata_path = args.output / "enron_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("Enron resume refused: metadata changed")
        if not args.resume:
            raise SystemExit("Output exists; pass --resume")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    lookup = {}
    pending = []
    for index, relative in enumerate(workbooks):
        shard = shard_root / f"workbook_{index:03d}.json"
        lookup[relative] = shard
        if shard.exists():
            record = json.loads(shard.read_text(encoding="utf-8"))
            if record["sha256"] != sha256(args.root / relative):
                raise SystemExit(f"Workbook changed: {relative}")
        else:
            pending.append((str(args.root), relative, rule_config, learned_config, str(shard)))
    workers = min(args.workers, max(1, len(pending)))
    print(f"V5-Core Enron scheduling: {workers} workers; {len(pending)} pending.", flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(task, item) for item in pending]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            print(f"[{index}/{len(futures)}] {future.result()}", flush=True)
    records = {relative: json.loads(path.read_text(encoding="utf-8")) for relative, path in lookup.items()}
    raw = []
    for event in events:
        record = records[event["workbook"]]
        sources = parse_sources(event.get("source_cells") or event.get("source_cell", ""))
        for method, ranking in record["rankings"].items():
            ranks = [row["rank"] for row in ranking if tuple(row["cell"].rsplit("!", 1)) in sources]
            rank = min(ranks) if ranks else len(ranking) + 1
            raw.append({
                "instance_id": event["instance_id"], "method": method,
                "rank": rank, "top5": int(rank <= 5), "mrr": 1 / rank,
                "exam": (rank - 1) / max(1, record["formula_count"]),
            })
    with (args.output / "enron_raw.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0])); writer.writeheader(); writer.writerows(raw)
    summary = {}
    for method in sorted({row["method"] for row in raw}):
        rows = [row for row in raw if row["method"] == method]
        summary[method] = {
            "events": len(rows),
            "top5": statistics.fmean(row["top5"] for row in rows),
            "mrr": statistics.fmean(row["mrr"] for row in rows),
            "exam": statistics.fmean(row["exam"] for row in rows),
        }
    payload = {
        "retrospective_only": True,
        "summary": summary,
        "unsupported_formula_policy": compatibility_policy["policy"],
        "unsupported_formula_count": sum(
            int(record.get("unsupported_formula_count", 0)) for record in records.values()
        ),
        "workbooks_with_unsupported_formulas": sum(
            bool(record.get("unsupported_formula_count", 0)) for record in records.values()
        ),
        "rule_mrr_not_below_v4_by_more_than_001": summary["v5_rule"]["mrr"] + 0.01 >= summary["v4"]["mrr"],
        "learned_mrr_not_below_v4_by_more_than_001": summary["v5_learned"]["mrr"] + 0.01 >= summary["v4"]["mrr"],
    }
    output = args.output / "enron_summary.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
