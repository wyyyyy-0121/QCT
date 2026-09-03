"""Reproduce the post-EORL source-to-formula-descendant coverage diagnosis."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.eorl import (
    parse_cell_label,
    source_formula_descendants,
)
from formulaguard.workbook import WorkbookModel
from scripts.audit_eorl_d0 import (
    DEFAULT_MANIFEST,
    EXPECTED_MANIFEST_SHA256,
    _git_commit,
    _read_manifest,
    _reject_protected,
    _require_clean_tracked_worktree,
    _write_immutable,
)
from scripts.run_model_discovery_signals import sha256, stable_hash

PROTOCOL = "formulaguard_eorl_topology_followup_v1"
DEFAULT_OUTPUT = ROOT / "results/eorl_d0/topology_followup_receipt.json"


def _parse_sources(value: str) -> list[tuple[str, str]]:
    return [
        parse_cell_label(item.strip())
        for item in value.replace("|", ";").split(";")
        if item.strip()
    ]


def _worker(payload: Mapping[str, object]) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(Path(str(payload["workbook_path"])))
    topology = source_formula_descendants(
        model,
        [parse_cell_label(str(item)) for item in payload["source_cells"]],  # type: ignore[union-attr]
    )
    return {
        "event_id": payload["event_id"],
        "corpus_id": payload["corpus_id"],
        "source_formula_count": topology["source_formula_count"],
        "sources_with_formula_descendants": topology["sources_with_formula_descendants"],
        "formula_descendant_count": topology["formula_descendant_count"],
        "has_formula_descendant": int(topology["formula_descendant_count"]) > 0,
    }


def run(*, manifest_path: Path, output_path: Path, workers: int) -> Path:
    _reject_protected(manifest_path)
    _reject_protected(output_path)
    _require_clean_tracked_worktree()
    if sha256(manifest_path) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("frozen EORL manifest hash mismatch")

    rows = [row for row in _read_manifest(manifest_path) if row["case_kind"] == "error"]
    payloads: list[dict[str, object]] = []
    for row in rows:
        workbook_path = (manifest_path.parent / row["workbook"]).resolve()
        _reject_protected(workbook_path)
        payloads.append({
            "event_id": row["instance_id"],
            "corpus_id": row["corpus_id"],
            "workbook_path": str(workbook_path),
            "source_cells": [f"{sheet}!{address}" for sheet, address in _parse_sources(row["source_cells"])],
        })

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        events = list(executor.map(_worker, payloads))
    events.sort(key=lambda row: str(row["event_id"]))

    cohorts: dict[str, dict[str, int]] = {}
    for corpus_id in sorted({str(row["corpus_id"]) for row in events}):
        selected = [row for row in events if row["corpus_id"] == corpus_id]
        with_descendants = sum(row["has_formula_descendant"] is True for row in selected)
        cohorts[corpus_id] = {
            "error_events": len(selected),
            "with_formula_descendants": with_descendants,
            "without_formula_descendants": len(selected) - with_descendants,
        }
    with_descendants = sum(row["has_formula_descendant"] is True for row in events)
    receipt: dict[str, object] = {
        "protocol": PROTOCOL,
        "status": "posthoc_topology_diagnosis_only",
        "git_commit": _git_commit(),
        "workers_requested": workers,
        "input": {
            "manifest_path": manifest_path.relative_to(ROOT).as_posix(),
            "manifest_sha256": sha256(manifest_path),
        },
        "summary": {
            "error_events": len(events),
            "with_formula_descendants": with_descendants,
            "without_formula_descendants": len(events) - with_descendants,
            "corpus_counts": dict(sorted(Counter(str(row["corpus_id"]) for row in events).items())),
        },
        "cohorts": cohorts,
        "events": events,
        "interpretation_limits": {
            "model_selection_authorized": False,
            "eorl_failure_reversed": False,
            "localization_accuracy_measured": False,
        },
        "protected_data_inputs": [],
    }
    receipt["receipt_sha256"] = stable_hash(receipt)
    _write_immutable(
        output_path,
        (json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args(argv)
    if args.workers < 1 or args.workers > 24:
        raise SystemExit("EORL topology workers must be between 1 and 24")
    try:
        print(run(
            manifest_path=args.manifest.resolve(),
            output_path=args.output.resolve(),
            workers=args.workers,
        ))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"EORL topology audit refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
