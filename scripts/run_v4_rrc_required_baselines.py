"""Run the remaining preregistered V4-RRC baselines on Gate 2 inputs."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.localize import LocalizationResult
from formulaguard.v5_psl import diagnose_v5_psl
from formulaguard.v52 import v52_from_v4
from formulaguard.workbook import WorkbookModel
from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    DEFAULT_V4,
    load_event_rows,
    load_json,
    load_shards,
    reject_protected,
    relative,
    sha256,
    source_rank,
    stable_hash,
)

PROTOCOL = "formulaguard_v4_rrc_required_baselines_v1"
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_OUTPUT = ROOT / "results/v4_rrc_required_baselines"
DEFAULT_WORKERS = 24


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def read_profiles(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"unit_id", "path", "workbook_sha256", "structure_cluster_id"}
    if not rows or required - set(rows[0]):
        raise ValueError("observation profiles have an unexpected schema")
    result = {}
    for row in rows:
        unit_id = row["unit_id"]
        if unit_id in result:
            raise ValueError(f"duplicate observation unit: {unit_id}")
        workbook = (ROOT / row["path"]).resolve()
        reject_protected(workbook)
        if not workbook.is_relative_to(ROOT):
            raise ValueError(f"workbook path escapes repository: {row['path']}")
        result[unit_id] = row
    return result


def localization_rows(payload: Sequence[Mapping[str, object]]) -> list[LocalizationResult]:
    results = []
    for expected_rank, row in enumerate(payload, start=1):
        if int(row["rank"]) != expected_rank:
            raise ValueError("V4 payload is not in complete rank order")
        sheet, address = str(row["cell"]).rsplit("!", 1)
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError("V4 ranking row lacks evidence")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        results.append(LocalizationResult(
            cell=(sheet, address),
            score=float(row["score"]),
            candidate_formula=(
                str(row["candidate_formula"]) if row.get("candidate_formula") else None
            ),
            evidence=dict(evidence),
        ))
    return results


def predict_one(task: tuple[str, str, str, str, str]) -> dict[str, object]:
    unit_id, workbook_text, expected_sha, v4_shard_text, output_text = task
    workbook = Path(workbook_text)
    output = Path(output_text)
    if sha256(workbook) != expected_sha:
        raise ValueError(f"workbook changed before baseline run: {unit_id}")
    v4_payload = load_json(Path(v4_shard_text))
    if v4_payload.get("unit_id") != unit_id or v4_payload.get("label_inputs") != []:
        raise ValueError(f"invalid frozen V4 shard: {unit_id}")
    model = WorkbookModel.from_xlsx(workbook)
    v4 = localization_rows(v4_payload["ranking"])
    if len(v4) != len(model.formulas):
        raise ValueError(f"V4 formula inventory differs from workbook: {unit_id}")
    review = v52_from_v4(model, v4, variant="b", candidate_limit=15)
    static = diagnose_v5_psl(model, ablation="no_perturbation")
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "unit_id": unit_id,
        "workbook_sha256": expected_sha,
        "formula_count": len(model.formulas),
        "v4_2_review_b": {
            "review_cells": [row.cell_label for row in review.review_set],
            "review_cost": len(review.review_set),
            "additional_action": int(review.rescue is not None),
            "status": review.status,
            "reason": review.reason,
            "rescue_cell": review.rescue.result.cell_label if review.rescue else None,
        },
        "v5_psl_static_anchor": {
            "ranking": [row.cell_label for row in static.ranking],
            "review_cells": [f"{sheet}!{address}" for sheet, address in static.review_cells],
            "state": static.state.value,
            "reason_codes": list(static.reason_codes),
        },
        "label_inputs": [],
        "protected_data_inputs": [],
    }
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if output.exists():
        if output.read_bytes() != encoded:
            raise ValueError(f"completed baseline shard differs: {unit_id}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".json.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, output)
    return payload


def _macro(rows: Sequence[Mapping[str, object]], field: str) -> float | None:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["case_kind"] != "error":
            continue
        groups[str(row["structure_group"])].append(float(row[field]))
    if not groups:
        return None
    return sum(sum(values) / len(values) for values in groups.values()) / len(groups)


def score(
    events: Sequence[Mapping[str, object]],
    predictions: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows = []
    for event in events:
        unit_id = str(event["unit_id"])
        prediction = predictions[unit_id]
        sources = [str(cell) for cell in event["source_formula_cells"]]
        v4_rank = int(event["metrics"]["v4"]["rank"]) if event["metrics"]["v4"]["rank"] else None
        v4_top5 = int(v4_rank is not None and v4_rank <= 5)
        review = prediction["v4_2_review_b"]
        review_hit = int(bool(set(sources) & set(review["review_cells"])))
        static = prediction["v5_psl_static_anchor"]
        static_rank = source_rank(static["ranking"], sources)
        rows.append({
            "event_id": event["event_id"],
            "unit_id": unit_id,
            "structure_group": event["structure_group"],
            "cohort": event["cohort"],
            "case_kind": event["case_kind"],
            "v4_top5": v4_top5,
            "v4_2_review_hit": review_hit,
            "v4_2_review_cost": review["review_cost"],
            "v4_2_additional_action": review["additional_action"],
            "static_source_rank": static_rank,
            "static_top5": int(static_rank is not None and static_rank <= 5),
        })
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    control_units = {str(row["unit_id"]) for row in controls}
    v42_control_actions = {
        str(row["unit_id"]) for row in controls if row["v4_2_additional_action"]
    }
    cohorts = {}
    for cohort in sorted({str(row["cohort"]) for row in errors}):
        selected = [row for row in errors if row["cohort"] == cohort]
        cohorts[cohort] = {
            "events": len(selected),
            "groups": len({str(row["structure_group"]) for row in selected}),
            "v4_top5": _macro(selected, "v4_top5"),
            "v4_2_native_review_hit": _macro(selected, "v4_2_review_hit"),
            "static_anchor_top5": _macro(selected, "static_top5"),
        }
    static_mrr_rows = [
        {**row, "static_mrr": 1.0 / row["static_source_rank"] if row["static_source_rank"] else 0.0}
        for row in errors
    ]
    summary = {
        "events": len(rows),
        "errors": len(errors),
        "controls": len(controls),
        "v4_top5": _macro(errors, "v4_top5"),
        "v4_2_review_b": {
            "native_review_hit": _macro(errors, "v4_2_review_hit"),
            "mean_review_cost_per_event": sum(float(row["v4_2_review_cost"]) for row in rows) / len(rows),
            "additional_action_units": len({
                str(row["unit_id"]) for row in rows if row["v4_2_additional_action"]
            }),
            "control_additional_action_rate": (
                len(v42_control_actions) / len(control_units) if control_units else None
            ),
            "metric_note": "native five-plus-optional-sixth review hit; not Top-5",
        },
        "v5_psl_static_anchor": {
            "top5": _macro(errors, "static_top5"),
            "mrr": _macro(static_mrr_rows, "static_mrr"),
        },
        "by_cohort": cohorts,
    }
    return summary, rows


def write_immutable(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"completed baseline output differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def run(
    *, profiles_path: Path, events_path: Path, v4_dir: Path,
    output_dir: Path, workers: int,
) -> Path:
    for path in (profiles_path, events_path, v4_dir, output_dir):
        reject_protected(path)
    profiles = read_profiles(profiles_path)
    events = load_event_rows(events_path)
    v4, v4_complete = load_shards(v4_dir, kind="V4")
    if set(profiles) != set(v4):
        raise ValueError("profile and V4 unit inventories differ")
    shard_paths = {
        str(load_json(path)["unit_id"]): path
        for path in sorted((v4_dir / "shards").glob("*.json"))
    }
    tasks = []
    for unit_id in sorted(profiles):
        profile = profiles[unit_id]
        workbook = (ROOT / profile["path"]).resolve()
        output = output_dir / "shards" / (unit_id.split(":", 1)[1] + ".json")
        tasks.append((unit_id, str(workbook), profile["workbook_sha256"], str(shard_paths[unit_id]), str(output)))
    predictions: dict[str, dict[str, object]] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        futures = {executor.submit(predict_one, task): task[0] for task in tasks}
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            payload = future.result()
            predictions[str(payload["unit_id"])] = payload
            if index % 20 == 0 or index == len(tasks):
                print(f"V4-RRC baselines {index}/{len(tasks)}", flush=True)
    summary, event_rows = score(events, predictions)
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(event_rows, key=lambda row: str(row["event_id"]))
    ).encode("utf-8")
    write_immutable(output_dir / "event_scores.jsonl", event_bytes)
    shard_hash = hashlib.sha256()
    for path in sorted((output_dir / "shards").glob("*.json")):
        shard_hash.update(path.name.encode("utf-8") + b"\0" + bytes.fromhex(sha256(path)))
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "git_commit": git_commit(),
        "workers": workers,
        "inputs": {
            "profiles": {"path": relative(profiles_path), "sha256": sha256(profiles_path)},
            "events": {"path": relative(events_path), "sha256": sha256(events_path)},
            "v4": {"path": relative(v4_dir), "combined_shards_sha256": v4_complete["combined_shards_sha256"]},
        },
        "counts": {"units": len(predictions), "events": len(events), "shards": len(predictions)},
        "summary": summary,
        "artifacts": {
            "event_scores": {"path": relative(output_dir / "event_scores.jsonl"), "sha256": hashlib.sha256(event_bytes).hexdigest()},
            "combined_shards_sha256": shard_hash.hexdigest(),
        },
        "label_boundary": {
            "prediction_label_inputs": [],
            "labels_read_only_by_scorer": True,
        },
        "protected_data_inputs": [],
    }
    payload["receipt_sha256"] = stable_hash(payload)
    receipt = output_dir / "receipt.json"
    write_immutable(receipt, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args(argv)
    receipt = run(
        profiles_path=args.profiles.resolve(),
        events_path=args.events.resolve(),
        v4_dir=args.v4.resolve(),
        output_dir=args.output_dir.resolve(),
        workers=args.workers,
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
