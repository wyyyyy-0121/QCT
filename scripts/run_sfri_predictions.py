#!/usr/bin/env python3
"""Run deterministic, label-free shared-formula integrity predictions."""

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
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.shared_formula_integrity import (
    PROTOCOL as CERTIFICATE_PROTOCOL,
)
from formulaguard.shared_formula_integrity import analyze_shared_formula_integrity
from formulaguard.workbook import WorkbookModel
from scripts.run_header_partition_predictions import (
    DEFAULT_COHORTS,
    DEFAULT_GROUPS,
    canonical_json,
    git_commit,
    sha256,
    stable_hash,
    validate_output_path,
)
from scripts.run_header_partition_predictions import load_units as _load_units

PROTOCOL = "formulaguard_sfri_predictions_v1"
SCHEMA_VERSION = 1
DEFAULT_OUTPUT = ROOT / "results/sfri_predictions"
MAX_WORKERS = 24
SOURCE_PATHS = (
    "formulaguard/a1.py",
    "formulaguard/formula.py",
    "formulaguard/header_partition.py",
    "formulaguard/shared_formula_integrity.py",
    "formulaguard/workbook.py",
    "scripts/run_header_partition_predictions.py",
    "scripts/run_sfri_predictions.py",
)


def load_units(
    groups_path: Path,
    *,
    cohorts: Sequence[str] = DEFAULT_COHORTS,
    root: Path = ROOT,
    allowed_roots: Sequence[Path] | None = None,
    allowed_group_roots: Sequence[Path] | None = None,
    snapshot_root: Path | None = None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Load the exact preregistered label-free input projection."""

    return _load_units(
        groups_path,
        cohorts=cohorts,
        root=root,
        allowed_roots=allowed_roots,
        allowed_group_roots=allowed_group_roots,
        snapshot_root=snapshot_root,
    )


def _git_source_status(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--", *SOURCE_PATHS),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in completed.stdout.splitlines() if line)


def capture_source_state(
    source_root: Path = ROOT,
    *,
    allow_dirty: bool = False,
) -> dict[str, object]:
    source_root = source_root.resolve()
    state = {
        "git_commit": git_commit(source_root),
        "source_sha256": {
            relative: sha256(source_root / relative) for relative in SOURCE_PATHS
        },
        "source_status": list(_git_source_status(source_root)),
    }
    dirty = bool(state["source_status"])
    if dirty and not allow_dirty:
        raise ValueError(
            "formal prediction run requires clean tracked source files; "
            "use allow_dirty only for non-formal development checks"
        )
    state["source_tree_dirty"] = dirty
    state["formal_evidence"] = not dirty
    return state


def verify_source_state(
    expected: Mapping[str, object], source_root: Path = ROOT
) -> None:
    observed = capture_source_state(source_root, allow_dirty=True)
    comparable = ("git_commit", "source_sha256", "source_status")
    if any(observed[key] != expected[key] for key in comparable):
        raise ValueError("prediction source changed while the scan was running")


def predict_unit(payload: tuple[Mapping[str, str], str]) -> dict[str, object]:
    unit, snapshot_text = payload
    snapshot = Path(snapshot_text)
    expected_hash = unit["workbook_sha256"]
    if sha256(snapshot) != expected_hash:
        raise ValueError("staged workbook hash changed before parsing")
    model = WorkbookModel.from_xlsx(snapshot)
    if sha256(snapshot) != expected_hash:
        raise ValueError("staged workbook hash changed while parsing")
    result = analyze_shared_formula_integrity(model)
    return {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        **dict(unit),
        "formula_count": len(model.formulas),
        "declared_region_count": result.declared_region_count,
        "certificate_count": len(result.certificates),
        "comparison_count": len(result.comparisons),
        "disagreement_count": len(result.disagreement_cells),
        "has_deterministic_candidate": result.deterministic_candidate is not None,
        "abstain_reason": result.abstain_reason,
        "result": asdict(result),
        "label_inputs": [],
        "protected_data_inputs": [],
    }


def _candidate_prediction(
    record: Mapping[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    certificate = candidate.get("certificate")
    if not isinstance(certificate, Mapping):
        raise TypeError("SFRI candidate certificate is malformed")
    return {
        "workbook": record["workbook"],
        "workbook_sha256": record["workbook_sha256"],
        "cohort": record["cohort"],
        "structure_cluster_id": record["structure_cluster_id"],
        "sheet": certificate["sheet"],
        "group_id": certificate["group_id"],
        "region_start": certificate["region_start"],
        "region_end": certificate["region_end"],
        "target_formula_cell": certificate["target_formula_cell"],
        "candidate_formula": candidate["candidate_formula"],
        "observed_formula": candidate["observed_formula"],
        "observed_disagrees": candidate["observed_disagrees"],
        "candidate_derived_without_observed_target": certificate[
            "candidate_derived_without_observed_target"
        ],
        "observed_target_used_for_comparison": candidate[
            "observed_target_used_for_comparison"
        ],
        "comparison_supported": candidate["comparison_supported"],
        "automatic_edit_supported": candidate["automatic_edit_supported"],
        "can_identify_formula_error": certificate["can_identify_formula_error"],
    }


def build_summary(
    records: Sequence[Mapping[str, object]],
    *,
    input_audit: Mapping[str, object],
    workers: int,
    source_state: Mapping[str, object],
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    by_cohort: dict[str, Counter[str]] = defaultdict(Counter)
    abstentions: Counter[str] = Counter()
    for record in records:
        cohort = str(record["cohort"])
        counts = by_cohort[cohort]
        counts["unique_observed_workbooks"] += 1
        counts["declared_regions"] += int(record["declared_region_count"])
        counts["eligible_certificates"] += int(record["certificate_count"])
        counts["audited_comparisons"] += int(record["comparison_count"])
        counts["schema_disagreements"] += int(record["disagreement_count"])
        result = record.get("result")
        if not isinstance(result, Mapping):
            raise TypeError("SFRI prediction result is malformed")
        candidate = result.get("deterministic_candidate")
        reason = record.get("abstain_reason")
        abstentions[str(reason or "sfri_candidate")] += 1
        if candidate is None:
            if reason == "no_schema_disagreement":
                counts["audited_agreement_workbooks"] += 1
            continue
        if not isinstance(candidate, Mapping):
            raise TypeError("SFRI deterministic candidate is malformed")
        counts["candidate_workbooks"] += 1
        candidates.append(_candidate_prediction(record, candidate))
    candidates.sort(key=lambda item: str(item["workbook_sha256"]))
    return {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        "certificate_protocol": CERTIFICATE_PROTOCOL,
        "complete": True,
        **dict(input_audit),
        **dict(source_state),
        "workers_requested": workers,
        "global": {
            "completed_workbooks": len(records),
            "declared_regions": sum(
                int(record["declared_region_count"]) for record in records
            ),
            "eligible_certificates": sum(
                int(record["certificate_count"]) for record in records
            ),
            "audited_comparisons": sum(
                int(record["comparison_count"]) for record in records
            ),
            "schema_disagreements": sum(
                int(record["disagreement_count"]) for record in records
            ),
            "candidate_workbooks": len(candidates),
            "action_workbooks": 0,
            "abstain_reasons": dict(sorted(abstentions.items())),
        },
        "by_cohort": {
            cohort: dict(sorted(counts.items()))
            for cohort, counts in sorted(by_cohort.items())
        },
        "certificate_predictions": candidates,
        "actions": [],
        "label_inputs": [],
        "protected_data_inputs": [],
    }


def validate_outputs(
    records: Sequence[Mapping[str, object]], summary: Mapping[str, object]
) -> None:
    if summary.get("protocol") != PROTOCOL:
        raise ValueError("summary protocol mismatch")
    if summary.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("summary schema mismatch")
    if summary.get("certificate_protocol") != CERTIFICATE_PROTOCOL:
        raise ValueError("summary certificate protocol mismatch")
    if summary.get("label_inputs") != [] or summary.get("protected_data_inputs") != []:
        raise ValueError("summary declares forbidden inputs")
    global_counts = summary.get("global")
    if not isinstance(global_counts, Mapping):
        raise TypeError("summary global counts are malformed")
    if global_counts.get("completed_workbooks") != len(records):
        raise ValueError("summary completion count does not match records")
    candidates = summary.get("certificate_predictions")
    if not isinstance(candidates, list):
        raise TypeError("summary certificate predictions are malformed")
    if global_counts.get("candidate_workbooks") != len(candidates):
        raise ValueError("summary candidate count does not match predictions")
    if global_counts.get("action_workbooks") != 0 or summary.get("actions") != []:
        raise ValueError("SFRI predictions must not claim automatic actions")

    expected_candidates = 0
    record_hashes: set[str] = set()
    for record in records:
        if record.get("protocol") != PROTOCOL:
            raise ValueError("prediction record protocol mismatch")
        if record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("prediction record schema mismatch")
        if record.get("label_inputs") != [] or record.get("protected_data_inputs") != []:
            raise ValueError("prediction record declares forbidden inputs")
        workbook_hash = str(record.get("workbook_sha256"))
        if workbook_hash in record_hashes:
            raise ValueError("prediction records contain a duplicate workbook hash")
        record_hashes.add(workbook_hash)
        result = record.get("result")
        if not isinstance(result, Mapping):
            raise TypeError("prediction result is malformed")
        certificates = result.get("certificates")
        comparisons = result.get("comparisons")
        disagreements = result.get("disagreement_cells")
        if not isinstance(certificates, (list, tuple)):
            raise TypeError("prediction certificates are malformed")
        if not isinstance(comparisons, (list, tuple)):
            raise TypeError("prediction comparisons are malformed")
        if not isinstance(disagreements, (list, tuple)):
            raise TypeError("prediction disagreement cells are malformed")
        if record.get("certificate_count") != len(certificates):
            raise ValueError("prediction certificate count is inconsistent")
        if record.get("comparison_count") != len(comparisons):
            raise ValueError("prediction comparison count is inconsistent")
        if record.get("disagreement_count") != len(disagreements):
            raise ValueError("prediction disagreement count is inconsistent")
        candidate = result.get("deterministic_candidate")
        if candidate is None:
            if record.get("has_deterministic_candidate") is not False:
                raise ValueError("prediction candidate flag is inconsistent")
            if record.get("abstain_reason") is None:
                raise ValueError("abstaining prediction lacks a reason")
            continue
        if not isinstance(candidate, Mapping):
            raise TypeError("prediction candidate is malformed")
        expected_candidates += 1
        if record.get("has_deterministic_candidate") is not True:
            raise ValueError("prediction candidate flag is inconsistent")
        if record.get("abstain_reason") is not None:
            raise ValueError("candidate prediction must not carry an abstain reason")
        if len(disagreements) != 1 or candidate.get("observed_disagrees") is not True:
            raise ValueError("SFRI candidate must be the sole schema disagreement")
        certificate = candidate.get("certificate")
        if not isinstance(certificate, Mapping):
            raise TypeError("prediction candidate certificate is malformed")
        required_truths = (
            certificate.get("target_excluded") is True,
            certificate.get("candidate_derived_without_observed_target") is True,
            certificate.get("observed_target_used_for_comparison") is False,
            certificate.get("can_identify_formula_error") is False,
            candidate.get("comparison_supported") is True,
            candidate.get("observed_target_used_for_comparison") is True,
            candidate.get("automatic_edit_supported") is False,
        )
        if not all(required_truths):
            raise ValueError("SFRI candidate provenance contract is invalid")
    if expected_candidates != len(candidates):
        raise ValueError("summary omitted or duplicated a candidate prediction")
    if len({str(item.get("workbook_sha256")) for item in candidates}) != len(
        candidates
    ):
        raise ValueError("summary contains duplicate candidate workbooks")


def write_predictions(
    output: Path,
    records: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> Path:
    validate_outputs(records, summary)
    output = output.resolve()
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise ValueError("output or partial output already exists")
    partial.mkdir(parents=True)
    try:
        shards = partial / "shards"
        shards.mkdir()
        shard_hashes: dict[str, str] = {}
        for record in records:
            name = f"{record['workbook_sha256']}.json"
            path = shards / name
            path.write_text(canonical_json(record) + "\n", encoding="ascii")
            shard_hashes[f"shards/{name}"] = sha256(path)

        records_path = partial / "predictions.jsonl"
        with records_path.open("w", encoding="ascii", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json(record) + "\n")
        summary_payload = dict(summary)
        summary_payload["predictions_sha256"] = sha256(records_path)
        summary_payload["prediction_records"] = len(records)
        summary_payload["prediction_shards"] = len(shard_hashes)
        summary_payload["shard_inventory_sha256"] = stable_hash(shard_hashes)
        summary_path = partial / "scan_summary.json"
        summary_path.write_text(
            json.dumps(summary_payload, ensure_ascii=True, indent=2, sort_keys=True)
            + "\n",
            encoding="ascii",
        )
        receipt = {
            "protocol": PROTOCOL,
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            "formal_evidence": summary["formal_evidence"],
            "git_commit": summary["git_commit"],
            "source_sha256": summary["source_sha256"],
            "predictions_sha256": sha256(records_path),
            "scan_summary_sha256": sha256(summary_path),
            "prediction_shard_sha256": shard_hashes,
            "shard_inventory_sha256": stable_hash(shard_hashes),
            "record_set_sha256": stable_hash(records),
            "label_inputs": [],
            "protected_data_inputs": [],
        }
        (partial / "completion_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
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
    output: Path,
    cohorts: Sequence[str],
    workers: int,
    root: Path = ROOT,
    allowed_roots: Sequence[Path] | None = None,
    allowed_group_roots: Sequence[Path] | None = None,
    source_root: Path = ROOT,
    allow_dirty: bool = False,
) -> Path:
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    source_state = capture_source_state(source_root, allow_dirty=allow_dirty)
    with tempfile.TemporaryDirectory(prefix="formulaguard-sfri-") as temp:
        units, input_audit = load_units(
            groups,
            cohorts=cohorts,
            root=root,
            allowed_roots=allowed_roots,
            allowed_group_roots=allowed_group_roots,
            snapshot_root=Path(temp) / "workbooks",
        )
        groups_input = groups if groups.is_absolute() else root / groups
        input_paths = [groups_input.resolve()]
        input_paths.extend(root / unit["workbook"] for unit in units)
        safe_output = validate_output_path(
            output,
            root=root,
            input_paths=input_paths,
        )
        payloads = [
            (
                {key: value for key, value in unit.items() if not key.startswith("_")},
                unit["_snapshot_path"],
            )
            for unit in units
        ]
        worker_count = min(workers, len(payloads))
        print(
            f"SFRI scan: workers={worker_count}; workbooks={len(payloads)}",
            flush=True,
        )
        if worker_count == 1:
            records = [predict_unit(payload) for payload in payloads]
        else:
            records = []
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=worker_count
            ) as executor:
                futures = [executor.submit(predict_unit, payload) for payload in payloads]
                for index, future in enumerate(
                    concurrent.futures.as_completed(futures), 1
                ):
                    records.append(future.result())
                    if index % 20 == 0 or index == len(futures):
                        print(f"SFRI scanned {index}/{len(futures)}", flush=True)
        records.sort(key=lambda item: str(item["unit_id"]))
        verify_source_state(source_state, source_root)
        summary = build_summary(
            records,
            input_audit=input_audit,
            workers=workers,
            source_state=source_state,
        )
        return write_predictions(safe_output, records, summary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cohort", action="append", dest="cohorts")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="permit a non-formal development scan from modified source files",
    )
    args = parser.parse_args(argv)
    try:
        receipt = run(
            groups=args.groups.resolve(),
            output=args.output,
            cohorts=tuple(args.cohorts or DEFAULT_COHORTS),
            workers=args.workers,
            allow_dirty=args.allow_dirty,
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"SFRI prediction refused: {exc}") from exc
    print(f"SFRI receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
