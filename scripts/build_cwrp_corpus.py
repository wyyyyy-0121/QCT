"""Profile, deduplicate, and split the preregistered CWRP corpus."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
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
    formula_count_ratio_eligible,
    profile_counter,
    stable_hash,
    weighted_jaccard,
    workbook_profile,
)
from formulaguard.workbook import WorkbookModel
from scripts.acquire_cwrp_sheetjs import COMMIT, sha256
from scripts.convert_cwrp_sheetjs import (
    PROTOCOL as CONVERSION_PROTOCOL,
)
from scripts.convert_cwrp_sheetjs import (
    write_json_atomic,
)

PROTOCOL = "formulaguard_cwrp_corpus_build_v1"
DEFAULT_CONVERSION = ROOT / "results/cwrp_sheetjs_conversion_v2"
DEFAULT_SOURCE = ROOT / "data/external/model_discovery/converted/sheetjs_enron"
DEFAULT_TARGETS = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_OUTPUT = ROOT / "results/cwrp_corpus_v1"
MAX_WORKERS = 24
NEAR_DUPLICATE_THRESHOLD = 0.80
FORMULA_COUNT_RATIO_MIN = 0.5
FORMULA_COUNT_RATIO_MAX = 2.0
TARGET_REQUIRED_FIELDS = {
    "unit_id", "cohort", "structure_cluster_id", "path", "workbook_sha256",
}
FORBIDDEN_FIELDS = {
    "source_cell", "source_cells", "correct_formula", "error_type", "case_kind",
    "template_id", "secret_labels", "pass_fail", "expected_output",
}
ALLOWED_TARGET_ROOTS = (
    ROOT / "data",
    ROOT / "results/v5_psl_pressure_inputs",
)
FORBIDDEN_TARGET_PREFIXES = (
    "data/external/v5_psl/revealed_trial",
    "data/external/v5_psl/custodian",
    "data/external/v5_psl/final_blind",
)


def _git_commit() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    return completed.stdout.strip()


def _safe_converted_path(value: str, source_root: Path) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"invalid converted path: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"unsafe converted path: {value!r}")
    if relative.parts[0] != "nuix" or relative.suffix.lower() != ".xlsx":
        raise ValueError(f"converted path is outside nuix xlsx scope: {value!r}")
    path = source_root.joinpath(*relative.parts).resolve()
    if source_root.resolve() not in path.parents or not path.is_file() or path.is_symlink():
        raise ValueError(f"converted workbook is missing or unsafe: {value!r}")
    return path


def read_conversion(conversion_dir: Path, source_root: Path) -> list[dict[str, object]]:
    receipt_path = conversion_dir / "conversion_receipt.json"
    manifest_path = conversion_dir / "conversion_manifest.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if receipt.get("protocol") != CONVERSION_PROTOCOL or not receipt.get("complete"):
        raise ValueError("conversion receipt is incomplete or has the wrong protocol")
    if receipt.get("source_commit") != COMMIT:
        raise ValueError("conversion receipt uses the wrong upstream commit")
    if receipt.get("conversion_manifest_sha256") != sha256(manifest_path):
        raise ValueError("conversion manifest hash differs from receipt")
    rows = manifest.get("results")
    if not isinstance(rows, list) or len(rows) != receipt.get("source_workbooks"):
        raise ValueError("conversion manifest accounting is incomplete")
    eligible = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "eligible":
            continue
        source_id = str(row.get("source_id", ""))
        if not source_id or source_id in seen:
            raise ValueError(f"duplicate or empty eligible source_id: {source_id!r}")
        seen.add(source_id)
        path = _safe_converted_path(str(row.get("converted_relative_path", "")), source_root)
        if sha256(path) != row.get("converted_sha256"):
            raise ValueError(f"eligible converted hash mismatch: {source_id}")
        if int(row.get("formula_count", 0)) < 1:
            raise ValueError(f"eligible workbook has no formulas: {source_id}")
        eligible.append({
            "workbook_id": source_id,
            "path": path,
            "relative_path": str(row["converted_relative_path"]),
            "workbook_sha256": str(row["converted_sha256"]),
            "formula_count": int(row["formula_count"]),
            "parseable_formula_count": int(row["parseable_formula_count"]),
        })
    if len(eligible) != receipt.get("eligible_workbooks"):
        raise ValueError("eligible workbook count differs from conversion receipt")
    return sorted(eligible, key=lambda row: str(row["workbook_id"]))


def _safe_target_path(value: str) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"invalid target path: {value!r}")
    candidate = (ROOT / value).resolve()
    allowed = tuple(path.resolve() for path in ALLOWED_TARGET_ROOTS)
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise ValueError(f"target path is outside the allowlist: {value!r}")
    relative = candidate.relative_to(ROOT).as_posix()
    if any(relative == prefix or relative.startswith(prefix + "/") for prefix in FORBIDDEN_TARGET_PREFIXES):
        raise ValueError(f"target path is protected: {value!r}")
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"target workbook is missing or unsafe: {value!r}")
    return candidate


def read_targets(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = TARGET_REQUIRED_FIELDS - fields
        forbidden = FORBIDDEN_FIELDS & fields
        if missing or forbidden:
            raise ValueError(
                f"target profiles missing={sorted(missing)} forbidden={sorted(forbidden)}"
            )
        rows = list(reader)
    if not rows:
        raise ValueError("target profile list is empty")
    normalized = []
    seen: set[str] = set()
    for row in rows:
        workbook_id = str(row["unit_id"])
        if not workbook_id or workbook_id in seen:
            raise ValueError(f"duplicate or empty target unit_id: {workbook_id!r}")
        seen.add(workbook_id)
        workbook = _safe_target_path(str(row["path"]))
        observed_hash = sha256(workbook)
        if observed_hash != row["workbook_sha256"]:
            raise ValueError(f"target workbook hash mismatch: {workbook_id}")
        normalized.append({
            "workbook_id": workbook_id,
            "path": workbook,
            "relative_path": workbook.relative_to(ROOT).as_posix(),
            "workbook_sha256": observed_hash,
        })
    return sorted(normalized, key=lambda row: str(row["workbook_id"]))


def _shard_name(kind: str, workbook_id: str) -> str:
    return hashlib.sha256(f"{kind}\0{workbook_id}".encode()).hexdigest() + ".json"


def _profile_worker(payload: tuple[str, str, str, str]) -> dict[str, object]:
    kind, workbook_id, path_text, expected_hash = payload
    path = Path(path_text)
    if sha256(path) != expected_hash:
        raise ValueError(f"input changed before profiling: {workbook_id}")
    profile = workbook_profile(WorkbookModel.from_xlsx(path))
    return {
        "protocol": PROTOCOL,
        "kind": kind,
        "workbook_id": workbook_id,
        "workbook_sha256": expected_hash,
        "profile": profile,
    }


def _validate_profile_shard(
    path: Path,
    *,
    kind: str,
    row: Mapping[str, object],
) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("protocol") != PROTOCOL
        or record.get("kind") != kind
        or record.get("workbook_id") != row["workbook_id"]
        or record.get("workbook_sha256") != row["workbook_sha256"]
    ):
        raise ValueError(f"profile shard identity mismatch: {path.name}")
    profile = record.get("profile")
    if not isinstance(profile, dict) or profile.get("protocol") != PROFILE_PROTOCOL:
        raise ValueError(f"profile shard payload is malformed: {path.name}")
    profile_counter(profile)
    if any(profile.get(key) != 0 for key in (
        "sensitive_text_features", "raw_numeric_features", "sheet_name_features",
        "formula_literal_features",
    )):
        raise ValueError(f"profile shard exports forbidden content: {path.name}")
    return record


def _union_find(ids: Sequence[str]):
    parent = {value: value for value in ids}

    def find(value: str) -> str:
        root = value
        while parent[root] != root:
            root = parent[root]
        while parent[value] != value:
            next_value = parent[value]
            parent[value] = root
            value = next_value
        return root

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a == b:
            return
        if a < b:
            parent[b] = a
        else:
            parent[a] = b

    return find, union


def _edge(left: Mapping[str, object], right: Mapping[str, object]) -> tuple[bool, str, float]:
    if left["workbook_sha256"] == right["workbook_sha256"]:
        return True, "exact_bytes", 1.0
    left_profile = left["profile"]
    right_profile = right["profile"]
    if not isinstance(left_profile, dict) or not isinstance(right_profile, dict):
        raise ValueError("template edge requires workbook profiles")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    if left_profile["structural_signature"] == right_profile["structural_signature"]:
        return True, "exact_structure", 1.0
    left_count = int(left_profile["parseable_formula_count"])
    right_count = int(right_profile["parseable_formula_count"])
    if not formula_count_ratio_eligible(
        left_count, right_count,
        minimum=FORMULA_COUNT_RATIO_MIN,
        maximum=FORMULA_COUNT_RATIO_MAX,
    ):
        return False, "", 0.0
    left_counter = left.get("_profile_counter")
    right_counter = right.get("_profile_counter")
    if not isinstance(left_counter, Counter):
        left_counter = profile_counter(left_profile)
    if not isinstance(right_counter, Counter):
        right_counter = profile_counter(right_profile)
    similarity = weighted_jaccard(left_counter, right_counter)
    if similarity >= NEAR_DUPLICATE_THRESHOLD:
        return True, "near_formula_multiset", similarity
    return False, "", similarity


def cluster_profiles(
    corpus: Sequence[Mapping[str, object]],
    targets: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    prepared_corpus = [
        {**row, "_profile_counter": profile_counter(row["profile"])}  # type: ignore[arg-type]
        for row in corpus
    ]
    prepared_targets = [
        {**row, "_profile_counter": profile_counter(row["profile"])}  # type: ignore[arg-type]
        for row in targets
    ]
    ids = [str(row["workbook_id"]) for row in prepared_corpus]
    if len(ids) != len(set(ids)):
        raise ValueError("corpus workbook IDs are not unique")
    find, union = _union_find(ids)
    internal_reasons: Counter[str] = Counter()
    internal_edges = 0
    for index, left in enumerate(prepared_corpus):
        for right in prepared_corpus[index + 1:]:
            connected, reason, _ = _edge(left, right)
            if connected:
                union(str(left["workbook_id"]), str(right["workbook_id"]))
                internal_edges += 1
                internal_reasons[reason] += 1

    target_connections: dict[str, list[dict[str, object]]] = defaultdict(list)
    target_reasons: Counter[str] = Counter()
    for source in prepared_corpus:
        source_id = str(source["workbook_id"])
        for target in prepared_targets:
            connected, reason, similarity = _edge(source, target)
            if connected:
                target_connections[source_id].append({
                    "target_id": target["workbook_id"],
                    "reason": reason,
                    "similarity": round(similarity, 12),
                })
                target_reasons[reason] += 1

    components: dict[str, list[str]] = defaultdict(list)
    for workbook_id in ids:
        components[find(workbook_id)].append(workbook_id)
    excluded_roots = {
        find(workbook_id) for workbook_id in target_connections
    }
    group_by_id: dict[str, str] = {}
    excluded_by_id: dict[str, bool] = {}
    group_members: dict[str, list[str]] = {}
    for members in components.values():
        ordered = sorted(members)
        group_id = "template-group:" + stable_hash(ordered)[:24]
        group_members[group_id] = ordered
        excluded = find(ordered[0]) in excluded_roots
        for workbook_id in ordered:
            group_by_id[workbook_id] = group_id
            excluded_by_id[workbook_id] = excluded

    retained_groups = sorted(
        group_id for group_id, members in group_members.items()
        if not excluded_by_id[members[0]]
    )
    fold_by_group = {group_id: index % 5 for index, group_id in enumerate(retained_groups)}
    output = []
    for row in prepared_corpus:
        workbook_id = str(row["workbook_id"])
        group_id = group_by_id[workbook_id]
        connections = sorted(
            target_connections.get(workbook_id, []),
            key=lambda item: (str(item["target_id"]), str(item["reason"])),
        )
        output.append({
            "workbook_id": workbook_id,
            "workbook_sha256": row["workbook_sha256"],
            "relative_path": row.get("relative_path", ""),
            "formula_count": row["profile"]["formula_count"],  # type: ignore[index]
            "parseable_formula_count": row["profile"]["parseable_formula_count"],  # type: ignore[index]
            "formula_multiset_sha256": row["profile"]["formula_multiset_sha256"],  # type: ignore[index]
            "structural_signature": row["profile"]["structural_signature"],  # type: ignore[index]
            "template_group_id": group_id,
            "template_group_size": len(group_members[group_id]),
            "excluded_target_overlap_component": excluded_by_id[workbook_id],
            "direct_target_connections": connections,
            "outer_fold": None if excluded_by_id[workbook_id] else fold_by_group[group_id],
        })
    audit = {
        "internal_edges": internal_edges,
        "internal_edge_reasons": dict(sorted(internal_reasons.items())),
        "target_edges": sum(len(items) for items in target_connections.values()),
        "target_edge_reasons": dict(sorted(target_reasons.items())),
        "template_groups": len(group_members),
        "retained_template_groups": len(retained_groups),
        "excluded_template_groups": len(group_members) - len(retained_groups),
        "directly_target_connected_workbooks": len(target_connections),
        "excluded_component_workbooks": sum(excluded_by_id.values()),
    }
    return sorted(output, key=lambda row: str(row["workbook_id"])), audit


def build(
    *,
    conversion_dir: Path,
    source_root: Path,
    target_profiles: Path,
    output_dir: Path,
    workers: int,
    resume: bool = False,
) -> Path:
    conversion_dir = conversion_dir.resolve()
    source_root = source_root.resolve()
    target_profiles = target_profiles.resolve()
    output_dir = output_dir.resolve()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    corpus_rows = read_conversion(conversion_dir, source_root)
    target_rows = read_targets(target_profiles)
    complete_path = output_dir / "corpus_receipt.json"
    if complete_path.exists():
        raise ValueError("corpus build is already complete; completed receipts are immutable")

    metadata = {
        "protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "conversion_receipt_sha256": sha256(conversion_dir / "conversion_receipt.json"),
        "target_profiles_sha256": sha256(target_profiles),
        "corpus_inputs": len(corpus_rows),
        "target_inputs": len(target_rows),
        "workers_requested": workers,
        "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
        "formula_count_ratio": [FORMULA_COUNT_RATIO_MIN, FORMULA_COUNT_RATIO_MAX],
        "source_hashes": {
            "formulaguard/cwrp.py": sha256(ROOT / "formulaguard/cwrp.py"),
            "scripts/build_cwrp_corpus.py": sha256(Path(__file__).resolve()),
        },
        "target_fields_read": sorted(TARGET_REQUIRED_FIELDS),
        "fault_label_fields_rejected": sorted(FORBIDDEN_FIELDS),
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "filename_features": False,
    }
    metadata_path = output_dir / "metadata.json"
    if output_dir.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("partial corpus output exists; pass --resume after audit")
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("partial corpus metadata differs from this run")
    else:
        output_dir.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    shards = output_dir / "profile_shards"
    shards.mkdir(exist_ok=True)

    all_rows = [("corpus", row) for row in corpus_rows] + [("target", row) for row in target_rows]
    records: dict[tuple[str, str], dict[str, object]] = {}
    pending = []
    for kind, row in all_rows:
        workbook_id = str(row["workbook_id"])
        shard = shards / _shard_name(kind, workbook_id)
        if shard.exists():
            records[(kind, workbook_id)] = _validate_profile_shard(shard, kind=kind, row=row)
        else:
            pending.append((kind, row))
    if pending:
        worker_count = min(workers, len(pending))
        print(
            f"CWRP profiling scheduling: workers={worker_count}; "
            f"pending={len(pending)}; resumed={len(all_rows) - len(pending)}",
            flush=True,
        )
        payloads = [
            (kind, str(row["workbook_id"]), str(row["path"]), str(row["workbook_sha256"]))
            for kind, row in pending
        ]
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_profile_worker, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                record = future.result()
                kind = str(record["kind"])
                workbook_id = str(record["workbook_id"])
                shard = shards / _shard_name(kind, workbook_id)
                write_json_atomic(shard, record)
                records[(kind, workbook_id)] = record
                print(f"[{index}/{len(payloads)}] {kind}:{workbook_id}", flush=True)

    corpus_profiles = []
    for row in corpus_rows:
        workbook_id = str(row["workbook_id"])
        record = records[("corpus", workbook_id)]
        profile = record["profile"]
        if (
            profile["formula_count"] != row["formula_count"]  # type: ignore[index]
            or profile["parseable_formula_count"] != row["parseable_formula_count"]  # type: ignore[index]
        ):
            raise ValueError(f"profile/conversion formula counts differ: {workbook_id}")
        corpus_profiles.append({**row, "profile": profile})
    target_profile_rows = [
        {**row, "profile": records[("target", str(row["workbook_id"]))]["profile"]}
        for row in target_rows
    ]
    manifest_rows, dedup_audit = cluster_profiles(corpus_profiles, target_profile_rows)
    manifest = {
        "protocol": PROTOCOL,
        "workbooks": manifest_rows,
    }
    manifest_path = output_dir / "corpus_manifest.json"
    write_json_atomic(manifest_path, manifest)
    retained = [row for row in manifest_rows if not row["excluded_target_overlap_component"]]
    fold_groups: dict[int, set[str]] = defaultdict(set)
    fold_workbooks: Counter[int] = Counter()
    fold_formulas: Counter[int] = Counter()
    for row in retained:
        fold = int(row["outer_fold"])
        fold_groups[fold].add(str(row["template_group_id"]))
        fold_workbooks[fold] += 1
        fold_formulas[fold] += int(row["parseable_formula_count"])
    fold_summary = {
        str(fold): {
            "template_groups": len(fold_groups[fold]),
            "workbooks": fold_workbooks[fold],
            "parseable_formulas": fold_formulas[fold],
        }
        for fold in range(5)
    }
    receipt = {
        "protocol": PROTOCOL,
        "source_commit": COMMIT,
        "profiled_corpus_workbooks": len(corpus_profiles),
        "profiled_target_workbooks": len(target_profile_rows),
        "deduplication": dedup_audit,
        "retained_workbooks": len(retained),
        "retained_parseable_formulas": sum(int(row["parseable_formula_count"]) for row in retained),
        "folds": fold_summary,
        "corpus_manifest_sha256": sha256(manifest_path),
        "corpus_inventory_sha256": stable_hash(manifest_rows),
        "profile_shards_sha256": stable_hash([
            (path.name, sha256(path)) for path in sorted(shards.glob("*.json"))
        ]),
        "u0_partial": {
            "min_100_workbooks": len(retained) >= 100,
            "min_10000_parseable_formulas": sum(
                int(row["parseable_formula_count"]) for row in retained
            ) >= 10000,
            "min_10_template_groups_each_fold": all(
                len(fold_groups[fold]) >= 10 for fold in range(5)
            ),
            "sparse_subset_not_yet_scored": True,
        },
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "complete": len(records) == len(all_rows),
    }
    write_json_atomic(complete_path, receipt)
    return complete_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversion", type=Path, default=DEFAULT_CONVERSION)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        receipt = build(
            conversion_dir=args.conversion,
            source_root=args.source,
            target_profiles=args.targets,
            output_dir=args.output,
            workers=args.workers,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"CWRP corpus build refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
