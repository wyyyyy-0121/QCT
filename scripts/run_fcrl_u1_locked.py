#!/usr/bin/env python3
"""Run the frozen FCRL U1 internal test twice in independent processes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import torch

from formulaguard.fcrl_torch import generate_prefix_beam, load_runtime
from formulaguard.fcrl_u1 import prediction_content, sha256_file, stable_hash
from scripts.build_fcrl_u1_corpus import load_sources, write_json_atomic
from scripts.score_fcrl_u1 import (
    PREDICTION_PROTOCOL,
    load_prediction_file,
    score,
    verify_candidate_lock,
)
from scripts.train_fcrl_u1 import (
    configure_determinism,
    iter_batches,
    load_target_contract,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_fcrl_u1_locked_runner_v1"
DEFAULT_LOCK = ROOT / "research/V5_FCRL_U1_CANDIDATE_LOCK.json"
DEFAULT_OUTPUT = ROOT / "results/fcrl_u1_internal_test_v1"


def _artifact_path(candidate: dict[str, object], name: str) -> Path:
    artifacts = candidate["artifacts"]
    assert isinstance(artifacts, dict)
    record = artifacts[name]
    assert isinstance(record, dict)
    return (ROOT / str(record["path"])).resolve()


def _source_path(candidate: dict[str, object], name: str) -> Path:
    source_paths = candidate["source_paths"]
    assert isinstance(source_paths, dict)
    return (ROOT / str(source_paths[name])).resolve()


@torch.no_grad()
def run_worker(candidate_lock: Path, output: Path) -> Path:
    if output.exists():
        raise ValueError("FCRL worker prediction output already exists")
    candidate = verify_candidate_lock(candidate_lock)
    configure_determinism()
    if not torch.cuda.is_available():
        raise ValueError("FCRL U1 locked inference requires CUDA")
    target_manifest = _artifact_path(candidate, "target_manifest")
    target_receipt = _artifact_path(candidate, "target_receipt")
    manifest, targets = load_target_contract(target_manifest, target_receipt)
    del manifest
    internal_targets = [target for target in targets if target["split"] == "internal_test"]
    if not internal_targets:
        raise ValueError("FCRL target manifest has no internal-test targets")
    sources = load_sources(
        _artifact_path(candidate, "corpus_manifest"),
        _artifact_path(candidate, "corpus_receipt"),
        _artifact_path(candidate, "intake_manifest"),
        _source_path(candidate, "input_root"),
    )
    sources_by_id = {str(source["workbook_id"]): source for source in sources}
    runtime = load_runtime(
        _source_path(candidate, "fortap_source"),
        _artifact_path(candidate, "base_checkpoint"),
    )
    decoder_state = torch.load(
        _artifact_path(candidate, "selected_decoder"),
        map_location="cpu",
        weights_only=True,
    )
    runtime.model.decoder.load_state_dict(decoder_state, strict=True)
    device = torch.device("cuda:0")
    runtime.model.to(device)
    runtime.model.eval()

    rows: list[dict[str, object]] = []
    completed = 0
    for cpu_batch, records in iter_batches(
        internal_targets, sources_by_id, runtime, epoch=None
    ):
        batch = cpu_batch.to(device)
        encoded = runtime.model.encode(batch)
        for index, record in enumerate(records):
            predictions = [
                item.key
                for item in generate_prefix_beam(
                    runtime,
                    batch,
                    sample_index=index,
                    encoded_states=encoded,
                )
            ]
            rows.append({"target_id": record["target_id"], "predictions": predictions})
        completed += len(records)
        if completed % 250 == 0 or completed == len(internal_targets):
            print(
                f"FCRL locked inference decoded {completed}/{len(internal_targets)}",
                flush=True,
            )
    torch.cuda.synchronize(device)
    content = prediction_content(rows)
    payload = {
        "protocol": PREDICTION_PROTOCOL,
        "complete": True,
        "candidate_id": candidate["candidate_id"],
        "targets": len(content),
        "prediction_sha256": stable_hash(content),
        "predictions": content,
        "internal_test_only": True,
        "protected_data_inputs": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output, payload)
    return output


def run_locked(candidate_lock: Path, output: Path, *, resume: bool) -> Path:
    candidate = verify_candidate_lock(candidate_lock)
    metadata = {
        "protocol": PROTOCOL,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256_file(candidate_lock),
        "independent_processes": 2,
        "protected_data_inputs": [],
    }
    metadata_path = output / "metadata.json"
    if output.exists():
        if (
            not resume
            or not metadata_path.is_file()
            or json.loads(metadata_path.read_text(encoding="ascii")) != metadata
        ):
            raise ValueError("FCRL locked output exists or resume metadata changed")
    else:
        output.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    score_path = output / "u1_score.json"
    if score_path.exists():
        raise ValueError("FCRL U1 has already received its final complete score")

    prediction_paths = [
        output / "run_1_predictions.json",
        output / "run_2_predictions.json",
    ]
    for prediction_path in prediction_paths:
        if prediction_path.exists():
            load_prediction_file(prediction_path, str(candidate["candidate_id"]))
            continue
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = "0"
        environment.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        subprocess.run(
            (
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--candidate-lock",
                str(candidate_lock.resolve()),
                "--predictions-output",
                str(prediction_path.resolve()),
            ),
            cwd=ROOT,
            env=environment,
            check=True,
        )
    result = score(candidate_lock, prediction_paths[0], prediction_paths[1])
    write_json_atomic(score_path, result)
    return score_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--predictions-output", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.worker:
            if args.predictions_output is None:
                raise ValueError("FCRL worker requires a prediction output")
            result = run_worker(args.candidate_lock, args.predictions_output)
        else:
            if args.predictions_output is not None:
                raise ValueError("prediction output is reserved for the FCRL worker")
            result = run_locked(args.candidate_lock, args.output, resume=args.resume)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"FCRL U1 locked inference refused: {exc}") from exc
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
