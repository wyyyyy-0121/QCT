#!/usr/bin/env python3
"""Generate locked, label-free FSPR rankings for the revealed public inventory."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.fspr import (
    FSPRModel,
    fspr_decision,
    load_model,
    workbook_logits,
)
from formulaguard.localize import v4_scores
from formulaguard.workbook import WorkbookModel
from scripts.run_header_partition_predictions import (
    canonical_json,
    load_units,
    sha256,
    stable_hash,
    validate_output_path,
)

PROTOCOL = "formulaguard_fspr_public_predictions_v1"
SCHEMA_VERSION = 1
REVIEW_BUDGET = 5
V4_PREFIX = 4
EXPECTED_EVENTS = 220
EXPECTED_WORKBOOKS = 196
MAX_WORKERS = 24
COHORTS = (
    "enron",
    "historical_100",
    "public:info1",
    "public:integer_corpus",
    "public:modified_euses",
)
DEFAULT_GROUPS = ROOT / "results/core_reset_b_phase0/scoring_groups.csv"
DEFAULT_MODEL = ROOT / "results/fspr_v1_run_a/model.json"
DEFAULT_LOCK = ROOT / "research/V5_FSPR_LABEL_FREE_LOCK.json"
DEFAULT_OUTPUT = ROOT / "results/fspr_public_predictions"
SOURCE_PATHS = (
    "formulaguard/fspr.py",
    "formulaguard/localize.py",
    "formulaguard/workbook.py",
    "scripts/run_header_partition_predictions.py",
    "scripts/run_fspr_public_predictions.py",
    "scripts/score_fspr_public_predictions.py",
    "scripts/score_model_discovery_signals.py",
    "research/V5_FSPR_LABEL_FREE_LOCK.json",
    "results/fspr_v1_run_a/model.json",
)

_WORKER_MODEL: FSPRModel | None = None


def _git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_source_status() -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--", *SOURCE_PATHS),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in completed.stdout.splitlines() if line)


def capture_source_state(*, allow_dirty: bool = False) -> dict[str, object]:
    state = {
        "git_commit": _git_commit(),
        "source_sha256": {path: sha256(ROOT / path) for path in SOURCE_PATHS},
        "source_status": list(_git_source_status()),
    }
    dirty = bool(state["source_status"])
    if dirty and not allow_dirty:
        raise ValueError("formal FSPR prediction requires clean tracked source files")
    state["source_tree_dirty"] = dirty
    state["formal_evidence"] = not dirty
    return state


def verify_source_state(expected: Mapping[str, object]) -> None:
    observed = capture_source_state(allow_dirty=True)
    for key in ("git_commit", "source_sha256", "source_status"):
        if observed[key] != expected[key]:
            raise ValueError("FSPR prediction source changed during the run")


def validate_model_lock(lock_path: Path, model_path: Path) -> dict[str, object]:
    lock = json.loads(lock_path.read_text(encoding="ascii"))
    if (
        lock.get("protocol") != "formulaguard_fspr_label_free_lock_v1"
        or lock.get("candidate_locked") is not True
        or lock.get("public_transfer_prediction_authorized") is not True
        or lock.get("spreadsheetbench_v2_download_authorized") is not False
        or lock.get("version_artifact_authorized") is not False
        or lock.get("protected_access_authorized") is not False
    ):
        raise ValueError("FSPR label-free lock does not authorize public prediction")
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise TypeError("FSPR label-free lock artifacts are malformed")
    expected_model = (ROOT / str(artifacts.get("model_path", ""))).resolve()
    if model_path.resolve() != expected_model:
        raise ValueError("FSPR prediction model differs from the locked artifact")
    if sha256(model_path) != artifacts.get("model_sha256"):
        raise ValueError("FSPR locked model hash mismatch")
    return lock


def _init_worker(model_path: str) -> None:
    global _WORKER_MODEL
    _WORKER_MODEL = load_model(model_path)


def predict_unit(payload: tuple[Mapping[str, str], str]) -> dict[str, object]:
    unit, snapshot_text = payload
    if _WORKER_MODEL is None:
        raise RuntimeError("FSPR worker model is not initialized")
    snapshot = Path(snapshot_text)
    expected_hash = unit["workbook_sha256"]
    if sha256(snapshot) != expected_hash:
        raise ValueError("staged workbook hash changed before FSPR prediction")
    workbook = WorkbookModel.from_xlsx(snapshot)
    if sha256(snapshot) != expected_hash:
        raise ValueError("staged workbook hash changed while parsing")
    v4_ranking = [row.cell_label for row in v4_scores(workbook)]
    logits = workbook_logits(workbook, _WORKER_MODEL)
    decision = fspr_decision(v4_ranking, logits, _WORKER_MODEL.threshold)
    fspr_ranking = list(decision.ranking)
    if set(v4_ranking) != set(fspr_ranking) or len(v4_ranking) != len(fspr_ranking):
        raise AssertionError("FSPR public prediction changed the formula inventory")
    return {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        **dict(unit),
        "formula_count": len(v4_ranking),
        "ordinary_visible_formula_count": len(logits),
        "formula_inventory_sha256": stable_hash(sorted(v4_ranking)),
        "v4_ranking": v4_ranking,
        "fspr_ranking": fspr_ranking,
        "v4_top5": v4_ranking[:REVIEW_BUDGET],
        "fspr_top5": fspr_ranking[:REVIEW_BUDGET],
        "fspr_candidate": decision.fspr_candidate,
        "displaced_v4_fifth": decision.displaced_v4_fifth,
        "candidate_logit": decision.candidate_logit,
        "threshold": _WORKER_MODEL.threshold,
        "ranking_changed": decision.changed,
        "model_sha256": _WORKER_MODEL.model_sha256,
        "label_inputs": [],
        "revealed_localization_inputs": [],
        "answer_workbook_inputs": [],
        "task_text_inputs": [],
        "protected_data_inputs": [],
    }


def validate_record(record: Mapping[str, object], model_sha256: str) -> None:
    if record.get("protocol") != PROTOCOL or record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("FSPR public prediction protocol/schema mismatch")
    if record.get("model_sha256") != model_sha256:
        raise ValueError("FSPR public prediction model hash mismatch")
    for field in (
        "label_inputs",
        "revealed_localization_inputs",
        "answer_workbook_inputs",
        "task_text_inputs",
        "protected_data_inputs",
    ):
        if record.get(field) != []:
            raise ValueError(f"FSPR public prediction contains forbidden input: {field}")
    v4 = record.get("v4_ranking")
    fspr = record.get("fspr_ranking")
    if not isinstance(v4, list) or not isinstance(fspr, list):
        raise TypeError("FSPR public rankings are malformed")
    if len(v4) != record.get("formula_count") or len(fspr) != len(v4):
        raise ValueError("FSPR public ranking length is incomplete")
    if len(set(v4)) != len(v4) or set(v4) != set(fspr):
        raise ValueError("FSPR public ranking inventory is invalid")
    if fspr[:V4_PREFIX] != v4[:V4_PREFIX]:
        raise ValueError("FSPR public prediction changed the frozen V4 prefix")
    if record.get("v4_top5") != v4[:REVIEW_BUDGET]:
        raise ValueError("FSPR public V4 Top-5 is inconsistent")
    if record.get("fspr_top5") != fspr[:REVIEW_BUDGET]:
        raise ValueError("FSPR public Top-5 is inconsistent")
    if record.get("formula_inventory_sha256") != stable_hash(sorted(v4)):
        raise ValueError("FSPR public formula inventory hash mismatch")
    changed = v4 != fspr
    if record.get("ranking_changed") is not changed:
        raise ValueError("FSPR public ranking-change flag is inconsistent")
    if changed and fspr[V4_PREFIX] != record.get("fspr_candidate"):
        raise ValueError("FSPR public fifth-slot candidate is inconsistent")


def write_outputs(
    output: Path,
    records: Sequence[Mapping[str, object]],
    receipt: Mapping[str, object],
) -> Path:
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise ValueError("FSPR prediction output or partial directory already exists")
    partial.mkdir(parents=True)
    try:
        predictions = partial / "predictions.jsonl"
        with predictions.open("w", encoding="ascii", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json(record) + "\n")
        completed = {
            **dict(receipt),
            "predictions_sha256": sha256(predictions),
            "record_set_sha256": stable_hash(records),
        }
        (partial / "completion_receipt.json").write_text(
            json.dumps(completed, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="ascii",
        )
        os.replace(partial, output)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return output / "completion_receipt.json"


def run(
    *,
    groups: Path,
    model_path: Path,
    lock_path: Path,
    output: Path,
    workers: int,
    allow_dirty: bool = False,
) -> Path:
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    lock = validate_model_lock(lock_path, model_path)
    classifier = load_model(model_path)
    source_state = capture_source_state(allow_dirty=allow_dirty)
    with tempfile.TemporaryDirectory(prefix="formulaguard-fspr-public-") as temp:
        units, input_audit = load_units(
            groups,
            cohorts=COHORTS,
            root=ROOT,
            snapshot_root=Path(temp) / "workbooks",
        )
        if input_audit.get("selected_identity_rows") != EXPECTED_EVENTS:
            raise ValueError("FSPR public event inventory differs from preregistration")
        if len(units) != EXPECTED_WORKBOOKS:
            raise ValueError("FSPR public workbook inventory differs from preregistration")
        input_paths = [groups.resolve(), model_path.resolve(), lock_path.resolve()]
        input_paths.extend(ROOT / unit["workbook"] for unit in units)
        safe_output = validate_output_path(output, root=ROOT, input_paths=input_paths)
        payloads = [
            (
                {key: value for key, value in unit.items() if not key.startswith("_")},
                unit["_snapshot_path"],
            )
            for unit in units
        ]
        print(f"FSPR public scan: workers={workers}; workbooks={len(payloads)}", flush=True)
        if workers == 1:
            _init_worker(str(model_path))
            records = [predict_unit(payload) for payload in payloads]
        else:
            records = []
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=min(workers, len(payloads)),
                initializer=_init_worker,
                initargs=(str(model_path),),
            ) as executor:
                futures = [executor.submit(predict_unit, payload) for payload in payloads]
                for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                    records.append(future.result())
                    if index % 20 == 0 or index == len(futures):
                        print(f"FSPR public scanned {index}/{len(futures)}", flush=True)
        records.sort(key=lambda row: str(row["unit_id"]))
        for record in records:
            validate_record(record, classifier.model_sha256)
        verify_source_state(source_state)
        by_cohort: dict[str, Counter[str]] = defaultdict(Counter)
        for record in records:
            cohort = str(record["cohort"])
            by_cohort[cohort]["workbooks"] += 1
            by_cohort[cohort]["ranking_changes"] += int(record["ranking_changed"] is True)
        receipt = {
            "protocol": PROTOCOL,
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            **source_state,
            **input_audit,
            "prediction_records": len(records),
            "review_budget": REVIEW_BUDGET,
            "immutable_v4_prefix": V4_PREFIX,
            "model_sha256": classifier.model_sha256,
            "model_lock_sha256": sha256(lock_path),
            "model_implementation_commit": lock["implementation_commit"],
            "ranking_change_workbooks": sum(
                int(record["ranking_changed"] is True) for record in records
            ),
            "by_cohort": {
                cohort: dict(sorted(counts.items()))
                for cohort, counts in sorted(by_cohort.items())
            },
            "label_inputs": [],
            "revealed_localization_inputs": [],
            "answer_workbook_inputs": [],
            "task_text_inputs": [],
            "protected_data_inputs": [],
        }
        return write_outputs(safe_output, records, receipt)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = run(
            groups=args.groups.resolve(),
            model_path=args.model.resolve(),
            lock_path=args.lock.resolve(),
            output=args.output,
            workers=args.workers,
            allow_dirty=args.allow_dirty,
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FSPR public prediction refused: {exc}") from exc
    print(f"FSPR public prediction receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
