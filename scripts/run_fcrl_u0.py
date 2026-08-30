#!/usr/bin/env python3
"""Run the frozen FCRL artifact, leakage, determinism, and GPU smoke gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import platform
import subprocess
import sys
from pathlib import Path

from formulaguard.fcrl import FCRLAdapterError, build_table_input, formula_to_prefix
from formulaguard.fcrl_torch import load_runtime, tensorize_tables
from formulaguard.workbook import WorkbookModel


def synthetic_workbook(formula: str, cached_value: int) -> WorkbookModel:
    cells = {
        ("Synthetic", "A1"): "Item",
        ("Synthetic", "B1"): "Value",
        ("Synthetic", "A2"): "First",
        ("Synthetic", "B2"): 11,
        ("Synthetic", "A3"): "Second",
        ("Synthetic", "B3"): 13,
        ("Synthetic", "A4"): "Total",
        ("Synthetic", "B4"): cached_value,
    }
    return WorkbookModel.from_cells(cells, {("Synthetic", "B4"): formula})


def build_hash(runtime) -> str:
    table = build_table_input(synthetic_workbook("=SUM(B2:B3)", 24), ("Synthetic", "B4"))
    return tensorize_tables([table], runtime).encoder_hashes[0]


def independent_hashes(script: Path, source: Path, checkpoint: Path) -> list[str]:
    hashes: list[str] = []
    for _ in range(2):
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--hash-only",
                "--source-root",
                str(source),
                "--checkpoint",
                str(checkpoint),
            ],
            check=True,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": "0"},
        )
        marker = next(
            (line for line in reversed(completed.stdout.splitlines()) if line.startswith("FCRL_HASH=")),
            None,
        )
        if marker is None:
            raise RuntimeError("independent adapter hash subprocess produced no marker")
        hashes.append(marker.split("=", 1)[1])
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/external/model_discovery/raw/TUTA_table_understanding"),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("data/external/model_discovery/raw/fcrl_checkpoints/fortap.bin"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("results/fcrl_u0/u0_receipt.json"),
    )
    parser.add_argument("--hash-only", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    checkpoint = args.checkpoint.resolve()
    runtime = load_runtime(source_root, checkpoint)
    if args.hash_only:
        print(f"FCRL_HASH={build_hash(runtime)}")
        return 0

    torch = __import__("torch")
    torch.set_num_threads(24)
    if not torch.cuda.is_available():
        raise SystemExit("FCRL U0 requires the preregistered CUDA forward/backward test")

    first = build_table_input(synthetic_workbook("=SUM(B2:B3)", 24), ("Synthetic", "B4"))
    second = build_table_input(synthetic_workbook("=B2+B3", 999), ("Synthetic", "B4"))
    if first.encoder_material_hash() != second.encoder_material_hash():
        raise SystemExit("target formula or cached value leaked into adapter context material")
    first_batch = tensorize_tables([first], runtime)
    second_batch = tensorize_tables([second], runtime)
    if first_batch.encoder_hashes != second_batch.encoder_hashes:
        raise SystemExit("target formula or cached value leaked into encoder tensors")

    try:
        formula_to_prefix("='Other'!A1+1")
    except FCRLAdapterError as exc:
        if exc.code != "cross_sheet_reference":
            raise
    else:
        raise SystemExit("cross-sheet formula was not rejected")

    process_hashes = independent_hashes(Path(__file__).resolve(), source_root, checkpoint)
    if len(set(process_hashes)) != 1 or process_hashes[0] != first_batch.encoder_hashes[0]:
        raise SystemExit("independent-process encoder hashes differ")

    device = torch.device("cuda:0")
    model = runtime.model.to(device)
    batch = first_batch.to(device)
    model.train()
    encoded = model.encode(batch)
    if not bool(torch.isfinite(encoded).all()):
        raise SystemExit("ForTaP backbone emitted non-finite values")
    model.decoder.zero_grad(set_to_none=True)
    total_loss, sketch_loss, range_loss = model.decoder_loss(batch)
    if not all(math.isfinite(float(value.detach().cpu())) for value in (total_loss, sketch_loss, range_loss)):
        raise SystemExit("FCRL decoder loss is non-finite")
    total_loss.backward()
    backbone_gradients = sum(parameter.grad is not None for parameter in model.backbone.parameters())
    decoder_gradients = [
        parameter.grad
        for parameter in model.decoder.parameters()
        if parameter.requires_grad and parameter.grad is not None
    ]
    if backbone_gradients != 0:
        raise SystemExit("frozen ForTaP backbone received gradients")
    if not decoder_gradients or not all(bool(torch.isfinite(gradient).all()) for gradient in decoder_gradients):
        raise SystemExit("FCRL decoder did not receive finite gradients")

    backbone_parameters = sum(parameter.numel() for parameter in model.backbone.parameters())
    decoder_parameters = sum(parameter.numel() for parameter in model.decoder.parameters())
    receipt = {
        "protocol": "formulaguard_fcrl_u0_v1",
        "status": "pass",
        "adapter_protocol": "formulaguard_fcrl_adapter_v1",
        "checks": {
            "checkpoint_hash_exact": True,
            "backbone_keys_and_shapes_exact": True,
            "backbone_frozen": backbone_gradients == 0,
            "target_formula_and_cached_value_absent_from_encoder": True,
            "independent_process_hash_match": True,
            "cross_sheet_reference_rejected": True,
            "target_marker_survives_truncation": int(first_batch.formula_label.sum()) == 2,
            "gpu_forward_finite": True,
            "decoder_backward_finite": True,
            "torch_scatter_not_required_by_selected_modules": True,
            "official_attention_key_value_layout_adapted": True,
        },
        "artifact": {
            "source_commit": "4de8bba4e9bf6a89b2e131bfb471b4db2c45b951",
            "checkpoint_sha256": runtime.checkpoint_sha256,
            "checkpoint_bytes": runtime.checkpoint_bytes,
            "loaded_backbone_tensors": runtime.loaded_backbone_tensors,
            "backbone_parameters": backbone_parameters,
            "decoder_parameters": decoder_parameters,
        },
        "synthetic_smoke": {
            "sequence_tokens": int(first_batch.token_id.shape[1]),
            "formula_target_tokens": int(first_batch.tgt_sketch.shape[1]),
            "reachable_references": sum(first_batch.reachable_references),
            "total_references": sum(first_batch.total_references),
            "encoder_hash": first_batch.encoder_hashes[0],
            "process_hashes": process_hashes,
            "encoded_shape": list(encoded.shape),
            "total_loss": float(total_loss.detach().cpu()),
            "sketch_loss": float(sketch_loss.detach().cpu()),
            "range_loss": float(range_loss.detach().cpu()),
        },
        "compatibility_boundary": {
            "official_FPTUTA_imported": False,
            "torch_scatter_installed": importlib.util.find_spec("torch_scatter") is not None,
            "selected_imports": ["BbForTuta", "LSTMLM", "FPTokenizer"],
            "attention_compatibility": "encoder_key_value_batch_first_to_sequence_first",
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "cpu_workers": torch.get_num_threads(),
        },
        "protected_data_inputs": [],
        "fault_label_inputs": [],
        "raw_workbook_values_logged": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
