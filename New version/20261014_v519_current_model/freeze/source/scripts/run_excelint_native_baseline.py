"""Run the official ExceLint-core CLI on the locked public Gate 2 inputs."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    load_event_rows,
    reject_protected,
    relative,
    sha256,
    stable_hash,
)
from scripts.run_v4_rrc_required_baselines import read_profiles, write_immutable

PROTOCOL = "formulaguard_excelint_native_baseline_v1"
EXCELINT_REPOSITORY = "https://github.com/plasma-umass/ExceLint-core"
EXCELINT_COMMIT = "b2c5e7df4405a932c82a07e105f275c61fdab6e3"
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_OUTPUT = ROOT / "results/v4_rrc_excelint_native"
DEFAULT_EXCELINT_ROOT = Path("/tmp/qct_gate1/ExceLint-core")
DEFAULT_NODE = ROOT / ".venv/bin/node"
DEFAULT_WORKERS = 24
DEFAULT_TIMEOUT_SECONDS = 300


class OutputSchemaError(ValueError):
    """The official CLI returned JSON outside the pinned native contract."""


def git_commit(directory: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=directory, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def directory_sha256(directory: Path, pattern: str) -> str:
    digest = hashlib.sha256()
    paths = sorted(path for path in directory.rglob(pattern) if path.is_file())
    if not paths:
        raise ValueError(f"no runtime files matched {pattern}: {directory}")
    for path in paths:
        digest.update(str(path.relative_to(directory)).encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def column_name(index: int) -> str:
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise OutputSchemaError("ExceLint column coordinate must be a positive integer")
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def parse_native_output(payload: object) -> list[str]:
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise OutputSchemaError("ExceLint output must contain exactly one workbook")
    sheets = payload[0].get("sheets")
    if not isinstance(sheets, dict):
        raise OutputSchemaError("ExceLint workbook lacks its native sheets map")
    cells: set[str] = set()
    for sheet_name, sheet in sheets.items():
        if not isinstance(sheet_name, str) or not isinstance(sheet, dict):
            raise OutputSchemaError("invalid ExceLint worksheet entry")
        found = sheet.get("foundBugs")
        if not isinstance(found, list):
            raise OutputSchemaError("ExceLint worksheet lacks foundBugs")
        for vector in found:
            if not isinstance(vector, dict):
                raise OutputSchemaError("invalid ExceLint foundBugs vector")
            x, y, c = vector.get("x"), vector.get("y"), vector.get("c")
            if (
                isinstance(y, bool) or not isinstance(y, int) or y < 1
                or isinstance(c, bool) or not isinstance(c, int) or c != 0
            ):
                raise OutputSchemaError("invalid ExceLint foundBugs coordinate")
            cells.add(f"{sheet_name}!{column_name(x)}{y}")
    return sorted(cells)


def runtime_identity(excelint_root: Path, node: Path) -> dict[str, object]:
    reject_protected(excelint_root)
    reject_protected(node)
    cli = excelint_root / "build/src/cli/excelint-cli.js"
    source = excelint_root / "src/cli/excelint-cli.ts"
    package_lock = excelint_root / "package-lock.json"
    for path in (node, cli, source, package_lock):
        if not path.is_file():
            raise FileNotFoundError(path)
    commit = git_commit(excelint_root)
    if commit != EXCELINT_COMMIT:
        raise ValueError(f"ExceLint checkout is not pinned at {EXCELINT_COMMIT}")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=excelint_root, check=True, capture_output=True, text=True,
    ).stdout
    if dirty:
        raise ValueError("ExceLint checkout has modified tracked files")
    node_version = subprocess.run(
        [str(node), "--version"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    return {
        "repository": EXCELINT_REPOSITORY,
        "commit": commit,
        "node_version": node_version,
        "cli_source_sha256": sha256(source),
        "package_lock_sha256": sha256(package_lock),
        "build_javascript_tree_sha256": directory_sha256(excelint_root / "build/src", "*.js"),
        "native_parameters": {
            "formatting_discount_percent": 50,
            "reporting_threshold_percent": 0,
            "minimum_fix_size_cells": 3,
            "maximum_fix_entropy": 1.0,
        },
    }


def predict_one(task: tuple[str, str, str, str, str, int]) -> dict[str, object]:
    unit_id, workbook_text, expected_sha, output_text, runtime_text, timeout_seconds = task
    workbook = Path(workbook_text)
    output = Path(output_text)
    runtime = json.loads(runtime_text)
    reject_protected(workbook)
    reject_protected(output)
    if sha256(workbook) != expected_sha:
        raise ValueError(f"workbook changed before ExceLint run: {unit_id}")

    status = "ok"
    review_cells: list[str] = []
    with tempfile.TemporaryFile(mode="w+b") as raw_output:
        try:
            completed = subprocess.run(
                [runtime["node"], runtime["cli"], "--input", str(workbook)],
                cwd=runtime["root"], stdout=raw_output, stderr=subprocess.DEVNULL,
                timeout=timeout_seconds, check=False,
            )
            if completed.returncode != 0:
                status = "nonzero_exit"
            else:
                raw_output.seek(0)
                try:
                    review_cells = parse_native_output(json.load(raw_output))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    status = "invalid_json"
                except OutputSchemaError:
                    status = "invalid_output_schema"
        except subprocess.TimeoutExpired:
            status = "timeout"

    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "unit_id": unit_id,
        "workbook_sha256": expected_sha,
        "status": status,
        "review_cells": review_cells if status == "ok" else [],
        "review_cost": len(review_cells) if status == "ok" else None,
        "acted": int(bool(review_cells)) if status == "ok" else None,
        "label_inputs": [],
        "protected_data_inputs": [],
        "raw_native_output_persisted": False,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if output.exists():
        if output.read_bytes() != encoded:
            raise ValueError(f"completed ExceLint shard differs: {unit_id}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".json.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, output)
    return payload


def _macro(rows: Sequence[Mapping[str, object]], field: str) -> float | None:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["structure_group"])].append(float(row[field]))
    if not groups:
        return None
    return sum(sum(values) / len(values) for values in groups.values()) / len(groups)


def score(
    events: Sequence[Mapping[str, object]],
    predictions: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    for event in events:
        unit_id = str(event["unit_id"])
        prediction = predictions[unit_id]
        supported = prediction["status"] == "ok"
        review_cells = {str(cell) for cell in prediction["review_cells"]}
        sources = {str(cell) for cell in event["source_formula_cells"]}
        region_hit = int(bool(review_cells & sources)) if supported else None
        rows.append({
            "event_id": event["event_id"],
            "unit_id": unit_id,
            "structure_group": event["structure_group"],
            "cohort": event["cohort"],
            "case_kind": event["case_kind"],
            "status": prediction["status"],
            "supported": int(supported),
            "source_region_hit": region_hit,
            "review_cost": prediction["review_cost"],
            "acted": prediction["acted"],
        })

    errors = [row for row in rows if row["case_kind"] == "error"]
    supported_errors = [row for row in errors if row["supported"]]
    conservative_errors = [
        {**row, "conservative_hit": row["source_region_hit"] or 0}
        for row in errors
    ]
    control_units = {
        str(row["unit_id"]): row for row in rows if row["case_kind"] == "control"
    }
    supported_controls = [row for row in control_units.values() if row["supported"]]
    unit_predictions = list(predictions.values())
    supported_units = [row for row in unit_predictions if row["status"] == "ok"]

    cohorts: dict[str, object] = {}
    for cohort in sorted({str(row["cohort"]) for row in rows}):
        cohort_rows = [row for row in rows if row["cohort"] == cohort]
        cohort_errors = [row for row in cohort_rows if row["case_kind"] == "error"]
        cohort_supported = [row for row in cohort_errors if row["supported"]]
        cohort_conservative = [
            {**row, "conservative_hit": row["source_region_hit"] or 0}
            for row in cohort_errors
        ]
        cohorts[cohort] = {
            "events": len(cohort_rows),
            "error_events": len(cohort_errors),
            "supported_error_events": len(cohort_supported),
            "source_region_hit_supported": _macro(cohort_supported, "source_region_hit"),
            "source_region_hit_all_inputs_conservative": _macro(
                cohort_conservative, "conservative_hit"
            ),
        }

    summary = {
        "compatibility": {
            "units": len(unit_predictions),
            "supported_units": len(supported_units),
            "supported_unit_rate": len(supported_units) / len(unit_predictions),
            "status_counts": dict(sorted(Counter(str(row["status"]) for row in unit_predictions).items())),
        },
        "native_region": {
            "error_events": len(errors),
            "supported_error_events": len(supported_errors),
            "source_region_hit_structure_macro_supported": _macro(
                supported_errors, "source_region_hit"
            ),
            "source_region_hit_structure_macro_all_inputs_conservative": _macro(
                conservative_errors, "conservative_hit"
            ),
            "mean_review_cells_per_supported_unit": (
                sum(int(row["review_cost"]) for row in supported_units) / len(supported_units)
                if supported_units else None
            ),
            "median_review_cells_per_supported_unit": (
                statistics.median(int(row["review_cost"]) for row in supported_units)
                if supported_units else None
            ),
            "metric_note": "native foundBugs region hit and unique review-cell cost; no Top-5 or MRR",
        },
        "control_safety": {
            "control_units": len(control_units),
            "supported_control_units": len(supported_controls),
            "control_workbook_action_rate_supported": (
                sum(int(row["acted"]) for row in supported_controls) / len(supported_controls)
                if supported_controls else None
            ),
        },
        "by_cohort": cohorts,
    }
    return summary, rows


def run(
    *, profiles_path: Path, events_path: Path, output_dir: Path,
    excelint_root: Path, node: Path, workers: int, timeout_seconds: int,
) -> Path:
    for path in (profiles_path, events_path, output_dir, excelint_root, node):
        reject_protected(path)
    if workers < 1 or timeout_seconds < 1:
        raise ValueError("workers and timeout must be positive")
    identity = runtime_identity(excelint_root, node)
    profiles = read_profiles(profiles_path)
    runtime = json.dumps({
        "root": str(excelint_root),
        "node": str(node),
        "cli": str(excelint_root / "build/src/cli/excelint-cli.js"),
    })
    tasks = []
    for unit_id in sorted(profiles):
        profile = profiles[unit_id]
        workbook = (ROOT / profile["path"]).resolve()
        output = output_dir / "shards" / (unit_id.split(":", 1)[1] + ".json")
        tasks.append((
            unit_id, str(workbook), profile["workbook_sha256"], str(output),
            runtime, timeout_seconds,
        ))

    predictions: dict[str, dict[str, object]] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        futures = {executor.submit(predict_one, task): task[0] for task in tasks}
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            payload = future.result()
            predictions[str(payload["unit_id"])] = payload
            if index % 20 == 0 or index == len(tasks):
                print(f"ExceLint native {index}/{len(tasks)}", flush=True)

    # Labels are opened only after every label-free native prediction is complete.
    events = load_event_rows(events_path)
    if {str(row["unit_id"]) for row in events} - set(predictions):
        raise ValueError("event table contains a unit without an ExceLint prediction")
    summary, event_rows = score(events, predictions)
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(event_rows, key=lambda row: str(row["event_id"]))
    ).encode("utf-8")
    write_immutable(output_dir / "event_scores.jsonl", event_bytes)
    shard_hash = hashlib.sha256()
    for path in sorted((output_dir / "shards").glob("*.json")):
        shard_hash.update(path.name.encode("utf-8") + b"\0" + bytes.fromhex(sha256(path)))
    receipt_payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "source_lock_git_commit": git_commit(ROOT),
        "workers": workers,
        "timeout_seconds_per_workbook": timeout_seconds,
        "runtime_identity": identity,
        "inputs": {
            "profiles": {"path": relative(profiles_path), "sha256": sha256(profiles_path)},
            "events_for_scoring_only": {"path": relative(events_path), "sha256": sha256(events_path)},
        },
        "counts": {"units": len(predictions), "events": len(events), "shards": len(predictions)},
        "summary": summary,
        "artifacts": {
            "event_scores": {
                "path": relative(output_dir / "event_scores.jsonl"),
                "sha256": hashlib.sha256(event_bytes).hexdigest(),
            },
            "combined_shards_sha256": shard_hash.hexdigest(),
        },
        "output_boundary": {
            "raw_native_output_persisted": False,
            "persisted_prediction_fields": [
                "unit_id", "workbook_sha256", "status", "review_cells",
                "review_cost", "acted",
            ],
            "native_formula_or_value_content_persisted": False,
        },
        "label_boundary": {
            "prediction_label_inputs": [],
            "labels_opened_after_all_prediction_shards": True,
        },
        "protected_data_inputs": [],
    }
    receipt_payload["receipt_sha256"] = stable_hash(receipt_payload)
    receipt = output_dir / "receipt.json"
    write_immutable(
        receipt,
        (json.dumps(receipt_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--excelint-root", type=Path, default=DEFAULT_EXCELINT_ROOT)
    parser.add_argument("--node", type=Path, default=DEFAULT_NODE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    receipt = run(
        profiles_path=args.profiles.resolve(),
        events_path=args.events.resolve(),
        output_dir=args.output_dir.resolve(),
        excelint_root=args.excelint_root.resolve(),
        node=args.node.resolve(),
        workers=args.workers,
        timeout_seconds=args.timeout_seconds,
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
