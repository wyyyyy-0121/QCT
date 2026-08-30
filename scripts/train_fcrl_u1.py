#!/usr/bin/env python3
"""Train the frozen FCRL decoder and select it on calibration groups only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import torch

from formulaguard.fcrl import build_table_input
from formulaguard.fcrl_torch import (
    FCRLRuntime,
    FCRLTensorBatch,
    generate_prefix_beam,
    load_runtime,
    tensorize_tables,
)
from formulaguard.fcrl_u1 import prediction_metrics
from formulaguard.workbook import WorkbookModel
from scripts.build_fcrl_u1_corpus import (
    DEFAULT_CORPUS_MANIFEST,
    DEFAULT_CORPUS_RECEIPT,
    DEFAULT_INPUT_ROOT,
    DEFAULT_INTAKE_MANIFEST,
    DEFAULT_FORTAP_SOURCE,
    EXPECTED_GROUPS,
    load_sources,
    sha256_file,
    stable_hash,
    write_json_atomic,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_fcrl_u1_training_v1"
SEED = 260831
BATCH_SIZE = 8
LEARNING_RATE = 2e-4
WEIGHT_DECAY = 0.01
GRADIENT_CLIP = 1.0
MAX_EPOCHS = 15
PATIENCE = 2
CPU_WORKERS = 24

DEFAULT_TARGET_MANIFEST = ROOT / "results/fcrl_u1_corpus_v1/target_manifest.json"
DEFAULT_TARGET_RECEIPT = ROOT / "results/fcrl_u1_corpus_v1/corpus_receipt.json"
DEFAULT_CHECKPOINT = ROOT / "data/external/model_discovery/raw/fcrl_checkpoints/fortap.bin"
DEFAULT_OUTPUT = ROOT / "results/fcrl_u1_training_v1"


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
        raise ValueError("tracked worktree must be clean before FCRL training")


def configure_determinism() -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ["PYTHONHASHSEED"] = "0"
    random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.set_num_threads(CPU_WORKERS)


def atomic_torch_save(payload: object, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def load_target_contract(manifest_path: Path, receipt_path: Path) -> tuple[dict, list[dict]]:
    receipt = json.loads(receipt_path.read_text(encoding="ascii"))
    if (
        receipt.get("protocol") != "formulaguard_fcrl_u1_corpus_v1"
        or receipt.get("complete") is not True
        or receipt.get("target_manifest_sha256") != sha256_file(manifest_path)
        or receipt.get("protected_data_inputs") != []
        or receipt.get("answer_workbook_inputs") != []
        or receipt.get("fault_label_inputs") != []
        or receipt.get("v4_rank_inputs") != []
        or receipt.get("raw_inputs_logged") is not False
        or receipt.get("embeddings_persisted") is not False
        or receipt.get("internal_test_decoded") is not False
    ):
        raise ValueError("FCRL target corpus receipt is incomplete or unsafe")
    if receipt.get("split_structure_groups") != EXPECTED_GROUPS:
        raise ValueError("one or more frozen FCRL structure groups has no retained target")
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    targets = manifest.get("targets")
    if (
        manifest.get("protocol") != "formulaguard_fcrl_u1_corpus_v1"
        or not isinstance(targets, list)
        or len(targets) != receipt.get("selected_targets")
        or receipt.get("target_inventory_sha256") != stable_hash(targets)
    ):
        raise ValueError("FCRL target manifest count mismatch")
    global_top5 = manifest.get("global_frequency_top5_train_only")
    if (
        not isinstance(global_top5, list)
        or len(global_top5) > 5
        or len(global_top5) != len(set(global_top5))
        or any(not isinstance(value, str) or not value for value in global_top5)
        or receipt.get("global_frequency_top5_train_only") != global_top5
    ):
        raise ValueError("FCRL train-only global baseline is invalid")
    target_ids = [str(target["target_id"]) for target in targets]
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("FCRL target IDs are not unique")
    split_counts: Counter[str] = Counter()
    split_groups: dict[str, set[str]] = defaultdict(set)
    for target in targets:
        split = str(target.get("split", ""))
        local = target.get("local_peer_top5")
        reachable = target.get("reachable_references")
        total = target.get("total_references")
        if (
            split not in EXPECTED_GROUPS
            or not str(target.get("target_id", "")).startswith("fcrl-target:")
            or not str(target.get("workbook_id", "")).startswith("fcrl-wb:")
            or not isinstance(target.get("gold_key"), str)
            or not target["gold_key"]
            or not isinstance(local, list)
            or len(local) > 5
            or len(local) != len(set(local))
            or any(not isinstance(value, str) or not value for value in local)
            or not isinstance(reachable, int)
            or not isinstance(total, int)
            or total <= 0
            or reachable < 0
            or reachable > total
            or not isinstance(target.get("sheet_index"), int)
            or int(target["sheet_index"]) < 0
            or not isinstance(target.get("address"), str)
            or not target["address"]
            or len(str(target.get("encoder_hash", ""))) != 64
        ):
            raise ValueError("FCRL target manifest row is invalid")
        split_counts[split] += 1
        split_groups[split].add(str(target["structure_group"]))
    if dict(split_counts) != receipt.get("split_targets") or {
        split: len(split_groups[split]) for split in EXPECTED_GROUPS
    } != EXPECTED_GROUPS:
        raise ValueError("FCRL target split counts or group coverage changed")
    return manifest, targets


def _resolve_target_key(model: WorkbookModel, target: Mapping[str, object]) -> tuple[str, str]:
    sheets = list(model.sheet_visibility)
    sheet_index = int(target["sheet_index"])
    if sheet_index < 0 or sheet_index >= len(sheets):
        raise ValueError("FCRL target sheet ordinal changed")
    return sheets[sheet_index], str(target["address"])


def iter_batches(
    targets: Sequence[dict],
    sources_by_id: Mapping[str, Mapping[str, object]],
    runtime: FCRLRuntime,
    *,
    epoch: int | None,
) -> Iterable[tuple[FCRLTensorBatch, list[dict]]]:
    by_workbook: dict[str, list[dict]] = defaultdict(list)
    for target in targets:
        by_workbook[str(target["workbook_id"])].append(target)
    workbook_ids = sorted(by_workbook)
    rng = random.Random(SEED + epoch) if epoch is not None else None
    if rng is not None:
        rng.shuffle(workbook_ids)
    tables = []
    records: list[dict] = []
    for workbook_id in workbook_ids:
        source = sources_by_id.get(workbook_id)
        if source is None:
            raise ValueError("FCRL target references an unavailable source workbook")
        model = WorkbookModel.from_xlsx(str(source["path"]))
        workbook_targets = sorted(by_workbook[workbook_id], key=lambda row: str(row["target_id"]))
        if rng is not None:
            rng.shuffle(workbook_targets)
        for target in workbook_targets:
            table = build_table_input(model, _resolve_target_key(model, target))
            tables.append(table)
            records.append(target)
            if len(tables) == BATCH_SIZE:
                batch = tensorize_tables(tables, runtime)
                if list(batch.encoder_hashes) != [str(row["encoder_hash"]) for row in records]:
                    raise ValueError("FCRL encoder hash changed after corpus freeze")
                yield batch, records
                tables, records = [], []
    if tables:
        batch = tensorize_tables(tables, runtime)
        if list(batch.encoder_hashes) != [str(row["encoder_hash"]) for row in records]:
            raise ValueError("FCRL encoder hash changed after corpus freeze")
        yield batch, records


@torch.no_grad()
def evaluate_calibration(
    targets: Sequence[dict],
    sources_by_id: Mapping[str, Mapping[str, object]],
    runtime: FCRLRuntime,
    global_top5: Sequence[str],
    device: torch.device,
) -> tuple[dict[str, object], str]:
    runtime.model.eval()
    rows: list[dict[str, object]] = []
    completed = 0
    for cpu_batch, records in iter_batches(targets, sources_by_id, runtime, epoch=None):
        batch = cpu_batch.to(device)
        encoded = runtime.model.encode(batch)
        for index, record in enumerate(records):
            beam = generate_prefix_beam(
                runtime,
                batch,
                sample_index=index,
                encoded_states=encoded,
            )
            predictions = [item.key for item in beam]
            gold = str(record["gold_key"])
            local = [str(value) for value in record["local_peer_top5"]]
            rows.append(
                {
                    "target_id": record["target_id"],
                    "workbook_id": record["workbook_id"],
                    "structure_group": record["structure_group"],
                    "predictions": predictions,
                    "model_top1": bool(predictions and predictions[0] == gold),
                    "model_top5": gold in predictions[:5],
                    "global_top5": gold in global_top5,
                    "local_peer_top5": gold in local[:5],
                }
            )
        completed += len(records)
        if completed % 250 == 0 or completed == len(targets):
            print(f"FCRL calibration decoded {completed}/{len(targets)}", flush=True)
    prediction_payload = [
        {"target_id": row["target_id"], "predictions": row["predictions"]}
        for row in sorted(rows, key=lambda row: str(row["target_id"]))
    ]
    return prediction_metrics(rows), stable_hash(prediction_payload)


def decoder_cpu_state(runtime: FCRLRuntime) -> dict[str, torch.Tensor]:
    return {
        key: value.detach().cpu().clone()
        for key, value in runtime.model.decoder.state_dict().items()
    }


def train(
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
    resume: bool,
) -> Path:
    require_clean_tracked_worktree()
    configure_determinism()
    if not torch.cuda.is_available():
        raise ValueError("FCRL U1 training requires CUDA")
    manifest, targets = load_target_contract(target_manifest, target_receipt)
    sources = load_sources(corpus_manifest, corpus_receipt, intake_manifest, input_root)
    sources_by_id = {str(source["workbook_id"]): source for source in sources}
    if {str(target["workbook_id"]) for target in targets} - set(sources_by_id):
        raise ValueError("FCRL target manifest contains an unknown workbook")
    train_targets = [target for target in targets if target["split"] == "train"]
    calibration_targets = [target for target in targets if target["split"] == "calibration"]
    if any(target["split"] == "internal_test" for target in train_targets + calibration_targets):
        raise ValueError("internal-test target entered FCRL training")
    global_top5 = [str(value) for value in manifest["global_frequency_top5_train_only"]]

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "target_manifest_sha256": sha256_file(target_manifest),
        "target_receipt_sha256": sha256_file(target_receipt),
        "train_targets": len(train_targets),
        "calibration_targets": len(calibration_targets),
        "batch_size": BATCH_SIZE,
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "gradient_clip": GRADIENT_CLIP,
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "seed": SEED,
        "internal_test_inputs": [],
        "answer_workbook_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
        "protected_data_inputs": [],
        "embeddings_persisted": False,
    }
    metadata_path = output / "metadata.json"
    if metadata_path.exists():
        if not resume or json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
            raise ValueError("FCRL training output exists or resume metadata differs")
    else:
        if any(output.iterdir()):
            raise ValueError("nonempty FCRL training output has no matching metadata")
        write_json_atomic(metadata_path, metadata)

    device = torch.device("cuda:0")
    runtime = load_runtime(fortap_source, checkpoint)
    runtime.model.to(device)
    optimizer = torch.optim.AdamW(
        runtime.model.decoder.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    last_checkpoint = output / "last_complete_epoch.pt"
    selected_decoder = output / "selected_decoder.bin"
    history: list[dict[str, object]] = []
    best_metric = -1.0
    best_epoch = 0
    stale_epochs = 0
    start_epoch = 1
    if resume:
        if not last_checkpoint.is_file():
            raise ValueError("FCRL resume requested without a complete epoch checkpoint")
        state = torch.load(last_checkpoint, map_location=device, weights_only=False)
        if (
            state.get("protocol") != PROTOCOL
            or state.get("git_commit") != metadata["git_commit"]
            or state.get("target_manifest_sha256") != metadata["target_manifest_sha256"]
        ):
            raise ValueError("FCRL epoch checkpoint identity mismatch")
        runtime.model.decoder.load_state_dict(state["decoder"], strict=True)
        optimizer.load_state_dict(state["optimizer"])
        history = list(state["history"])
        best_metric = float(state["best_metric"])
        best_epoch = int(state["best_epoch"])
        stale_epochs = int(state["stale_epochs"])
        start_epoch = int(state["epoch"]) + 1
        torch.set_rng_state(state["torch_rng_cpu"].cpu())
        torch.cuda.set_rng_state_all([value.cpu() for value in state["torch_rng_cuda"]])
        if stale_epochs >= PATIENCE or start_epoch > MAX_EPOCHS:
            raise ValueError("FCRL training is already complete and cannot be resumed")

    for epoch in range(start_epoch, MAX_EPOCHS + 1):
        runtime.model.train()
        started = time.monotonic()
        total_loss = total_sketch = total_range = 0.0
        trained_targets = batches = 0
        for cpu_batch, records in iter_batches(
            train_targets, sources_by_id, runtime, epoch=epoch
        ):
            batch = cpu_batch.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss, sketch_loss, range_loss = runtime.model.decoder_loss(batch)
            if not bool(torch.isfinite(loss)):
                raise ValueError("FCRL training loss became non-finite")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(runtime.model.decoder.parameters(), GRADIENT_CLIP)
            optimizer.step()
            count = len(records)
            trained_targets += count
            batches += 1
            total_loss += float(loss.detach().cpu()) * count
            total_sketch += float(sketch_loss.detach().cpu()) * count
            total_range += float(range_loss.detach().cpu()) * count
            if batches % 100 == 0:
                print(
                    f"FCRL epoch {epoch}: batches={batches}; targets={trained_targets}/"
                    f"{len(train_targets)}; mean_loss={total_loss / trained_targets:.6f}",
                    flush=True,
                )
        if trained_targets != len(train_targets):
            raise ValueError("FCRL epoch did not consume every train target")

        calibration_metrics, calibration_hash = evaluate_calibration(
            calibration_targets, sources_by_id, runtime, global_top5, device
        )
        metric = float(calibration_metrics["structure_group_macro"]["model_top5"])
        improved = metric > best_metric
        if improved:
            best_metric = metric
            best_epoch = epoch
            stale_epochs = 0
            atomic_torch_save(decoder_cpu_state(runtime), selected_decoder)
        else:
            stale_epochs += 1
        epoch_record = {
            "epoch": epoch,
            "train_targets": trained_targets,
            "train_batches": batches,
            "mean_total_loss": total_loss / trained_targets,
            "mean_sketch_loss": total_sketch / trained_targets,
            "mean_range_loss": total_range / trained_targets,
            "calibration": calibration_metrics,
            "calibration_prediction_sha256": calibration_hash,
            "improved": improved,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        history.append(epoch_record)
        checkpoint_payload = {
            "protocol": PROTOCOL,
            "git_commit": metadata["git_commit"],
            "target_manifest_sha256": metadata["target_manifest_sha256"],
            "epoch": epoch,
            "decoder": decoder_cpu_state(runtime),
            "optimizer": optimizer.state_dict(),
            "history": history,
            "best_metric": best_metric,
            "best_epoch": best_epoch,
            "stale_epochs": stale_epochs,
            "torch_rng_cpu": torch.get_rng_state(),
            "torch_rng_cuda": torch.cuda.get_rng_state_all(),
        }
        atomic_torch_save(checkpoint_payload, last_checkpoint)
        progress = {
            **metadata,
            "complete": stale_epochs >= PATIENCE or epoch == MAX_EPOCHS,
            "epochs_completed": epoch,
            "best_epoch": best_epoch,
            "best_calibration_structure_group_macro_top5": best_metric,
            "stale_epochs": stale_epochs,
            "history": history,
            "selected_decoder_sha256": sha256_file(selected_decoder),
            "selected_decoder_bytes": selected_decoder.stat().st_size,
            "internal_test_decoded": False,
        }
        write_json_atomic(output / "training_receipt.json", progress)
        print(
            f"FCRL epoch {epoch} complete: calibration_group_macro_top5={metric:.6f}; "
            f"best_epoch={best_epoch}; stale={stale_epochs}",
            flush=True,
        )
        if stale_epochs >= PATIENCE:
            break
    return output / "training_receipt.json"


def _parser() -> argparse.ArgumentParser:
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
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = train(
            target_manifest=args.target_manifest,
            target_receipt=args.target_receipt,
            corpus_manifest=args.corpus_manifest,
            corpus_receipt=args.corpus_receipt,
            intake_manifest=args.intake_manifest,
            input_root=args.input_root,
            fortap_source=args.fortap_source,
            checkpoint=args.checkpoint,
            output=args.output,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"FCRL U1 training refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
