#!/usr/bin/env python3
"""Freeze and test a high-confidence semantic compatibility selector."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch

from formulaguard.semantic_compatibility_torch import SemanticCompatibilityHead
from scripts.build_fcrl_u1_corpus import sha256_file, write_json_atomic
from scripts.extract_semantic_compatibility_embeddings import load_target_contract
from scripts.train_semantic_compatibility import (
    DEFAULT_EMBEDDING_RECEIPT,
    DEFAULT_EMBEDDINGS,
    DEFAULT_TARGET_MANIFEST,
    DEFAULT_TARGET_RECEIPT,
    DEFAULT_VOCABULARY,
    _batch_tensors,
    build_examples,
    load_embeddings,
    load_vocabulary,
)
from scripts.train_semantic_compatibility import (
    PROTOCOL as TRAINING_PROTOCOL,
)

PROTOCOL = "formulaguard_semantic_compatibility_selective_v1"
MIN_CALIBRATION_ACTIONS = 100
MIN_CALIBRATION_COVERAGE = 0.08
MIN_CALIBRATION_ACCURACY = 0.75
MIN_CALIBRATION_WILSON_LOWER = 0.70
MIN_CALIBRATION_DELTA = 0.20
MIN_CALIBRATION_GROUPS = 8
MIN_INTERNAL_ACTIONS = 80
MIN_INTERNAL_COVERAGE = 0.05
MIN_INTERNAL_ACCURACY = 0.70
MIN_INTERNAL_WILSON_LOWER = 0.60
MIN_INTERNAL_DELTA = 0.10
MIN_INTERNAL_GROUPS = 8

DEFAULT_TRAINING_RECEIPT = ROOT / "results/semantic_compatibility_training_v2/receipt.json"
DEFAULT_SELECTED_MODEL = ROOT / "results/semantic_compatibility_training_v2/selected_model.pt"
DEFAULT_OUTPUT = ROOT / "results/semantic_compatibility_selective_v1"


@dataclass(frozen=True)
class SelectiveRow:
    structure_group: str
    margin: float
    model_correct: bool
    frequency_correct: bool


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
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
        raise ValueError("tracked worktree must be clean before selective scoring")


def wilson_interval(successes: int, total: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    if total < 1 or successes < 0 or successes > total:
        raise ValueError("invalid Wilson interval counts")
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    ) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


@torch.no_grad()
def score_rows(
    head: SemanticCompatibilityHead,
    examples,
    context_states: torch.Tensor,
    embedding_indices: Mapping[str, int],
    train_frequency: Mapping[str, int],
    device: torch.device,
) -> list[SelectiveRow]:
    head.eval()
    rows = []
    batch_size = 128
    for start in range(0, len(examples), batch_size):
        batch_examples = examples[start : start + batch_size]
        (
            context,
            _correct_tokens,
            _correct_lengths,
            _role_ids,
            candidate_tokens,
            candidate_lengths,
            candidate_mask,
            _gold_indices,
        ) = _batch_tensors(batch_examples, context_states, embedding_indices, device)
        logits = head.candidate_logits(
            context,
            candidate_tokens,
            candidate_lengths,
            candidate_mask,
        )
        for index, example in enumerate(batch_examples):
            candidate_count = len(example.candidate_roles)
            if candidate_count < 2:
                continue
            scores = logits[index, :candidate_count]
            order = torch.argsort(scores, descending=True, stable=True)
            predicted_index = int(order[0].item())
            frequency_prediction = min(
                example.candidate_roles,
                key=lambda role: (-int(train_frequency.get(role, 0)), role),
            )
            rows.append(SelectiveRow(
                structure_group=example.structure_group,
                margin=float((scores[order[0]] - scores[order[1]]).item()),
                model_correct=predicted_index == example.gold_index,
                frequency_correct=frequency_prediction == example.role,
            ))
    if not rows:
        raise ValueError("selective semantic scoring has no eligible cases")
    return rows


def summarize(rows: Sequence[SelectiveRow], threshold: float) -> dict[str, object]:
    selected = [row for row in rows if row.margin >= threshold]
    actions = len(selected)
    model_successes = sum(row.model_correct for row in selected)
    frequency_successes = sum(row.frequency_correct for row in selected)
    accuracy = model_successes / actions if actions else 0.0
    frequency_accuracy = frequency_successes / actions if actions else 0.0
    interval = wilson_interval(model_successes, actions) if actions else (0.0, 0.0)
    return {
        "eligible_cases": len(rows),
        "threshold": threshold,
        "actions": actions,
        "coverage": actions / len(rows),
        "accuracy": accuracy,
        "accuracy_wilson_95ci": list(interval),
        "train_frequency_accuracy": frequency_accuracy,
        "accuracy_delta_over_train_frequency": accuracy - frequency_accuracy,
        "structure_groups": len({row.structure_group for row in selected}),
    }


def calibration_gates(summary: Mapping[str, object]) -> dict[str, bool]:
    interval = summary["accuracy_wilson_95ci"]
    return {
        "at_least_100_actions": int(summary["actions"]) >= MIN_CALIBRATION_ACTIONS,
        "coverage_at_least_8pct": float(summary["coverage"]) >= MIN_CALIBRATION_COVERAGE,
        "accuracy_at_least_75pct": float(summary["accuracy"]) >= MIN_CALIBRATION_ACCURACY,
        "wilson_lower_bound_at_least_70pct": float(interval[0]) >= MIN_CALIBRATION_WILSON_LOWER,
        "delta_over_train_frequency_at_least_20pp": float(
            summary["accuracy_delta_over_train_frequency"]
        ) >= MIN_CALIBRATION_DELTA,
        "at_least_8_structure_groups": int(summary["structure_groups"]) >= MIN_CALIBRATION_GROUPS,
    }


def internal_gates(summary: Mapping[str, object]) -> dict[str, bool]:
    interval = summary["accuracy_wilson_95ci"]
    return {
        "at_least_80_actions": int(summary["actions"]) >= MIN_INTERNAL_ACTIONS,
        "coverage_at_least_5pct": float(summary["coverage"]) >= MIN_INTERNAL_COVERAGE,
        "accuracy_at_least_70pct": float(summary["accuracy"]) >= MIN_INTERNAL_ACCURACY,
        "wilson_lower_bound_at_least_60pct": float(interval[0]) >= MIN_INTERNAL_WILSON_LOWER,
        "delta_over_train_frequency_at_least_10pp": float(
            summary["accuracy_delta_over_train_frequency"]
        ) >= MIN_INTERNAL_DELTA,
        "at_least_8_structure_groups": int(summary["structure_groups"]) >= MIN_INTERNAL_GROUPS,
    }


def select_threshold(rows: Sequence[SelectiveRow]) -> tuple[dict[str, object], dict[str, bool]]:
    candidates = []
    for threshold in sorted({row.margin for row in rows}, reverse=True):
        summary = summarize(rows, threshold)
        gates = calibration_gates(summary)
        if all(gates.values()):
            candidates.append((summary, gates))
    if not candidates:
        fallback = summarize(rows, max(row.margin for row in rows))
        return fallback, calibration_gates(fallback)
    return max(
        candidates,
        key=lambda item: (
            int(item[0]["actions"]),
            float(item[0]["accuracy_wilson_95ci"][0]),
            float(item[0]["threshold"]),
        ),
    )


def score(
    *,
    target_manifest: Path,
    target_receipt: Path,
    vocabulary_path: Path,
    embeddings_path: Path,
    embedding_receipt: Path,
    training_receipt_path: Path,
    selected_model_path: Path,
    output: Path,
) -> Path:
    require_clean_tracked_worktree()
    if not torch.cuda.is_available():
        raise ValueError("selective semantic scoring requires CUDA")
    if output.exists():
        raise ValueError("selective semantic output already exists; internal test cannot be repeated")
    output.mkdir(parents=True)

    training_receipt = json.loads(training_receipt_path.read_text(encoding="ascii"))
    if (
        training_receipt.get("protocol") != TRAINING_PROTOCOL
        or training_receipt.get("complete") is not True
        or training_receipt.get("internal_test_evaluated") is not False
        or training_receipt.get("selected_model_sha256") != sha256_file(selected_model_path)
        or training_receipt.get("protected_data_inputs") != []
        or training_receipt.get("fault_label_inputs") != []
        or training_receipt.get("v4_rank_inputs") != []
    ):
        raise ValueError("semantic training receipt violates the selective contract")
    _manifest, targets = load_target_contract(target_manifest, target_receipt)
    vocabulary = load_vocabulary(vocabulary_path, target_receipt)
    target_ids = [str(target["target_id"]) for target in targets]
    embedding_ids, context_states = load_embeddings(
        embeddings_path,
        embedding_receipt,
        target_manifest,
        target_receipt,
        target_ids,
    )
    embedding_indices = {identifier: index for index, identifier in enumerate(embedding_ids)}
    train_targets = [target for target in targets if target["split"] == "train"]
    calibration_targets = [target for target in targets if target["split"] == "calibration"]
    train_frequency = Counter(str(target["role"]) for target in train_targets)
    role_ids = {role: index for index, role in enumerate(sorted(train_frequency))}
    calibration_examples = build_examples(calibration_targets, vocabulary, role_ids)

    device = torch.device("cuda:0")
    head = SemanticCompatibilityHead(len(vocabulary.tokens)).to(device)
    selected_model = torch.load(selected_model_path, map_location=device, weights_only=True)
    if (
        selected_model.get("protocol") != TRAINING_PROTOCOL
        or selected_model.get("vocabulary_sha256") != sha256_file(vocabulary_path)
    ):
        raise ValueError("selected semantic model identity changed")
    head.load_state_dict(selected_model["model_state"], strict=True)

    calibration_rows = score_rows(
        head,
        calibration_examples,
        context_states,
        embedding_indices,
        train_frequency,
        device,
    )
    calibration_summary, calibration_gate_values = select_threshold(calibration_rows)
    calibration_passed = all(calibration_gate_values.values())
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "target_manifest_sha256": sha256_file(target_manifest),
        "target_receipt_sha256": sha256_file(target_receipt),
        "vocabulary_sha256": sha256_file(vocabulary_path),
        "embeddings_sha256": sha256_file(embeddings_path),
        "embedding_receipt_sha256": sha256_file(embedding_receipt),
        "training_receipt_sha256": sha256_file(training_receipt_path),
        "selected_model_sha256": sha256_file(selected_model_path),
        "threshold_selection": "maximum_calibration_coverage_passing_all_fixed_gates",
        "protected_data_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
    }
    write_json_atomic(output / "metadata.json", metadata)

    internal_summary = None
    internal_gate_values = None
    if calibration_passed:
        access_marker = {
            "protocol": PROTOCOL,
            "status": "internal_test_access_started_once",
            "threshold": calibration_summary["threshold"],
            "target_manifest_sha256": metadata["target_manifest_sha256"],
        }
        write_json_atomic(output / "internal_test_access.json", access_marker)
        internal_targets = [target for target in targets if target["split"] == "internal_test"]
        internal_examples = build_examples(internal_targets, vocabulary, role_ids)
        internal_rows = score_rows(
            head,
            internal_examples,
            context_states,
            embedding_indices,
            train_frequency,
            device,
        )
        internal_summary = summarize(internal_rows, float(calibration_summary["threshold"]))
        internal_gate_values = internal_gates(internal_summary)
        access_marker["status"] = "internal_test_access_completed_once"
        write_json_atomic(output / "internal_test_access.json", access_marker)

    receipt = {
        **metadata,
        "complete": True,
        "calibration": calibration_summary,
        "calibration_gates": calibration_gate_values,
        "calibration_passed": calibration_passed,
        "internal_test_evaluated": calibration_passed,
        "internal_test": internal_summary,
        "internal_test_gates": internal_gate_values,
        "selective_semantic_passed": bool(
            calibration_passed
            and internal_gate_values is not None
            and all(internal_gate_values.values())
        ),
        "per_target_predictions_persisted": False,
        "protected_data_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
    }
    receipt_path = output / "receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-manifest", type=Path, default=DEFAULT_TARGET_MANIFEST)
    parser.add_argument("--target-receipt", type=Path, default=DEFAULT_TARGET_RECEIPT)
    parser.add_argument("--vocabulary", type=Path, default=DEFAULT_VOCABULARY)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--embedding-receipt", type=Path, default=DEFAULT_EMBEDDING_RECEIPT)
    parser.add_argument("--training-receipt", type=Path, default=DEFAULT_TRAINING_RECEIPT)
    parser.add_argument("--selected-model", type=Path, default=DEFAULT_SELECTED_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        receipt = score(
            target_manifest=args.target_manifest,
            target_receipt=args.target_receipt,
            vocabulary_path=args.vocabulary,
            embeddings_path=args.embeddings,
            embedding_receipt=args.embedding_receipt,
            training_receipt_path=args.training_receipt,
            selected_model_path=args.selected_model,
            output=args.output,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(f"selective semantic scoring refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
