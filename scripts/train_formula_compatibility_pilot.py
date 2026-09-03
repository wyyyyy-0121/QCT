#!/usr/bin/env python3
"""Train the exploratory formula-corruption compatibility model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch
from torch import Tensor
from torch.nn import functional as F

from formulaguard.formula_compatibility_pilot import PROTOCOL, candidate_rows
from formulaguard.formula_compatibility_pilot_torch import FormulaCompatibilityPilot
from formulaguard.pcrc import (
    CORPUS_PROTOCOL,
    MAX_CONTEXT_TOKENS,
    MAX_FORMULA_TOKENS,
    PCRCVocabulary,
)
from scripts.build_fcrl_u1_corpus import sha256_file, write_json_atomic

SEED = 260902
BATCH_SIZE = 128
LEARNING_RATES = (1e-3, 3e-4, 1e-4)
WEIGHT_DECAY = 1e-4
GRADIENT_CLIP = 1.0
MAX_EPOCHS = 30
PATIENCE = 4
DEFAULT_CORPUS = ROOT / "results/pcrc_corpus_v1"
DEFAULT_OUTPUT = ROOT / "results/formula_compatibility_pilot_v1"


@dataclass(frozen=True)
class Example:
    target_id: str
    workbook_id: str
    structure_group: str
    context_ids: tuple[int, ...]
    candidate_ids: tuple[tuple[int, ...], ...]
    candidate_kinds: tuple[str, ...]
    observed_key: str


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def require_clean_tracked_worktree() -> None:
    result = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("tracked worktree must be clean before compatibility training")


def configure_determinism(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)


def _key(tokens: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(tokens).encode("ascii")).hexdigest()


def load_vocabulary(path: Path) -> PCRCVocabulary:
    payload = json.loads(path.read_text(encoding="ascii"))
    if payload.get("protocol") != CORPUS_PROTOCOL or payload.get("train_only") is not True:
        raise ValueError("formula compatibility vocabulary contract differs")
    tokens = payload.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError("formula compatibility vocabulary is malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    return PCRCVocabulary(tuple(str(token) for token in tokens))


def load_examples(corpus: Path, vocabulary: PCRCVocabulary) -> dict[str, list[Example]]:
    receipt = json.loads((corpus / "corpus_receipt.json").read_text(encoding="ascii"))
    if (
        receipt.get("protocol") != CORPUS_PROTOCOL
        or receipt.get("complete") is not True
        or receipt.get("vocabulary_sha256") != sha256_file(corpus / "vocabulary.json")
        or receipt.get("fault_label_inputs") != []
        or receipt.get("answer_workbook_inputs") != []
        or receipt.get("protected_data_inputs") != []
        or receipt.get("target_formula_tokens_entered_context") is not False
    ):
        raise ValueError("formula compatibility corpus receipt violates the pilot contract")
    splits: dict[str, list[Example]] = defaultdict(list)
    for path in sorted((corpus / "workbook_shards").glob("*.json")):
        payload = json.loads(path.read_text(encoding="ascii"))
        for item in payload["examples"]:
            candidates = candidate_rows(item)
            if len(candidates) < 2:
                continue
            observed_tokens = tuple(str(token) for token in item["observed_tokens"])
            example = Example(
                target_id=str(item["target_id"]),
                workbook_id=str(item["workbook_id"]),
                structure_group=str(item["structure_group"]),
                context_ids=vocabulary.encode(item["context_tokens"], maximum=MAX_CONTEXT_TOKENS),
                candidate_ids=tuple(
                    vocabulary.encode(candidate["tokens"], maximum=MAX_FORMULA_TOKENS)
                    for candidate in candidates
                ),
                candidate_kinds=tuple(str(candidate["kind"]) for candidate in candidates),
                observed_key=_key(observed_tokens),
            )
            splits[str(item["split"])].append(example)
    for rows in splits.values():
        rows.sort(key=lambda item: item.target_id)
    return dict(splits)


def _pad(rows: Sequence[Sequence[int]], device: torch.device) -> tuple[Tensor, Tensor]:
    lengths = torch.tensor([len(row) for row in rows], dtype=torch.long, device=device)
    width = int(lengths.max().item())
    result = torch.zeros((len(rows), width), dtype=torch.long, device=device)
    for index, row in enumerate(rows):
        result[index, : len(row)] = torch.tensor(row, dtype=torch.long, device=device)
    return result, lengths


def batch_tensors(examples: Sequence[Example], device: torch.device):
    context_ids, context_lengths = _pad([item.context_ids for item in examples], device)
    candidate_count = max(len(item.candidate_ids) for item in examples)
    formula_width = max(len(candidate) for item in examples for candidate in item.candidate_ids)
    formula_ids = torch.zeros(
        (len(examples), candidate_count, formula_width), dtype=torch.long, device=device
    )
    formula_lengths = torch.ones(
        (len(examples), candidate_count), dtype=torch.long, device=device
    )
    candidate_mask = torch.zeros(
        (len(examples), candidate_count), dtype=torch.bool, device=device
    )
    for row, example in enumerate(examples):
        for column, candidate in enumerate(example.candidate_ids):
            formula_ids[row, column, : len(candidate)] = torch.tensor(candidate, device=device)
            formula_lengths[row, column] = len(candidate)
            candidate_mask[row, column] = True
    return context_ids, context_lengths, formula_ids, formula_lengths, candidate_mask


def _accuracy(values: Sequence[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


def frequency_baseline_prediction(
    example: Example,
    frequency: Mapping[str, int],
) -> int:
    """Select by train frequency without using the candidate's list position."""
    return max(
        range(len(example.candidate_ids)),
        key=lambda position: (
            int(frequency.get(_encoded_key(example.candidate_ids[position]), 0)),
            _encoded_key(example.candidate_ids[position]),
        ),
    )


def peer_support_counts(
    example: Example,
    vocabulary: PCRCVocabulary,
) -> tuple[int, ...]:
    """Count exact masked-context peer support for each candidate formula."""
    try:
        peer_start = vocabulary.ids["PEER_START"]
        peer_end = vocabulary.ids["PEER_END"]
    except KeyError as exc:
        raise ValueError("formula compatibility vocabulary lacks peer markers") from exc
    peers: list[tuple[int, ...]] = []
    context = example.context_ids
    position = 0
    while position < len(context):
        if context[position] != peer_start:
            position += 1
            continue
        try:
            end = context.index(peer_end, position + 1)
        except ValueError:
            break
        # PEER_START is followed by direction and distance metadata.
        if end > position + 3:
            peers.append(tuple(context[position + 3 : end]))
        position = end + 1
    candidate_bodies = [tuple(candidate[1:-1]) for candidate in example.candidate_ids]
    return tuple(sum(candidate == peer for peer in peers) for candidate in candidate_bodies)


def peer_frequency_baseline_prediction(
    example: Example,
    frequency: Mapping[str, int],
    vocabulary: PCRCVocabulary,
) -> int:
    """Select by local peer support, then train frequency and content hash."""
    support = peer_support_counts(example, vocabulary)
    return max(
        range(len(example.candidate_ids)),
        key=lambda position: (
            support[position],
            int(frequency.get(_encoded_key(example.candidate_ids[position]), 0)),
            _encoded_key(example.candidate_ids[position]),
        ),
    )


@torch.no_grad()
def evaluate(
    model: FormulaCompatibilityPilot,
    examples: Sequence[Example],
    frequency: Mapping[str, int],
    vocabulary: PCRCVocabulary,
    device: torch.device,
    *,
    formula_only: bool = False,
) -> dict[str, object]:
    model.eval()
    rows = []
    losses = []
    by_kind: dict[str, list[bool]] = defaultdict(list)
    for start in range(0, len(examples), BATCH_SIZE):
        batch = examples[start : start + BATCH_SIZE]
        tensors = batch_tensors(batch, device)
        logits = model.candidate_logits(*tensors, formula_only=formula_only)
        gold = torch.zeros(len(batch), dtype=torch.long, device=device)
        losses.append(float(F.cross_entropy(logits, gold, reduction="sum").item()))
        predictions = logits.argmax(dim=1).tolist()
        for index, example in enumerate(batch):
            correct = predictions[index] == 0
            frequency_counts = tuple(
                int(frequency.get(_encoded_key(candidate), 0))
                for candidate in example.candidate_ids
            )
            frequency_prediction = frequency_baseline_prediction(example, frequency)
            peer_prediction = peer_frequency_baseline_prediction(
                example, frequency, vocabulary
            )
            maximum_frequency = max(frequency_counts)
            frequency_winners = sum(
                value == maximum_frequency for value in frequency_counts
            )
            peer_support = peer_support_counts(example, vocabulary)
            row = {
                "group": example.structure_group,
                "workbook": example.workbook_id,
                "correct": correct,
                "frequency_correct": frequency_prediction == 0,
                "frequency_fractional_correct": (
                    1.0 / frequency_winners
                    if frequency_counts[0] == maximum_frequency
                    else 0.0
                ),
                "frequency_tied": frequency_winners > 1,
                "frequency_all_zero": maximum_frequency == 0,
                "peer_frequency_correct": peer_prediction == 0,
                "observed_has_exact_peer": peer_support[0] > 0,
                "candidate_count": len(example.candidate_ids),
            }
            rows.append(row)
            for kind in example.candidate_kinds[1:]:
                by_kind[kind].append(
                    float(logits[index, 0].item())
                    > max(
                        float(logits[index, position].item())
                        for position, value in enumerate(example.candidate_kinds)
                        if value == kind
                    )
                )
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["group"])].append(row)
    accuracy = _accuracy([bool(row["correct"]) for row in rows])
    frequency_accuracy = _accuracy([bool(row["frequency_correct"]) for row in rows])
    peer_frequency_accuracy = _accuracy([
        bool(row["peer_frequency_correct"]) for row in rows
    ])
    return {
        "targets": len(rows),
        "structure_groups": len(groups),
        "workbooks": len({str(row["workbook"]) for row in rows}),
        "candidate_accuracy": accuracy,
        "frequency_accuracy": frequency_accuracy,
        "accuracy_delta_over_frequency": accuracy - frequency_accuracy,
        "frequency_fractional_tie_accuracy": sum(
            float(row["frequency_fractional_correct"]) for row in rows
        ) / len(rows),
        "frequency_tie_rate": _accuracy([
            bool(row["frequency_tied"]) for row in rows
        ]),
        "frequency_all_zero_rate": _accuracy([
            bool(row["frequency_all_zero"]) for row in rows
        ]),
        "peer_frequency_accuracy": peer_frequency_accuracy,
        "accuracy_delta_over_peer_frequency": accuracy - peer_frequency_accuracy,
        "observed_exact_peer_coverage": _accuracy([
            bool(row["observed_has_exact_peer"]) for row in rows
        ]),
        "group_macro_accuracy": sum(
            _accuracy([bool(row["correct"]) for row in values]) for values in groups.values()
        ) / len(groups),
        "frequency_group_macro_accuracy": sum(
            _accuracy([bool(row["frequency_correct"]) for row in values]) for values in groups.values()
        ) / len(groups),
        "peer_frequency_group_macro_accuracy": sum(
            _accuracy([bool(row["peer_frequency_correct"]) for row in values])
            for values in groups.values()
        ) / len(groups),
        "mean_cross_entropy": sum(losses) / len(rows),
        "accuracy_by_candidate_count": {
            str(count): _accuracy([
                bool(row["correct"]) for row in rows if row["candidate_count"] == count
            ])
            for count in sorted({int(row["candidate_count"]) for row in rows})
        },
        "pairwise_accuracy_by_negative_kind": {
            kind: _accuracy(values) for kind, values in sorted(by_kind.items())
        },
    }


def _encoded_key(tokens: Sequence[int]) -> str:
    return hashlib.sha256(b"".join(int(value).to_bytes(4, "little") for value in tokens)).hexdigest()


def cpu_state(model: FormulaCompatibilityPilot) -> dict[str, Tensor]:
    return {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}


def train_one(
    *,
    learning_rate: float,
    vocabulary_size: int,
    vocabulary: PCRCVocabulary,
    train_examples: Sequence[Example],
    calibration_examples: Sequence[Example],
    frequency: Mapping[str, int],
    device: torch.device,
) -> tuple[dict[str, object], dict[str, Tensor]]:
    configure_determinism(SEED)
    model = FormulaCompatibilityPilot(vocabulary_size).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=WEIGHT_DECAY)
    best_score = None
    best_state = None
    best_epoch = 0
    stale = 0
    history = []
    for epoch in range(1, MAX_EPOCHS + 1):
        started = time.monotonic()
        model.train()
        order = torch.randperm(len(train_examples), generator=torch.Generator().manual_seed(SEED + epoch)).tolist()
        total_loss = 0.0
        trained = 0
        for start in range(0, len(order), BATCH_SIZE):
            batch = [train_examples[index] for index in order[start : start + BATCH_SIZE]]
            tensors = batch_tensors(batch, device)
            optimizer.zero_grad(set_to_none=True)
            logits = model.candidate_logits(*tensors)
            gold = torch.zeros(len(batch), dtype=torch.long, device=device)
            loss = F.cross_entropy(logits, gold)
            if not bool(torch.isfinite(loss)):
                raise ValueError("formula compatibility loss is non-finite")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRADIENT_CLIP)
            optimizer.step()
            total_loss += float(loss.item()) * len(batch)
            trained += len(batch)
        metrics = evaluate(model, calibration_examples, frequency, vocabulary, device)
        score = (
            float(metrics["group_macro_accuracy"]),
            float(metrics["candidate_accuracy"]),
            -float(metrics["mean_cross_entropy"]),
        )
        improved = best_score is None or score > best_score
        if improved:
            best_score = score
            best_state = cpu_state(model)
            best_epoch = epoch
            stale = 0
        else:
            stale += 1
        history.append({
            "epoch": epoch,
            "train_loss": total_loss / trained,
            "calibration": metrics,
            "selected": improved,
            "elapsed_seconds": time.monotonic() - started,
        })
        print(
            f"lr={learning_rate:g} epoch={epoch} train={total_loss / trained:.4f} "
            f"cal={float(metrics['candidate_accuracy']):.4f} "
            f"group={float(metrics['group_macro_accuracy']):.4f}",
            flush=True,
        )
        if stale >= PATIENCE:
            break
    if best_state is None:
        raise ValueError("formula compatibility training selected no checkpoint")
    return {
        "learning_rate": learning_rate,
        "best_epoch": best_epoch,
        "best_score": list(best_score),
        "history": history,
    }, best_state


def atomic_torch_save(payload: object, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def train(*, corpus: Path, output: Path) -> Path:
    require_clean_tracked_worktree()
    if not torch.cuda.is_available():
        raise ValueError("formula compatibility training requires CUDA")
    vocabulary = load_vocabulary(corpus / "vocabulary.json")
    splits = load_examples(corpus, vocabulary)
    train_examples = splits["train"]
    calibration_examples = splits["calibration"]
    internal_examples = splits["internal_test"]
    frequency = Counter(_encoded_key(example.candidate_ids[0]) for example in train_examples)
    output = output.resolve()
    if output.exists():
        raise ValueError("formula compatibility pilot output already exists")
    output.mkdir(parents=True)
    metadata = {
        "protocol": PROTOCOL,
        "status": "exploratory_revealed_development",
        "git_commit": git_commit(),
        "corpus_receipt_sha256": sha256_file(corpus / "corpus_receipt.json"),
        "vocabulary_sha256": sha256_file(corpus / "vocabulary.json"),
        "train_targets": len(train_examples),
        "calibration_targets": len(calibration_examples),
        "internal_test_targets": len(internal_examples),
        "learning_rates": list(LEARNING_RATES),
        "batch_size": BATCH_SIZE,
        "weight_decay": WEIGHT_DECAY,
        "gradient_clip": GRADIENT_CLIP,
        "maximum_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "seed": SEED,
        "fault_label_inputs": [],
        "answer_workbook_inputs": [],
        "protected_data_inputs": [],
    }
    write_json_atomic(output / "metadata.json", metadata)
    device = torch.device("cuda:0")
    runs = []
    states = []
    for learning_rate in LEARNING_RATES:
        run, state = train_one(
            learning_rate=learning_rate,
            vocabulary_size=len(vocabulary.tokens),
            vocabulary=vocabulary,
            train_examples=train_examples,
            calibration_examples=calibration_examples,
            frequency=frequency,
            device=device,
        )
        runs.append(run)
        states.append(state)
    selected_index = max(
        range(len(runs)),
        key=lambda index: (
            *runs[index]["best_score"],  # type: ignore[misc]
            -float(runs[index]["learning_rate"]),
        ),
    )
    selected = FormulaCompatibilityPilot(len(vocabulary.tokens)).to(device)
    selected.load_state_dict(states[selected_index], strict=True)
    calibration_metrics = evaluate(
        selected, calibration_examples, frequency, vocabulary, device
    )
    internal_metrics = evaluate(selected, internal_examples, frequency, vocabulary, device)
    formula_only_metrics = evaluate(
        selected, internal_examples, frequency, vocabulary, device, formula_only=True
    )
    model_path = output / "selected_model.pt"
    atomic_torch_save({
        "protocol": PROTOCOL,
        "git_commit": metadata["git_commit"],
        "learning_rate": runs[selected_index]["learning_rate"],
        "best_epoch": runs[selected_index]["best_epoch"],
        "vocabulary_sha256": metadata["vocabulary_sha256"],
        "model_state": states[selected_index],
    }, model_path)
    write_json_atomic(output / "history.json", {"protocol": PROTOCOL, "runs": runs})
    receipt = {
        **metadata,
        "complete": True,
        "selected_learning_rate": runs[selected_index]["learning_rate"],
        "selected_epoch": runs[selected_index]["best_epoch"],
        "calibration_metrics": calibration_metrics,
        "internal_test_metrics": internal_metrics,
        "formula_only_internal_test_metrics": formula_only_metrics,
        "selected_model_sha256": sha256_file(model_path),
        "model_development_result": "promising" if (
            float(internal_metrics["candidate_accuracy"]) >= 0.60
            and float(internal_metrics["accuracy_delta_over_peer_frequency"]) >= 0.02
            and float(internal_metrics["group_macro_accuracy"]) >= 0.55
        ) else "insufficient",
        "public_localization_authorized": False,
        "formal_version_authorized": False,
    }
    receipt_path = output / "receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        print(train(corpus=args.corpus.resolve(), output=args.output.resolve()))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"formula compatibility pilot refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
