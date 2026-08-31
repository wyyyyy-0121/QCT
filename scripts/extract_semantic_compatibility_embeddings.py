#!/usr/bin/env python3
"""Extract frozen ForTaP states for the semantic compatibility corpus."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch

from formulaguard.fcrl import build_masked_context_input
from formulaguard.fcrl_torch import (
    EXPECTED_CHECKPOINT_SHA256,
    EXPECTED_SOURCE_COMMIT,
    FCRLTensorBatch,
    FCRLTokenizerRuntime,
    load_runtime,
    load_tokenizer_runtime,
    tensorize_tables,
)
from formulaguard.semantic_compatibility import (
    canonical_formula_role,
    semantic_candidate_roles,
)
from formulaguard.semantic_compatibility_torch import frozen_context_states
from formulaguard.workbook import WorkbookModel
from scripts.build_fcrl_u1_corpus import (
    DEFAULT_CORPUS_MANIFEST,
    DEFAULT_CORPUS_RECEIPT,
    DEFAULT_FORTAP_SOURCE,
    DEFAULT_INPUT_ROOT,
    DEFAULT_INTAKE_MANIFEST,
    EXPECTED_GROUPS,
    load_sources,
    sha256_file,
    stable_hash,
    write_json_atomic,
)
from scripts.build_semantic_compatibility_corpus import (
    PROTOCOL as CORPUS_PROTOCOL,
    target_id,
)


PROTOCOL = "formulaguard_semantic_compatibility_embeddings_v1"
MAX_WORKERS = 24
GPU_BATCH_SIZE = 16
CONTEXT_SIZE = 768
DEFAULT_TARGET_MANIFEST = ROOT / "results/semantic_compatibility_corpus_v1/target_manifest.json"
DEFAULT_TARGET_RECEIPT = ROOT / "results/semantic_compatibility_corpus_v1/corpus_receipt.json"
DEFAULT_CHECKPOINT = ROOT / "data/external/model_discovery/raw/fcrl_checkpoints/fortap.bin"
DEFAULT_OUTPUT = ROOT / "results/semantic_compatibility_embeddings_v1"

_TOKENIZER_RUNTIME: FCRLTokenizerRuntime | None = None


def git_commit(path: Path = ROOT) -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_clean_tracked_worktree() -> None:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("tracked worktree must be clean before embedding extraction")


def atomic_torch_save(payload: object, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def load_target_contract(
    manifest_path: Path,
    receipt_path: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    receipt = json.loads(receipt_path.read_text(encoding="ascii"))
    if (
        receipt.get("protocol") != CORPUS_PROTOCOL
        or receipt.get("complete") is not True
        or receipt.get("target_manifest_sha256") != sha256_file(manifest_path)
        or receipt.get("protected_data_inputs") != []
        or receipt.get("fault_label_inputs") != []
        or receipt.get("answer_workbook_inputs") != []
        or receipt.get("raw_cell_text_persisted") is not False
        or receipt.get("raw_numeric_values_persisted") is not False
        or receipt.get("raw_formula_strings_persisted") is not False
    ):
        raise ValueError("semantic target receipt violates the embedding contract")
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    targets = manifest.get("targets")
    if manifest.get("protocol") != CORPUS_PROTOCOL or not isinstance(targets, list):
        raise ValueError("semantic target manifest is invalid")
    if manifest.get("target_inventory_sha256") != stable_hash(targets):
        raise ValueError("semantic target inventory hash changed")
    if receipt.get("target_inventory_sha256") != manifest["target_inventory_sha256"]:
        raise ValueError("semantic target receipt inventory hash changed")

    identifiers: set[str] = set()
    split_counts: Counter[str] = Counter()
    split_groups: dict[str, set[str]] = defaultdict(set)
    for target in targets:
        identifier = str(target.get("target_id", ""))
        workbook_id = str(target.get("workbook_id", ""))
        split = str(target.get("split", ""))
        group = str(target.get("structure_group", ""))
        sheet_index = target.get("sheet_index")
        address = target.get("address")
        role = target.get("role")
        candidates = target.get("local_candidate_roles")
        if (
            split not in EXPECTED_GROUPS
            or not workbook_id.startswith("fcrl-wb:")
            or not isinstance(sheet_index, int)
            or sheet_index < 0
            or not isinstance(address, str)
            or not address
            or identifier != target_id(workbook_id, sheet_index, address)
            or identifier in identifiers
            or not isinstance(role, str)
            or not role
            or hashlib.sha256(role.encode("utf-8")).hexdigest() != target.get("role_sha256")
            or not isinstance(candidates, list)
            or len(candidates) > 4
            or len(candidates) != len(set(candidates))
            or any(not isinstance(candidate, str) or not candidate for candidate in candidates)
        ):
            raise ValueError("semantic target row is invalid")
        identifiers.add(identifier)
        split_counts[split] += 1
        split_groups[split].add(group)
    observed_counts = dict(sorted(split_counts.items()))
    observed_groups = {split: len(split_groups[split]) for split in EXPECTED_GROUPS}
    if (
        len(targets) != receipt.get("selected_targets")
        or observed_counts != receipt.get("split_targets")
        or observed_groups != receipt.get("split_structure_groups")
    ):
        raise ValueError("semantic target split inventory changed")
    return manifest, targets


def _resolve_target_key(
    model: WorkbookModel,
    target: Mapping[str, object],
) -> tuple[str, str]:
    sheets = list(model.sheet_visibility)
    sheet_index = int(target["sheet_index"])
    if sheet_index < 0 or sheet_index >= len(sheets):
        raise ValueError("semantic target sheet ordinal changed")
    return sheets[sheet_index], str(target["address"])


def _init_worker(fortap_source: str) -> None:
    global _TOKENIZER_RUNTIME
    torch.set_num_threads(1)
    _TOKENIZER_RUNTIME = load_tokenizer_runtime(Path(fortap_source))


def _process_workbook(
    source: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if _TOKENIZER_RUNTIME is None:
        raise RuntimeError("semantic tokenizer worker is not initialized")
    model = WorkbookModel.from_xlsx(str(source["path"]))
    tables = []
    identifiers: list[str] = []
    batches: list[tuple[tuple[str, ...], FCRLTensorBatch]] = []
    for target in sorted(targets, key=lambda row: str(row["target_id"])):
        key = _resolve_target_key(model, target)
        if key not in model.formulas:
            raise ValueError("semantic target is no longer a formula")
        role = canonical_formula_role(model.formulas[key], key[1], key[0])
        if (
            role != target["role"]
            or hashlib.sha256(role.encode("utf-8")).hexdigest() != target["role_sha256"]
            or list(semantic_candidate_roles(model, key)) != target["local_candidate_roles"]
        ):
            raise ValueError("semantic formula role changed after corpus construction")
        tables.append(build_masked_context_input(model, key))
        identifiers.append(str(target["target_id"]))
        if len(tables) == GPU_BATCH_SIZE:
            batches.append((tuple(identifiers), tensorize_tables(tables, _TOKENIZER_RUNTIME)))
            tables, identifiers = [], []
    if tables:
        batches.append((tuple(identifiers), tensorize_tables(tables, _TOKENIZER_RUNTIME)))
    return {
        "workbook_id": source["workbook_id"],
        "target_ids": tuple(str(target["target_id"]) for target in sorted(
            targets, key=lambda row: str(row["target_id"])
        )),
        "batches": batches,
    }


def _shard_name(workbook_id: str) -> str:
    return hashlib.sha256(workbook_id.encode("utf-8")).hexdigest() + ".pt"


def _validate_embedding_payload(
    payload: object,
    expected_target_ids: Sequence[str],
) -> torch.Tensor:
    if not isinstance(payload, dict) or set(payload) != {
        "protocol",
        "target_ids",
        "context_states",
    }:
        raise ValueError("semantic embedding payload fields changed")
    target_ids = payload.get("target_ids")
    states = payload.get("context_states")
    if (
        payload.get("protocol") != PROTOCOL
        or not isinstance(target_ids, (list, tuple))
        or tuple(target_ids) != tuple(expected_target_ids)
        or not isinstance(states, torch.Tensor)
        or states.dtype != torch.float16
        or tuple(states.shape) != (len(expected_target_ids), CONTEXT_SIZE)
        or not bool(torch.isfinite(states).all())
    ):
        raise ValueError("semantic embedding payload is invalid")
    return states


def _completed_results(
    executor: concurrent.futures.ProcessPoolExecutor,
    tasks: Sequence[tuple[Mapping[str, object], Sequence[Mapping[str, object]]]],
    *,
    window: int,
) -> Iterable[dict[str, object]]:
    iterator = iter(tasks)
    pending: set[concurrent.futures.Future] = set()
    for _ in range(min(window, len(tasks))):
        source, targets = next(iterator)
        pending.add(executor.submit(_process_workbook, source, targets))
    while pending:
        done, pending = concurrent.futures.wait(
            pending,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            yield future.result()
            try:
                source, targets = next(iterator)
            except StopIteration:
                continue
            pending.add(executor.submit(_process_workbook, source, targets))


def extract(
    *,
    target_manifest: Path,
    target_receipt: Path,
    corpus_manifest: Path,
    corpus_receipt: Path,
    intake_manifest: Path,
    input_root: Path,
    fortap_source: Path,
    checkpoint: Path,
    output: Path,
    workers: int,
    resume: bool,
) -> Path:
    require_clean_tracked_worktree()
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    if not torch.cuda.is_available():
        raise ValueError("semantic embedding extraction requires CUDA")
    if sha256_file(checkpoint) != EXPECTED_CHECKPOINT_SHA256:
        raise ValueError("ForTaP checkpoint hash changed")
    if git_commit(fortap_source) != EXPECTED_SOURCE_COMMIT:
        raise ValueError("ForTaP source commit changed")

    _manifest, targets = load_target_contract(target_manifest, target_receipt)
    sources = load_sources(corpus_manifest, corpus_receipt, intake_manifest, input_root)
    sources_by_id = {str(source["workbook_id"]): source for source in sources}
    by_workbook: dict[str, list[dict[str, object]]] = defaultdict(list)
    for target in targets:
        workbook_id = str(target["workbook_id"])
        if workbook_id not in sources_by_id:
            raise ValueError("semantic target references an unavailable workbook")
        by_workbook[workbook_id].append(target)

    output = output.resolve()
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "target_manifest_sha256": sha256_file(target_manifest),
        "target_receipt_sha256": sha256_file(target_receipt),
        "checkpoint_sha256": EXPECTED_CHECKPOINT_SHA256,
        "fortap_source_commit": EXPECTED_SOURCE_COMMIT,
        "workers": workers,
        "gpu_batch_size": GPU_BATCH_SIZE,
        "selected_targets": len(targets),
        "protected_data_inputs": [],
        "fault_label_inputs": [],
        "answer_workbook_inputs": [],
        "raw_cell_text_persisted": False,
        "raw_numeric_values_persisted": False,
        "raw_formula_strings_persisted": False,
        "formula_roles_persisted": False,
    }
    metadata_path = output / "metadata.json"
    if output.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("semantic embedding output exists; pass --resume after audit")
        if json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
            raise ValueError("semantic embedding resume metadata differs")
    else:
        output.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    shards = output / "workbook_shards"
    shards.mkdir(exist_ok=True)

    expected_by_workbook = {
        workbook_id: tuple(sorted(str(target["target_id"]) for target in workbook_targets))
        for workbook_id, workbook_targets in by_workbook.items()
    }
    pending_tasks = []
    for workbook_id in sorted(by_workbook):
        shard = shards / _shard_name(workbook_id)
        if shard.exists():
            payload = torch.load(shard, map_location="cpu", weights_only=True)
            _validate_embedding_payload(payload, expected_by_workbook[workbook_id])
        else:
            pending_tasks.append((sources_by_id[workbook_id], by_workbook[workbook_id]))

    if pending_tasks:
        device = torch.device("cuda:0")
        runtime = load_runtime(fortap_source, checkpoint)
        runtime.model.to(device)
        runtime.model.eval()
        context = multiprocessing.get_context("spawn")
        completed = len(by_workbook) - len(pending_tasks)
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_init_worker,
            initargs=(str(fortap_source.resolve()),),
        ) as executor:
            for result in _completed_results(
                executor,
                pending_tasks,
                window=max(workers * 2, 1),
            ):
                workbook_id = str(result["workbook_id"])
                state_chunks = []
                observed_ids: list[str] = []
                for target_ids, cpu_batch in result["batches"]:  # type: ignore[union-attr]
                    states = frozen_context_states(runtime, cpu_batch.to(device))
                    state_chunks.append(states.to(device="cpu", dtype=torch.float16))
                    observed_ids.extend(target_ids)
                payload = {
                    "protocol": PROTOCOL,
                    "target_ids": tuple(observed_ids),
                    "context_states": torch.cat(state_chunks, dim=0),
                }
                _validate_embedding_payload(payload, expected_by_workbook[workbook_id])
                atomic_torch_save(payload, shards / _shard_name(workbook_id))
                completed += 1
                if completed % 25 == 0 or completed == len(by_workbook):
                    print(
                        f"semantic embeddings workbooks {completed}/{len(by_workbook)}",
                        flush=True,
                    )

    observed_shards = {path.name for path in shards.glob("*.pt")}
    expected_shards = {_shard_name(workbook_id) for workbook_id in by_workbook}
    if observed_shards != expected_shards:
        raise ValueError("semantic embedding shard inventory changed")
    identifiers: list[str] = []
    rows: list[torch.Tensor] = []
    for workbook_id in sorted(by_workbook):
        shard = shards / _shard_name(workbook_id)
        payload = torch.load(shard, map_location="cpu", weights_only=True)
        states = _validate_embedding_payload(payload, expected_by_workbook[workbook_id])
        identifiers.extend(payload["target_ids"])
        rows.extend(states.unbind(0))
    order = sorted(range(len(identifiers)), key=identifiers.__getitem__)
    ordered_ids = tuple(identifiers[index] for index in order)
    expected_ids = tuple(sorted(str(target["target_id"]) for target in targets))
    if ordered_ids != expected_ids:
        raise ValueError("semantic embedding target inventory changed")
    consolidated = {
        "protocol": PROTOCOL,
        "target_ids": ordered_ids,
        "context_states": torch.stack([rows[index] for index in order]),
    }
    _validate_embedding_payload(consolidated, expected_ids)
    embeddings_path = output / "embeddings.pt"
    atomic_torch_save(consolidated, embeddings_path)
    receipt = {
        **metadata,
        "complete": True,
        "workbooks_with_embeddings": len(by_workbook),
        "context_state_shape": list(consolidated["context_states"].shape),
        "context_state_dtype": str(consolidated["context_states"].dtype),
        "context_states_finite": True,
        "embeddings_sha256": sha256_file(embeddings_path),
        "workbook_shards_sha256": stable_hash([
            (path.name, sha256_file(path)) for path in sorted(shards.glob("*.pt"))
        ]),
        "persisted_payload_fields": ["target_ids", "context_states"],
        "target_formula_tokens_entered_context_encoder": False,
    }
    receipt_path = output / "receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-manifest", type=Path, default=DEFAULT_TARGET_MANIFEST)
    parser.add_argument("--target-receipt", type=Path, default=DEFAULT_TARGET_RECEIPT)
    parser.add_argument("--corpus-manifest", type=Path, default=DEFAULT_CORPUS_MANIFEST)
    parser.add_argument("--corpus-receipt", type=Path, default=DEFAULT_CORPUS_RECEIPT)
    parser.add_argument("--intake-manifest", type=Path, default=DEFAULT_INTAKE_MANIFEST)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--fortap-source", type=Path, default=DEFAULT_FORTAP_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = extract(
            target_manifest=args.target_manifest,
            target_receipt=args.target_receipt,
            corpus_manifest=args.corpus_manifest,
            corpus_receipt=args.corpus_receipt,
            intake_manifest=args.intake_manifest,
            input_root=args.input_root,
            fortap_source=args.fortap_source,
            checkpoint=args.checkpoint,
            output=args.output,
            workers=args.workers,
            resume=args.resume,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(f"semantic embedding extraction refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
