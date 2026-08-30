#!/usr/bin/env python3
"""Build the frozen, input-only FCRL U1 target manifest with resumable shards."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from formulaguard.fcrl import (
    FCRLAdapterError,
    build_table_input,
    formula_prefix_key,
    local_peer_completion_keys,
)
from formulaguard.fcrl_torch import (
    FCRLTorchError,
    FCRLTokenizerRuntime,
    load_tokenizer_runtime,
    tensorize_tables,
)
from formulaguard.workbook import WorkbookModel


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_fcrl_u1_corpus_v1"
DRFV_MANIFEST_SHA256 = "0e1228992fccf6b13961e397b944133db83dcde72b5372af5c36cd54306e71ed"
DRFV_RECEIPT_SHA256 = "743461a31faf9734d38cbcb43dbf2a23cc1cf30076b8d83ffe22d3d7d6d5e789"
INTAKE_MANIFEST_SHA256 = "bb01edd4a58f80a7f26f6b3051f3bdbc6983b2a5a47a23d185bcd07cf2a4f42d"
EXPECTED_WORKBOOKS = 607
EXPECTED_GROUPS = {"train": 153, "calibration": 33, "internal_test": 33}
MAX_TARGETS_PER_WORKBOOK = 128
MAX_WORKERS = 24

DEFAULT_CORPUS_MANIFEST = ROOT / "results/drfv_corpus_v1/corpus_manifest.json"
DEFAULT_CORPUS_RECEIPT = ROOT / "results/drfv_corpus_v1/corpus_receipt.json"
DEFAULT_INTAKE_MANIFEST = ROOT / "results/drfv_spreadsheetbench_v1_intake/input_manifest.json"
DEFAULT_INPUT_ROOT = ROOT / "data/external/model_discovery/corpus/drfv_spreadsheetbench_v1_inputs"
DEFAULT_FORTAP_SOURCE = ROOT / "data/external/model_discovery/raw/TUTA_table_understanding"
DEFAULT_OUTPUT = ROOT / "results/fcrl_u1_corpus_v1"

_TOKENIZER_RUNTIME: FCRLTokenizerRuntime | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, path)


def git_commit() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def require_clean_tracked_worktree() -> None:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("tracked worktree must be clean before FCRL corpus construction")


def opaque_workbook_id(source_workbook_id: str) -> str:
    return "fcrl-wb:" + hashlib.sha256(source_workbook_id.encode("utf-8")).hexdigest()


def target_hash(workbook_id: str, sheet_index: int, address: str) -> str:
    material = f"{workbook_id}\0{sheet_index}\0{address.upper()}"
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def _safe_source_path(root: Path, relative_text: str) -> Path:
    if not relative_text or "\\" in relative_text or "\0" in relative_text:
        raise ValueError("unsafe input-only relative path")
    candidate = (root / relative_text).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("input-only workbook escapes source root") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("input-only workbook is missing or a symlink")
    return candidate


def load_sources(
    corpus_manifest: Path,
    corpus_receipt: Path,
    intake_manifest: Path,
    input_root: Path,
) -> list[dict[str, object]]:
    if sha256_file(corpus_manifest) != DRFV_MANIFEST_SHA256:
        raise ValueError("DRFV corpus manifest hash mismatch")
    if sha256_file(corpus_receipt) != DRFV_RECEIPT_SHA256:
        raise ValueError("DRFV corpus receipt hash mismatch")
    if sha256_file(intake_manifest) != INTAKE_MANIFEST_SHA256:
        raise ValueError("SpreadsheetBench input manifest hash mismatch")
    receipt = json.loads(corpus_receipt.read_text(encoding="utf-8"))
    if (
        receipt.get("retained_unique_byte_workbooks") != EXPECTED_WORKBOOKS
        or receipt.get("retained_structure_groups") != sum(EXPECTED_GROUPS.values())
        or receipt.get("protected_data_inputs") != []
        or receipt.get("answer_workbook_inputs") != []
        or receipt.get("fault_label_inputs") != []
    ):
        raise ValueError("DRFV corpus receipt violates the FCRL source contract")
    rows = json.loads(corpus_manifest.read_text(encoding="utf-8")).get("workbooks")
    if not isinstance(rows, list):
        raise ValueError("DRFV corpus manifest has no workbook rows")
    intake_rows = json.loads(intake_manifest.read_text(encoding="utf-8")).get("workbooks")
    if not isinstance(intake_rows, list):
        raise ValueError("SpreadsheetBench input manifest has no workbook rows")
    intake_by_id = {str(row["workbook_id"]): row for row in intake_rows}

    retained = [
        row
        for row in rows
        if row.get("status") == "eligible"
        and row.get("byte_representative") is True
        and row.get("excluded_known_overlap_component") is False
    ]
    if len(retained) != EXPECTED_WORKBOOKS:
        raise ValueError("retained FCRL workbook count changed")
    groups: dict[str, set[str]] = defaultdict(set)
    sources: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for row in retained:
        source_id = str(row["workbook_id"])
        intake = intake_by_id.get(source_id)
        if intake is None or intake.get("sha256") != row.get("workbook_sha256"):
            raise ValueError("retained workbook is not bound to the input-only intake")
        split = str(row["split"])
        group = str(row["template_group_id"])
        if split not in EXPECTED_GROUPS:
            raise ValueError("retained workbook has an invalid split")
        groups[split].add(group)
        path = _safe_source_path(input_root, str(intake["relative_path"]))
        digest = str(row["workbook_sha256"])
        if digest in seen_hashes:
            raise ValueError("byte-identical representative repeated")
        seen_hashes.add(digest)
        if sha256_file(path) != digest:
            raise ValueError("retained input-only workbook hash mismatch")
        sources.append(
            {
                "source_workbook_id": source_id,
                "workbook_id": opaque_workbook_id(source_id),
                "source_sha256": digest,
                "path": str(path),
                "structure_group": group,
                "split": split,
            }
        )
    if {split: len(values) for split, values in groups.items()} != EXPECTED_GROUPS:
        raise ValueError("FCRL structure-group split changed")
    group_splits: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        group_splits[str(source["structure_group"])].add(str(source["split"]))
    if any(len(splits) != 1 for splits in group_splits.values()):
        raise ValueError("structure group crosses FCRL splits")
    return sorted(sources, key=lambda row: str(row["workbook_id"]))


def _init_worker(fortap_source: str) -> None:
    global _TOKENIZER_RUNTIME
    _TOKENIZER_RUNTIME = load_tokenizer_runtime(Path(fortap_source))


def _process_workbook(source: Mapping[str, object]) -> dict[str, object]:
    if _TOKENIZER_RUNTIME is None:
        raise RuntimeError("FCRL tokenizer worker is not initialized")
    model = WorkbookModel.from_xlsx(str(source["path"]))
    sheet_order = list(model.sheet_visibility)
    sheet_index = {sheet: index for index, sheet in enumerate(sheet_order)}
    workbook_id = str(source["workbook_id"])
    candidates = [
        (target_hash(workbook_id, sheet_index[key[0]], key[1]), key, sheet_index[key[0]])
        for key in model.formula_cells
        if key[0] in sheet_index and model.is_visible(key)
    ]
    candidates.sort(key=lambda item: item[0])
    selected: list[dict[str, object]] = []
    rejection_counts: Counter[str] = Counter()
    for stable_target_hash, key, ordinal in candidates:
        if len(selected) >= MAX_TARGETS_PER_WORKBOOK:
            rejection_counts["stable_cap_not_examined"] += 1
            continue
        try:
            table = build_table_input(model, key)
            tensor_batch = tensorize_tables([table], _TOKENIZER_RUNTIME)
            peer_keys = local_peer_completion_keys(model, key)
        except FCRLAdapterError as exc:
            rejection_counts[exc.code] += 1
            continue
        except FCRLTorchError as exc:
            rejection_counts[str(exc)] += 1
            continue
        selected.append(
            {
                "target_id": "fcrl-target:" + stable_target_hash,
                "workbook_id": workbook_id,
                "source_sha256": source["source_sha256"],
                "structure_group": source["structure_group"],
                "split": source["split"],
                "sheet_index": ordinal,
                "address": key[1].upper(),
                "gold_key": formula_prefix_key(table.formula_prefix),
                "local_peer_top5": list(peer_keys),
                "reachable_references": tensor_batch.reachable_references[0],
                "total_references": tensor_batch.total_references[0],
                "encoder_hash": tensor_batch.encoder_hashes[0],
            }
        )
    return {
        "protocol": PROTOCOL,
        "workbook_id": workbook_id,
        "source_sha256": source["source_sha256"],
        "structure_group": source["structure_group"],
        "split": source["split"],
        "visible_formula_candidates": len(candidates),
        "selected_targets": len(selected),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "targets": selected,
        "raw_inputs_logged": False,
    }


def _validate_shard(path: Path, source: Mapping[str, object]) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    expected = {
        "protocol": PROTOCOL,
        "workbook_id": source["workbook_id"],
        "source_sha256": source["source_sha256"],
        "structure_group": source["structure_group"],
        "split": source["split"],
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("FCRL target shard identity mismatch")
    if payload.get("raw_inputs_logged") is not False:
        raise ValueError("FCRL target shard raw-input contract changed")
    targets = payload.get("targets")
    if not isinstance(targets, list) or len(targets) != payload.get("selected_targets"):
        raise ValueError("FCRL target shard count mismatch")
    forbidden = {"path", "relative_path", "filename", "task_id", "sheet_name", "raw_value"}
    for target in targets:
        if forbidden.intersection(target):
            raise ValueError("FCRL target shard contains a forbidden identity field")
        if target.get("workbook_id") != source["workbook_id"]:
            raise ValueError("FCRL target belongs to another workbook")
    return payload


def build(
    *,
    corpus_manifest: Path,
    corpus_receipt: Path,
    intake_manifest: Path,
    input_root: Path,
    fortap_source: Path,
    output: Path,
    workers: int,
    resume: bool,
) -> Path:
    require_clean_tracked_worktree()
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    sources = load_sources(corpus_manifest, corpus_receipt, intake_manifest, input_root)
    output = output.resolve()
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "workers": workers,
        "source_workbooks": len(sources),
        "max_targets_per_workbook": MAX_TARGETS_PER_WORKBOOK,
        "hashes": {
            "drfv_manifest": sha256_file(corpus_manifest),
            "drfv_receipt": sha256_file(corpus_receipt),
            "intake_manifest": sha256_file(intake_manifest),
            "adapter_source": sha256_file(ROOT / "formulaguard/fcrl.py"),
            "torch_adapter_source": sha256_file(ROOT / "formulaguard/fcrl_torch.py"),
            "builder_source": sha256_file(Path(__file__).resolve()),
        },
        "task_metadata_inputs": [],
        "answer_workbook_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
        "protected_data_inputs": [],
    }
    metadata_path = output / "metadata.json"
    if output.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("FCRL corpus output exists; pass --resume after audit")
        prior = json.loads(metadata_path.read_text(encoding="ascii"))
        comparable = dict(metadata)
        comparable["workers"] = prior.get("workers")
        if prior != comparable:
            raise ValueError("FCRL corpus resume metadata mismatch")
    else:
        output.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    shards = output / "workbook_shards"
    shards.mkdir(exist_ok=True)

    records: dict[str, dict[str, object]] = {}
    pending: list[dict[str, object]] = []
    for source in sources:
        shard = shards / f"{str(source['workbook_id']).split(':', 1)[1]}.json"
        if shard.exists():
            records[str(source["workbook_id"])] = _validate_shard(shard, source)
        else:
            pending.append(source)
    if pending:
        print(
            f"FCRL U1 corpus scheduling: workers={min(workers, len(pending))}; "
            f"pending={len(pending)}; resumed={len(sources) - len(pending)}",
            flush=True,
        )
        pending_by_id = {str(row["workbook_id"]): row for row in pending}
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(workers, len(pending)),
            initializer=_init_worker,
            initargs=(str(fortap_source.resolve()),),
        ) as executor:
            futures = [executor.submit(_process_workbook, source) for source in pending]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                record = future.result()
                workbook_id = str(record["workbook_id"])
                shard = shards / f"{workbook_id.split(':', 1)[1]}.json"
                write_json_atomic(shard, record)
                records[workbook_id] = _validate_shard(shard, pending_by_id[workbook_id])
                if index % 25 == 0 or index == len(futures):
                    print(f"FCRL U1 corpus completed {index}/{len(futures)}", flush=True)

    targets = sorted(
        (target for record in records.values() for target in record["targets"]),
        key=lambda target: str(target["target_id"]),
    )
    split_targets: Counter[str] = Counter(str(target["split"]) for target in targets)
    split_workbooks: dict[str, set[str]] = defaultdict(set)
    split_groups: dict[str, set[str]] = defaultdict(set)
    for target in targets:
        split = str(target["split"])
        split_workbooks[split].add(str(target["workbook_id"]))
        split_groups[split].add(str(target["structure_group"]))
    train_frequency = Counter(
        str(target["gold_key"]) for target in targets if target["split"] == "train"
    )
    global_top5 = [
        key for key, _count in sorted(train_frequency.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    rejection_counts: Counter[str] = Counter()
    for record in records.values():
        rejection_counts.update(record["rejection_counts"])
    manifest = {
        "protocol": PROTOCOL,
        "global_frequency_top5_train_only": global_top5,
        "targets": targets,
    }
    manifest_path = output / "target_manifest.json"
    write_json_atomic(manifest_path, manifest)
    receipt = {
        "protocol": PROTOCOL,
        "complete": len(records) == len(sources),
        "git_commit": git_commit(),
        "source_workbooks": len(sources),
        "selected_targets": len(targets),
        "split_targets": dict(sorted(split_targets.items())),
        "split_workbooks": {
            split: len(split_workbooks[split]) for split in EXPECTED_GROUPS
        },
        "split_structure_groups": {
            split: len(split_groups[split]) for split in EXPECTED_GROUPS
        },
        "visible_formula_candidates": sum(int(record["visible_formula_candidates"]) for record in records.values()),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "reachable_references": sum(int(target["reachable_references"]) for target in targets),
        "total_references": sum(int(target["total_references"]) for target in targets),
        "global_frequency_top5_train_only": global_top5,
        "target_manifest_sha256": sha256_file(manifest_path),
        "target_inventory_sha256": stable_hash(targets),
        "workbook_shards_sha256": stable_hash(
            [(path.name, sha256_file(path)) for path in sorted(shards.glob("*.json"))]
        ),
        "task_metadata_inputs": [],
        "answer_workbook_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
        "protected_data_inputs": [],
        "raw_inputs_logged": False,
        "embeddings_persisted": False,
        "internal_test_decoded": False,
    }
    receipt_path = output / "corpus_receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, default=DEFAULT_CORPUS_MANIFEST)
    parser.add_argument("--corpus-receipt", type=Path, default=DEFAULT_CORPUS_RECEIPT)
    parser.add_argument("--intake-manifest", type=Path, default=DEFAULT_INTAKE_MANIFEST)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--fortap-source", type=Path, default=DEFAULT_FORTAP_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = build(
            corpus_manifest=args.corpus_manifest,
            corpus_receipt=args.corpus_receipt,
            intake_manifest=args.intake_manifest,
            input_root=args.input_root,
            fortap_source=args.fortap_source,
            output=args.output,
            workers=args.workers,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"FCRL U1 corpus build refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
