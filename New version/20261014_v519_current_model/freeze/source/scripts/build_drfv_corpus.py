"""Profile, deduplicate, split, and gate the preregistered DRFV corpus."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.cwrp import (
    PROFILE_PROTOCOL,
    profile_counter,
    stable_hash,
    workbook_profile,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_cwrp_corpus import (
    PROTOCOL as CWRP_CORPUS_PROTOCOL,
)
from scripts.build_cwrp_corpus import (
    cluster_profiles,
)
from scripts.convert_cwrp_sheetjs import write_json_atomic
from scripts.intake_drfv_spreadsheetbench_v1 import (
    PROTOCOL as INTAKE_PROTOCOL,
)
from scripts.intake_drfv_spreadsheetbench_v1 import (
    sha256,
)

PROTOCOL = "formulaguard_drfv_corpus_build_v1"
DEFAULT_INTAKE = ROOT / "results/drfv_spreadsheetbench_v1_intake"
DEFAULT_SOURCE = ROOT / "data/external/model_discovery/corpus/drfv_spreadsheetbench_v1_inputs"
DEFAULT_PRIOR_PROFILES = ROOT / "results/cwrp_corpus_v1"
DEFAULT_OUTPUT = ROOT / "results/drfv_corpus_v1"
MAX_WORKERS = 24
MIN_PARSEABLE_FRACTION = 0.50
U0_MIN_WORKBOOKS = 300
U0_MIN_GROUPS = 100
U0_MIN_PARSEABLE_FORMULAS = 100_000
U0_MIN_ELIGIBLE_FRACTION = 0.80
SPLIT_PERCENT = (70, 15, 15)


def _git_commit() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _safe_input_path(value: str, source_root: Path) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"invalid intake path: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2:
        raise ValueError(f"unsafe intake path: {value!r}")
    if relative.suffix.lower() != ".xlsx" or not relative.name.lower().endswith("_input.xlsx"):
        raise ValueError(f"intake path is not an input workbook: {value!r}")
    path = source_root.joinpath(*relative.parts).resolve()
    if source_root.resolve() not in path.parents or not path.is_file() or path.is_symlink():
        raise ValueError(f"intake workbook is missing or unsafe: {value!r}")
    return path


def read_intake(intake_dir: Path, source_root: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    receipt_path = intake_dir / "intake_receipt.json"
    manifest_path = intake_dir / "input_manifest.json"
    receipt = json.loads(receipt_path.read_text(encoding="ascii"))
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    if receipt.get("protocol") != INTAKE_PROTOCOL or not receipt.get("complete"):
        raise ValueError("DRFV intake receipt is incomplete or has the wrong protocol")
    if receipt.get("input_manifest_sha256") != sha256(manifest_path):
        raise ValueError("DRFV input manifest hash differs from intake receipt")
    if any(receipt.get(field) for field in (
        "task_metadata_values_read",
        "instruction_inputs",
        "answer_position_inputs",
        "answer_workbook_inputs",
        "fault_label_inputs",
        "v4_rank_inputs",
        "protected_data_inputs",
    )):
        raise ValueError("DRFV intake receipt reports a forbidden input")
    rows = manifest.get("workbooks")
    if not isinstance(rows, list) or len(rows) != receipt.get("extracted_inputs"):
        raise ValueError("DRFV input manifest accounting is incomplete")
    normalized = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("DRFV input manifest row is malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        workbook_id = str(item.get("workbook_id", ""))
        relative_path = str(item.get("relative_path", ""))
        if not workbook_id or workbook_id in seen_ids or relative_path in seen_paths:
            raise ValueError(f"duplicate or empty intake identity: {workbook_id!r}")
        seen_ids.add(workbook_id)
        seen_paths.add(relative_path)
        path = _safe_input_path(relative_path, source_root)
        if path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"intake workbook differs from manifest: {workbook_id}")
        normalized.append({
            "workbook_id": workbook_id,
            "task_id": str(item.get("task_id", "")),
            "path": path,
            "relative_path": relative_path,
            "workbook_sha256": str(item["sha256"]),
            "bytes": int(item["bytes"]),
        })
    return sorted(normalized, key=lambda row: str(row["workbook_id"])), receipt


def _shard_name(workbook_id: str) -> str:
    return hashlib.sha256(workbook_id.encode("utf-8")).hexdigest() + ".json"


def _profile_worker(payload: tuple[str, str, str]) -> dict[str, object]:
    workbook_id, path_text, expected_hash = payload
    path = Path(path_text)
    if sha256(path) != expected_hash:
        raise ValueError(f"input changed before profiling: {workbook_id}")
    try:
        profile = workbook_profile(WorkbookModel.from_xlsx(path))
    except Exception as exc:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
        return {
            "protocol": PROTOCOL,
            "workbook_id": workbook_id,
            "workbook_sha256": expected_hash,
            "status": "excluded_read_error",
            "error_type": type(exc).__name__,
            "profile": None,
        }
    formula_count = int(profile["formula_count"])
    parseable_count = int(profile["parseable_formula_count"])
    fraction = parseable_count / formula_count if formula_count else 0.0
    if formula_count == 0:
        status = "excluded_no_formula"
    elif fraction < MIN_PARSEABLE_FRACTION:
        status = "excluded_low_parse_coverage"
    else:
        status = "eligible"
    return {
        "protocol": PROTOCOL,
        "workbook_id": workbook_id,
        "workbook_sha256": expected_hash,
        "status": status,
        "error_type": None,
        "parseable_formula_fraction": round(fraction, 12),
        "profile": profile,
    }


def _validate_profile_shard(path: Path, expected: Mapping[str, object]) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("protocol") != PROTOCOL
        or record.get("workbook_id") != expected["workbook_id"]
        or record.get("workbook_sha256") != expected["workbook_sha256"]
    ):
        raise ValueError(f"profile shard identity mismatch: {path.name}")
    status = record.get("status")
    profile = record.get("profile")
    if status == "excluded_read_error":
        if profile is not None or not isinstance(record.get("error_type"), str):
            raise ValueError(f"read-error shard is malformed: {path.name}")
        return record
    if status not in {"eligible", "excluded_no_formula", "excluded_low_parse_coverage"}:
        raise ValueError(f"profile shard has invalid status: {path.name}")
    if not isinstance(profile, dict) or profile.get("protocol") != PROFILE_PROTOCOL:
        raise ValueError(f"profile shard payload is malformed: {path.name}")
    profile_counter(profile)
    if any(profile.get(key) != 0 for key in (
        "sensitive_text_features",
        "raw_numeric_features",
        "sheet_name_features",
        "formula_literal_features",
    )):
        raise ValueError(f"profile shard exports forbidden content: {path.name}")
    formula_count = int(profile["formula_count"])
    parseable_count = int(profile["parseable_formula_count"])
    fraction = parseable_count / formula_count if formula_count else 0.0
    if abs(float(record.get("parseable_formula_fraction", -1.0)) - fraction) > 1e-9:
        raise ValueError(f"profile shard parseable fraction is inconsistent: {path.name}")
    expected_status = (
        "excluded_no_formula" if formula_count == 0
        else "excluded_low_parse_coverage" if fraction < MIN_PARSEABLE_FRACTION
        else "eligible"
    )
    if status != expected_status:
        raise ValueError(f"profile shard eligibility is inconsistent: {path.name}")
    return record


def read_prior_profiles(corpus_dir: Path | None) -> tuple[list[dict[str, object]], str | None]:
    if corpus_dir is None:
        return [], None
    receipt_path = corpus_dir / "corpus_receipt.json"
    shards_dir = corpus_dir / "profile_shards"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("protocol") != CWRP_CORPUS_PROTOCOL or not receipt.get("complete"):
        raise ValueError("prior structural-profile receipt is incomplete")
    shard_paths = sorted(shards_dir.glob("*.json"))
    aggregate = stable_hash([(path.name, sha256(path)) for path in shard_paths])
    if aggregate != receipt.get("profile_shards_sha256"):
        raise ValueError("prior structural-profile shards differ from receipt")
    rows = []
    seen: set[str] = set()
    for path in shard_paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        kind = str(record.get("kind", ""))
        source_id = str(record.get("workbook_id", ""))
        profile = record.get("profile")
        if kind not in {"corpus", "target"} or not source_id or not isinstance(profile, dict):
            raise ValueError(f"prior profile shard is malformed: {path.name}")
        profile_counter(profile)
        if any(profile.get(key) != 0 for key in (
            "sensitive_text_features", "raw_numeric_features", "sheet_name_features",
            "formula_literal_features",
        )):
            raise ValueError(f"prior profile shard exports forbidden content: {path.name}")
        workbook_id = f"prior:{kind}:{source_id}"
        if workbook_id in seen:
            raise ValueError(f"duplicate prior profile identity: {workbook_id}")
        seen.add(workbook_id)
        rows.append({
            "workbook_id": workbook_id,
            "workbook_sha256": str(record.get("workbook_sha256", "")),
            "relative_path": "",
            "profile": profile,
        })
    return sorted(rows, key=lambda row: str(row["workbook_id"])), sha256(receipt_path)


def assign_splits(group_ids: Sequence[str]) -> dict[str, str]:
    ordered = sorted(set(group_ids))
    if len(ordered) != len(group_ids):
        raise ValueError("split group IDs must be unique")
    train_end = len(ordered) * SPLIT_PERCENT[0] // 100
    calibration_end = len(ordered) * (SPLIT_PERCENT[0] + SPLIT_PERCENT[1]) // 100
    return {
        group_id: (
            "train" if index < train_end
            else "calibration" if index < calibration_end
            else "internal_test"
        )
        for index, group_id in enumerate(ordered)
    }


def _profile_summary(record: Mapping[str, object]) -> dict[str, object]:
    profile = record.get("profile")
    if not isinstance(profile, dict):
        return {
            "formula_count": 0,
            "parseable_formula_count": 0,
            "parseable_formula_fraction": 0.0,
            "formula_multiset_sha256": None,
            "structural_signature": None,
        }
    return {
        "formula_count": int(profile["formula_count"]),
        "parseable_formula_count": int(profile["parseable_formula_count"]),
        "parseable_formula_fraction": float(record["parseable_formula_fraction"]),
        "formula_multiset_sha256": profile["formula_multiset_sha256"],
        "structural_signature": profile["structural_signature"],
    }


def build(
    *,
    intake_dir: Path,
    source_root: Path,
    prior_profile_dir: Path | None,
    output_dir: Path,
    workers: int,
    resume: bool = False,
) -> Path:
    intake_dir = intake_dir.resolve()
    source_root = source_root.resolve()
    prior_profile_dir = prior_profile_dir.resolve() if prior_profile_dir is not None else None
    output_dir = output_dir.resolve()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    complete_path = output_dir / "corpus_receipt.json"
    if complete_path.exists():
        raise ValueError("DRFV corpus build is already complete; receipts are immutable")
    sources, intake_receipt = read_intake(intake_dir, source_root)
    prior_profiles, prior_receipt_hash = read_prior_profiles(prior_profile_dir)
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "intake_receipt_sha256": sha256(intake_dir / "intake_receipt.json"),
        "input_manifest_sha256": intake_receipt["input_manifest_sha256"],
        "prior_profile_receipt_sha256": prior_receipt_hash,
        "source_workbooks": len(sources),
        "prior_profiles": len(prior_profiles),
        "workers_requested": workers,
        "min_parseable_fraction": MIN_PARSEABLE_FRACTION,
        "near_duplicate_threshold": 0.8,
        "source_hashes": {
            "formulaguard/cwrp.py": sha256(ROOT / "formulaguard/cwrp.py"),
            "scripts/build_cwrp_corpus.py": sha256(ROOT / "scripts/build_cwrp_corpus.py"),
            "scripts/build_drfv_corpus.py": sha256(Path(__file__).resolve()),
        },
        "task_metadata_inputs": [],
        "answer_workbook_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
        "protected_data_inputs": [],
    }
    metadata_path = output_dir / "metadata.json"
    if output_dir.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("partial DRFV corpus output exists; pass --resume after audit")
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("partial DRFV corpus metadata differs from this run")
    else:
        output_dir.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    shards_dir = output_dir / "profile_shards"
    shards_dir.mkdir(exist_ok=True)

    records: dict[str, dict[str, object]] = {}
    pending = []
    for source in sources:
        workbook_id = str(source["workbook_id"])
        shard = shards_dir / _shard_name(workbook_id)
        if shard.exists():
            records[workbook_id] = _validate_profile_shard(shard, source)
        else:
            pending.append(source)
    if pending:
        worker_count = min(workers, len(pending))
        pending_by_id = {str(row["workbook_id"]): row for row in pending}
        print(
            f"DRFV profiling scheduling: workers={worker_count}; pending={len(pending)}; "
            f"resumed={len(sources) - len(pending)}",
            flush=True,
        )
        payloads = [
            (str(row["workbook_id"]), str(row["path"]), str(row["workbook_sha256"]))
            for row in pending
        ]
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_profile_worker, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                record = future.result()
                workbook_id = str(record["workbook_id"])
                shard = shards_dir / _shard_name(workbook_id)
                write_json_atomic(shard, record)
                records[workbook_id] = _validate_profile_shard(
                    shard,
                    pending_by_id[workbook_id],
                )
                if index % 50 == 0 or index == len(payloads):
                    print(f"DRFV profiled {index}/{len(payloads)}", flush=True)

    eligible = []
    status_counts: Counter[str] = Counter()
    for source in sources:
        workbook_id = str(source["workbook_id"])
        record = records[workbook_id]
        status_counts[str(record["status"])] += 1
        if record["status"] == "eligible":
            eligible.append({**source, "profile": record["profile"]})
    clustered, dedup_audit = cluster_profiles(eligible, prior_profiles)
    retained_groups = sorted({
        str(row["template_group_id"])
        for row in clustered
        if not row["excluded_target_overlap_component"]
    })
    split_by_group = assign_splits(retained_groups)

    retained_by_hash: dict[str, list[str]] = defaultdict(list)
    for row in clustered:
        if not row["excluded_target_overlap_component"]:
            retained_by_hash[str(row["workbook_sha256"])].append(str(row["workbook_id"]))
    byte_representatives = {
        min(workbook_ids) for workbook_ids in retained_by_hash.values()
    }
    clustered_by_id = {str(row["workbook_id"]): row for row in clustered}
    manifest_rows = []
    for source in sources:
        workbook_id = str(source["workbook_id"])
        record = records[workbook_id]
        row = {
            "workbook_id": workbook_id,
            "task_id": source["task_id"],
            "relative_path": source["relative_path"],
            "workbook_sha256": source["workbook_sha256"],
            "bytes": source["bytes"],
            "status": record["status"],
            "error_type": record.get("error_type"),
            **_profile_summary(record),
            "template_group_id": None,
            "excluded_known_overlap_component": None,
            "byte_representative": False,
            "split": None,
        }
        if workbook_id in clustered_by_id:
            clustered_row = clustered_by_id[workbook_id]
            excluded = bool(clustered_row["excluded_target_overlap_component"])
            group_id = str(clustered_row["template_group_id"])
            row.update({
                "template_group_id": group_id,
                "excluded_known_overlap_component": excluded,
                "byte_representative": workbook_id in byte_representatives,
                "split": None if excluded else split_by_group[group_id],
            })
        manifest_rows.append(row)

    retained_representatives = [
        row for row in manifest_rows
        if row["status"] == "eligible"
        and not row["excluded_known_overlap_component"]
        and row["byte_representative"]
    ]
    unique_parseable = sum(int(row["parseable_formula_count"]) for row in retained_representatives)
    eligible_fraction = len(eligible) / len(sources) if sources else 0.0
    u0_checks = {
        "min_300_unique_workbooks": len(retained_representatives) >= U0_MIN_WORKBOOKS,
        "min_100_structure_groups": len(retained_groups) >= U0_MIN_GROUPS,
        "min_100000_parseable_formulas": unique_parseable >= U0_MIN_PARSEABLE_FORMULAS,
        "min_80_percent_workbooks_parseable_fraction_ge_50_percent": (
            eligible_fraction >= U0_MIN_ELIGIBLE_FRACTION
        ),
        "known_overlap_components_removed": True,
        "zero_sensitive_text_features": True,
        "zero_raw_numeric_features": True,
        "zero_sheet_name_features": True,
        "zero_fault_label_inputs": True,
        "zero_v4_feature_inputs": True,
        "zero_protected_inputs": True,
    }
    split_groups: dict[str, set[str]] = defaultdict(set)
    split_workbooks: Counter[str] = Counter()
    split_formulas: Counter[str] = Counter()
    for row in retained_representatives:
        split = str(row["split"])
        split_groups[split].add(str(row["template_group_id"]))
        split_workbooks[split] += 1
        split_formulas[split] += int(row["parseable_formula_count"])
    split_summary = {
        split: {
            "template_groups": len(split_groups[split]),
            "unique_workbooks": split_workbooks[split],
            "parseable_formulas": split_formulas[split],
        }
        for split in ("train", "calibration", "internal_test")
    }
    manifest = {"protocol": PROTOCOL, "workbooks": manifest_rows}
    manifest_path = output_dir / "corpus_manifest.json"
    write_json_atomic(manifest_path, manifest)
    receipt = {
        "protocol": PROTOCOL,
        "complete": len(records) == len(sources),
        "git_commit": _git_commit(),
        "source_workbooks": len(sources),
        "status_counts": dict(sorted(status_counts.items())),
        "eligible_fraction": round(eligible_fraction, 12),
        "prior_profiles": len(prior_profiles),
        "deduplication": dedup_audit,
        "retained_unique_byte_workbooks": len(retained_representatives),
        "retained_structure_groups": len(retained_groups),
        "retained_unique_parseable_formulas": unique_parseable,
        "splits": split_summary,
        "u0_checks": u0_checks,
        "u0_passed": all(u0_checks.values()),
        "corpus_manifest_sha256": sha256(manifest_path),
        "corpus_inventory_sha256": stable_hash(manifest_rows),
        "profile_shards_sha256": stable_hash([
            (path.name, sha256(path)) for path in sorted(shards_dir.glob("*.json"))
        ]),
        "task_metadata_inputs": [],
        "answer_workbook_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
        "protected_data_inputs": [],
    }
    write_json_atomic(complete_path, receipt)
    return complete_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", type=Path, default=DEFAULT_INTAKE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--prior-profiles", type=Path, default=DEFAULT_PRIOR_PROFILES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = build(
            intake_dir=args.intake,
            source_root=args.source,
            prior_profile_dir=args.prior_profiles,
            output_dir=args.output,
            workers=args.workers,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"DRFV corpus build refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
