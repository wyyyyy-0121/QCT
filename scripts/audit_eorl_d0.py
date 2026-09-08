"""Run the preregistered EORL D0 task and source-repair availability gate."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.eorl import (
    D0_PROTOCOL,
    PROTOCOL,
    RELATIVE_TOLERANCE,
    finite_number,
    parse_cell_label,
    residual,
    select_output_task,
    source_repair_recoverability,
    values_match,
)
from formulaguard.libreoffice import (
    LibreOfficeEvaluator,
    LibreOfficeUnavailable,
)
from formulaguard.workbook import WorkbookModel
from scripts.run_model_discovery_signals import (
    read_profiles,
    sha256,
    shard_name,
    stable_hash,
)

DEFAULT_PREREGISTRATION = ROOT / "research/V5_EORL_PREREGISTRATION.json"
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_EVENTS = ROOT / "results/model_discovery_gate2_final_v3/event_scores.jsonl"
DEFAULT_MANIFEST = ROOT / "results/v5_psl_pressure_inputs/public_pressure_manifest.csv"
DEFAULT_SIGNALS = ROOT / "results/model_discovery_signal_audit_observed"
DEFAULT_OUTPUT = ROOT / "results/eorl_d0_a"
EXPECTED_PROFILES_SHA256 = "26f7d1d64a65860fb90714a51beb602742d28d1cfefeea8cbadf331b0e1463dc"
EXPECTED_EVENTS_SHA256 = "c68e2436957a83f6e8e80e6de6c5a3d45ca35b71e162ebc928275352ba90dd34"
EXPECTED_MANIFEST_SHA256 = "bed0ac4e026fd2afea1552d00262b00c0b6034cbc6cbcabf6355c9115719ac54"
EXPECTED_SIGNAL_SHARDS_SHA256 = "17fab17b109376e22d339a25d3861aa8c72e5c05a2c410cceab1845938a93890"
EXPECTED_HYPOTHESIS_CONFIG_SHA256 = "7cc319ad154cd874e8fda1249daa334ecbd6f37417fdcb4b52ee006c663b30bd"
EXPECTED_ERRORS = 60
EXPECTED_CONTROLS = 30
FORBIDDEN_TASK_FIELDS = {
    "case_kind", "cohort", "source_cell", "source_cells", "source_formula_cells",
    "correct_formula", "correct_formulas", "structure_group", "reference_path",
}


def _reject_protected(path: Path) -> None:
    if "FormulaGuard_240_120" in path.resolve().parts:
        raise ValueError(f"protected path is forbidden before EORL candidate lock: {path}")


def _require_clean_tracked_worktree() -> None:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("tracked worktree must be clean before EORL D0")


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    return payload


def _read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle) if row.get("include") == "1"]
    required = {
        "instance_id", "corpus_id", "workbook", "original_workbook",
        "case_kind", "source_cells", "include",
    }
    if not rows or not required <= set(rows[0]):
        raise ValueError("public pair manifest is empty or malformed")
    if len(rows) != EXPECTED_ERRORS + EXPECTED_CONTROLS:
        raise ValueError(f"unexpected public pair count: {len(rows)}")
    counts = Counter(row["case_kind"] for row in rows)
    if counts != Counter({"error": EXPECTED_ERRORS, "control": EXPECTED_CONTROLS}):
        raise ValueError(f"unexpected public case counts: {dict(counts)}")
    ids = [row["instance_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate public instance id")
    return sorted(rows, key=lambda row: row["instance_id"])


def _read_events(path: Path) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            event_id = str(row.get("event_id", ""))
            if not event_id or event_id in rows:
                raise ValueError(f"duplicate or empty event id: {event_id!r}")
            rows[event_id] = row
    return rows


def _source_cells(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise ValueError("event source_formula_cells is malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    return [parse_cell_label(str(item)) for item in value]


def _relative(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(ROOT).as_posix()


def _load_signal(signals: Path, unit_id: str, expected_hash: str) -> dict[str, object]:
    record = _read_json(signals / "shards" / shard_name(unit_id))
    if record.get("unit_id") != unit_id or record.get("workbook_sha256") != expected_hash:
        raise ValueError(f"signal identity mismatch: {unit_id}")
    audit = record.get("audit")
    if not isinstance(audit, dict) or audit.get("configuration_sha256") != EXPECTED_HYPOTHESIS_CONFIG_SHA256:
        raise ValueError(f"signal configuration mismatch: {unit_id}")
    return audit


def _task_worker(payload: Mapping[str, object]) -> dict[str, object]:
    observed_path = Path(str(payload["observed_path"]))
    reference_path = Path(str(payload["reference_path"]))
    observed = WorkbookModel.from_xlsx(observed_path)
    reference = WorkbookModel.from_xlsx(reference_path)
    sources = [parse_cell_label(str(value)) for value in payload["source_formula_cells"]]  # type: ignore[union-attr]
    selected = select_output_task(
        observed,
        reference,
        case_kind=str(payload["case_kind"]),
        source_formula_cells=sources,
    )
    scoring: dict[str, object] = {
        "event_id": payload["event_id"],
        "case_kind": payload["case_kind"],
        "cohort": payload["cohort"],
        "structure_group": payload["structure_group"],
        "source_formula_cells": list(payload["source_formula_cells"]),  # type: ignore[arg-type]
        "eligible": bool(selected["eligible"]),
        "selection": selected,
    }
    task: dict[str, object] | None = None
    if selected["eligible"] is True:
        output_cell = parse_cell_label(str(selected["output_cell"]))
        task = {
            "protocol": "formulaguard_eorl_public_task_v1",
            "task_id": payload["event_id"],
            "unit_id": payload["unit_id"],
            "workbook_path": _relative(observed_path),
            "workbook_sha256": payload["workbook_sha256"],
            "reference_sha256": payload["reference_sha256"],
            "output_cell": selected["output_cell"],
            "actual_value": selected["actual_value"],
            "expected_value": selected["expected_value"],
            "base_residual": selected["base_residual"],
            "cone_formula_count": selected["cone_formula_count"],
            "inference_fields": ["workbook_path", "output_cell", "expected_value"],
            "label_inputs_to_prediction": [],
        }
        if payload["case_kind"] == "error":
            audit = _read_json(Path(str(payload["signal_path"])))
            records = audit.get("records")
            if not isinstance(records, list):
                raise ValueError(f"malformed signal records: {payload['event_id']}")
            by_cell = {
                str(row["cell"]): row for row in records
                if isinstance(row, dict) and "cell" in row
            }
            scoring["source_recoverability"] = source_repair_recoverability(
                observed,
                output_cell=output_cell,
                expected_value=float(selected["expected_value"]),
                source_formula_cells=sources,
                records_by_cell=by_cell,
            )
        else:
            scoring["source_recoverability"] = None
    return {
        "event_id": payload["event_id"],
        "task": task,
        "scoring": scoring,
        "observed_path": str(observed_path),
        "reference_path": str(reference_path),
    }


def _lo_value(evaluation, output: tuple[str, str]) -> float | None:
    if output in evaluation.errors:
        return None
    return finite_number(evaluation.values.get(output))


def _cross_engine_worker(payload: Mapping[str, object]) -> dict[str, object]:
    event_id = str(payload["event_id"])
    output = parse_cell_label(str(payload["output_cell"]))
    result: dict[str, object] = {
        "event_id": event_id,
        "case_kind": payload["case_kind"],
        "sample_hash": hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
        "engine_available": False,
        "agreement": False,
    }
    try:
        observed = WorkbookModel.from_xlsx(Path(str(payload["observed_path"])))
        reference = WorkbookModel.from_xlsx(Path(str(payload["reference_path"])))
        with LibreOfficeEvaluator(observed) as evaluator:
            observed_base, _ = evaluator.evaluate(observed, [])
            repaired_base = None
            best = payload.get("best")
            if isinstance(best, Mapping):
                source = parse_cell_label(str(best["source_cell"]))
                repaired_base, _ = evaluator.evaluate(
                    observed,
                    [],
                    formula_overrides={source: str(best["formula"])},
                )
            engine_version = evaluator.engine_version
        with LibreOfficeEvaluator(reference) as evaluator:
            reference_base, _ = evaluator.evaluate(reference, [])
            reference_engine_version = evaluator.engine_version
        actual = _lo_value(observed_base, output)
        expected = _lo_value(reference_base, output)
        result.update({
            "engine_available": True,
            "engine_version": engine_version,
            "reference_engine_version": reference_engine_version,
            "base_finite": actual is not None,
            "reference_finite": expected is not None,
        })
        if actual is None or expected is None:
            return result
        lo_residual = residual(actual, expected)
        lo_mismatch = not values_match(actual, expected)
        internal_mismatch = float(payload["base_residual"]) > RELATIVE_TOLERANCE
        base_status_agrees = lo_mismatch == internal_mismatch
        sign_applicable = isinstance(payload.get("best"), Mapping)
        sign_agrees = True
        lo_positive = None
        if sign_applicable:
            repaired_value = _lo_value(repaired_base, output) if repaired_base is not None else None
            lo_positive = bool(
                repaired_value is not None
                and lo_residual - residual(repaired_value, expected) > RELATIVE_TOLERANCE
            )
            sign_agrees = lo_positive == bool(payload["best"]["positive_gain"])  # type: ignore[index]
        result.update({
            "base_residual": lo_residual,
            "base_status_agrees": base_status_agrees,
            "repair_sign_applicable": sign_applicable,
            "repair_gain_positive": lo_positive,
            "repair_sign_agrees": sign_agrees if sign_applicable else None,
            "agreement": base_status_agrees and sign_agrees,
        })
        return result
    except (OSError, ValueError, KeyError, LibreOfficeUnavailable) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def _sample_rows(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    selected: list[Mapping[str, object]] = []
    for kind in ("error", "control"):
        candidates = [row for row in rows if row["scoring"]["case_kind"] == kind and row["task"] is not None]  # type: ignore[index]
        candidates.sort(key=lambda row: hashlib.sha256(str(row["event_id"]).encode("utf-8")).hexdigest())
        count = math.ceil(0.20 * len(candidates))
        selected.extend(candidates[:count])
    return sorted(selected, key=lambda row: str(row["event_id"]))


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"immutable output differs: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _jsonl(rows: Sequence[Mapping[str, object]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")


def _validate_prediction_task(task: Mapping[str, object]) -> None:
    leaked = FORBIDDEN_TASK_FIELDS & set(task)
    if leaked:
        raise ValueError(f"EORL prediction task contains scoring fields: {sorted(leaked)}")
    if task.get("inference_fields") != ["workbook_path", "output_cell", "expected_value"]:
        raise ValueError("EORL prediction task inference field declaration differs")
    if task.get("label_inputs_to_prediction") != []:
        raise ValueError("EORL prediction task contains label inputs")


def _source_hashes() -> dict[str, str]:
    paths = (
        ROOT / "formulaguard/eorl.py",
        ROOT / "scripts/audit_eorl_d0.py",
        ROOT / "research/V5_EORL_PREREGISTRATION.md",
        ROOT / "research/V5_EORL_PREREGISTRATION.json",
    )
    return {_relative(path): sha256(path) for path in paths}


def run(
    *,
    preregistration: Path,
    profiles_path: Path,
    events_path: Path,
    manifest_path: Path,
    signals: Path,
    output: Path,
    workers: int,
) -> Path:
    for path in (preregistration, profiles_path, events_path, manifest_path, signals):
        _reject_protected(path)
    _require_clean_tracked_worktree()
    prereg = _read_json(preregistration)
    if prereg.get("protocol") != PROTOCOL or prereg.get("formal_version_authorized") is not False:
        raise ValueError("EORL preregistration identity mismatch")
    expected_hashes = {
        profiles_path: EXPECTED_PROFILES_SHA256,
        events_path: EXPECTED_EVENTS_SHA256,
        manifest_path: EXPECTED_MANIFEST_SHA256,
    }
    for path, expected in expected_hashes.items():
        if sha256(path) != expected:
            raise ValueError(f"frozen EORL input hash mismatch: {path}")
    signal_complete = _read_json(signals / "complete.json")
    if signal_complete.get("combined_shards_sha256") != EXPECTED_SIGNAL_SHARDS_SHA256:
        raise ValueError("frozen signal shard hash mismatch")

    profiles = read_profiles(profiles_path)
    profile_by_unit = {row["unit_id"]: row for row in profiles}
    events = _read_events(events_path)
    manifest = _read_manifest(manifest_path)
    payloads: list[dict[str, object]] = []
    for row in manifest:
        event = events.get(row["instance_id"])
        if event is None or event.get("case_kind") != row["case_kind"]:
            raise ValueError(f"event/manifest mismatch: {row['instance_id']}")
        observed_relative = row["workbook"] if row["case_kind"] == "error" else row["original_workbook"]
        observed_path = (manifest_path.parent / observed_relative).resolve()
        reference_path = (manifest_path.parent / row["original_workbook"]).resolve()
        _reject_protected(observed_path)
        _reject_protected(reference_path)
        observed_hash = sha256(observed_path)
        reference_hash = sha256(reference_path)
        event_unit = str(event.get("unit_id", ""))
        profile = profile_by_unit.get(event_unit)
        if profile is None or profile["workbook_sha256"] != observed_hash:
            raise ValueError(f"observed workbook absent from frozen profiles: {row['instance_id']}")
        if event.get("workbook_sha256") != observed_hash:
            raise ValueError(f"event/profile identity mismatch: {row['instance_id']}")
        sources = _source_cells(event.get("source_formula_cells"))
        manifest_sources = [
            parse_cell_label(value.strip())
            for value in row["source_cells"].replace("|", ";").split(";") if value.strip()
        ]
        if sources != manifest_sources:
            raise ValueError(f"event/manifest source mismatch: {row['instance_id']}")
        audit = _load_signal(signals, profile["unit_id"], observed_hash)
        signal_copy = output.resolve().parent / (output.name + "_input_shards") / shard_name(profile["unit_id"])
        # A minimal task-local copy prevents workers from receiving the source manifest.
        _write_immutable(signal_copy, json.dumps(audit, ensure_ascii=True, sort_keys=True).encode("utf-8"))
        payloads.append({
            "event_id": row["instance_id"],
            "case_kind": row["case_kind"],
            "cohort": f"public:{row['corpus_id']}",
            "structure_group": event["structure_group"],
            "unit_id": profile["unit_id"],
            "workbook_sha256": observed_hash,
            "reference_sha256": reference_hash,
            "observed_path": str(observed_path),
            "reference_path": str(reference_path),
            "source_formula_cells": [f"{cell[0]}!{cell[1]}" for cell in sources],
            "signal_path": str(signal_copy),
        })

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(_task_worker, payloads))
    rows.sort(key=lambda row: str(row["event_id"]))
    if len(rows) != EXPECTED_ERRORS + EXPECTED_CONTROLS:
        raise ValueError("D0 worker result is incomplete")

    sample = _sample_rows(rows)
    cross_payloads = []
    for row in sample:
        task = row["task"]
        scoring = row["scoring"]
        recoverability = scoring.get("source_recoverability")
        cross_payloads.append({
            "event_id": row["event_id"],
            "case_kind": scoring["case_kind"],
            "observed_path": row["observed_path"],
            "reference_path": row["reference_path"],
            "output_cell": task["output_cell"],
            "base_residual": task["base_residual"],
            "best": recoverability.get("best") if isinstance(recoverability, Mapping) else None,
        })
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, max(1, len(cross_payloads)))) as executor:
        cross_rows = list(executor.map(_cross_engine_worker, cross_payloads))
    cross_rows.sort(key=lambda row: str(row["event_id"]))

    task_rows = [row["task"] for row in rows if row["task"] is not None]
    scoring_rows = [row["scoring"] for row in rows]
    for task in task_rows:
        _validate_prediction_task(task)
    output.mkdir(parents=True, exist_ok=True)
    tasks_path = output / "tasks.jsonl"
    scoring_path = output / "scoring.jsonl"
    cross_path = output / "cross_engine.jsonl"
    _write_immutable(tasks_path, _jsonl(task_rows))
    _write_immutable(scoring_path, _jsonl(scoring_rows))
    _write_immutable(cross_path, _jsonl(cross_rows))

    eligible_errors = [row for row in scoring_rows if row["case_kind"] == "error" and row["eligible"]]
    eligible_controls = [row for row in scoring_rows if row["case_kind"] == "control" and row["eligible"]]
    recoverable_errors = [
        row for row in eligible_errors
        if isinstance(row.get("source_recoverability"), Mapping)
        and row["source_recoverability"].get("residually_recoverable") is True
    ]
    error_groups = {str(row["structure_group"]) for row in eligible_errors}
    recoverable_groups = {str(row["structure_group"]) for row in recoverable_errors}
    cross_agreement = (
        sum(row.get("agreement") is True for row in cross_rows) / len(cross_rows)
        if cross_rows else 0.0
    )
    pre_gates = {
        "eligible_error_events_at_least_40": len(eligible_errors) >= 40,
        "eligible_error_structure_groups_at_least_12": len(error_groups) >= 12,
        "eligible_control_events_at_least_24": len(eligible_controls) >= 24,
        "source_recoverable_error_events_at_least_24": len(recoverable_errors) >= 24,
        "source_recoverable_groups_at_least_8": len(recoverable_groups) >= 8,
        "retained_error_residuals_positive": all(float(row["selection"]["base_residual"]) > RELATIVE_TOLERANCE for row in eligible_errors),
        "retained_control_residuals_zero": all(float(row["selection"]["base_residual"]) <= RELATIVE_TOLERANCE for row in eligible_controls),
        "cross_engine_sample_at_least_20_percent_per_kind": (
            sum(row["case_kind"] == "error" for row in cross_rows) >= math.ceil(0.2 * len(eligible_errors))
            and sum(row["case_kind"] == "control" for row in cross_rows) >= math.ceil(0.2 * len(eligible_controls))
        ),
        "cross_engine_agreement_at_least_90_percent": cross_agreement >= 0.90,
        "protected_and_forbidden_inputs_absent": True,
    }
    summary = {
        "input_events": len(scoring_rows),
        "error_events": EXPECTED_ERRORS,
        "control_events": EXPECTED_CONTROLS,
        "eligible_error_events": len(eligible_errors),
        "eligible_error_structure_groups": len(error_groups),
        "eligible_control_events": len(eligible_controls),
        "source_recoverable_error_events": len(recoverable_errors),
        "source_recoverable_structure_groups": len(recoverable_groups),
        "cross_engine_sample_events": len(cross_rows),
        "cross_engine_agreement_events": sum(row.get("agreement") is True for row in cross_rows),
        "cross_engine_agreement_fraction": cross_agreement,
        "ineligible_reasons": dict(sorted(Counter(
            str(row["selection"].get("reason", "eligible"))
            for row in scoring_rows if not row["eligible"]
        ).items())),
    }
    receipt: dict[str, object] = {
        "protocol": D0_PROTOCOL,
        "eorl_protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "source_hashes": _source_hashes(),
        "inputs": {
            "preregistration_sha256": sha256(preregistration),
            "profiles_sha256": sha256(profiles_path),
            "events_sha256": sha256(events_path),
            "manifest_sha256": sha256(manifest_path),
            "signal_shards_sha256": EXPECTED_SIGNAL_SHARDS_SHA256,
            "hypothesis_configuration_sha256": EXPECTED_HYPOTHESIS_CONFIG_SHA256,
        },
        "workers_requested": workers,
        "summary": summary,
        "pre_reproduction_gates": pre_gates,
        "pre_reproduction_passed": all(pre_gates.values()),
        "reproduction_status": "pending_independent_process",
        "artifacts": {
            "tasks_sha256": sha256(tasks_path),
            "scoring_sha256": sha256(scoring_path),
            "cross_engine_sha256": sha256(cross_path),
        },
        "label_inputs_to_prediction": [],
        "protected_data_inputs": [],
    }
    receipt["receipt_sha256"] = stable_hash(receipt)
    receipt_path = output / "receipt.json"
    _write_immutable(
        receipt_path,
        (json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args(argv)
    if args.workers < 1 or args.workers > 24:
        raise SystemExit("EORL D0 workers must be between 1 and 24")
    try:
        print(run(
            preregistration=args.preregistration.resolve(),
            profiles_path=args.profiles.resolve(),
            events_path=args.events.resolve(),
            manifest_path=args.manifest.resolve(),
            signals=args.signals.resolve(),
            output=args.output.resolve(),
            workers=args.workers,
        ))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"EORL D0 refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
