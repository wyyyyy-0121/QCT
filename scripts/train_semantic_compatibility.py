#!/usr/bin/env python3
"""Train and evaluate the masked context/formula compatibility head."""

from __future__ import annotations

import argparse
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

from formulaguard.semantic_compatibility import (
    SPECIAL_TOKENS,
    FormulaVocabulary,
    pad_token_ids,
)
from formulaguard.semantic_compatibility_torch import SemanticCompatibilityHead
from scripts.build_fcrl_u1_corpus import sha256_file, write_json_atomic
from scripts.build_semantic_compatibility_corpus import PROTOCOL as CORPUS_PROTOCOL
from scripts.extract_semantic_compatibility_embeddings import (
    CONTEXT_SIZE,
    _validate_embedding_payload,
    load_target_contract,
)
from scripts.extract_semantic_compatibility_embeddings import (
    PROTOCOL as EMBEDDING_PROTOCOL,
)

PROTOCOL = "formulaguard_semantic_compatibility_training_v2"
SEED = 260831
BATCH_SIZE = 128
LEARNING_RATE = 3e-4
WEIGHT_DECAY = 1e-4
GRADIENT_CLIP = 1.0
HARD_NEGATIVE_WEIGHT = 1.0
MAX_EPOCHS = 40
PATIENCE = 5
BOOTSTRAP_SAMPLES = 5000
MIN_ELIGIBLE_CASES = 1000
MIN_CANDIDATE_ACCURACY = 0.55
MIN_ACCURACY_DELTA = 0.03
MIN_GROUP_MACRO_DELTA = 0.02

DEFAULT_TARGET_MANIFEST = ROOT / "results/semantic_compatibility_corpus_v2/target_manifest.json"
DEFAULT_TARGET_RECEIPT = ROOT / "results/semantic_compatibility_corpus_v2/corpus_receipt.json"
DEFAULT_VOCABULARY = ROOT / "results/semantic_compatibility_corpus_v2/vocabulary.json"
DEFAULT_EMBEDDINGS = ROOT / "results/semantic_compatibility_embeddings_v2/embeddings.pt"
DEFAULT_EMBEDDING_RECEIPT = ROOT / "results/semantic_compatibility_embeddings_v2/receipt.json"
DEFAULT_OUTPUT = ROOT / "results/semantic_compatibility_training_v2"


@dataclass(frozen=True)
class CompatibilityExample:
    target_id: str
    structure_group: str
    role: str
    role_id: int
    correct_token_ids: tuple[int, ...]
    candidate_roles: tuple[str, ...]
    candidate_token_ids: tuple[tuple[int, ...], ...]
    gold_index: int
    fallback_role: bool


@dataclass(frozen=True)
class EvaluationRow:
    structure_group: str
    model_correct: bool
    strict_model_correct: bool
    frequency_correct: bool
    candidate_count: int
    fallback_role: bool
    unseen_role: bool


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
        raise ValueError("tracked worktree must be clean before semantic training")


def atomic_torch_save(payload: object, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def configure_determinism() -> None:
    random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)


def load_vocabulary(path: Path, target_receipt: Path) -> FormulaVocabulary:
    receipt = json.loads(target_receipt.read_text(encoding="ascii"))
    payload = json.loads(path.read_text(encoding="ascii"))
    tokens = payload.get("tokens")
    if (
        receipt.get("protocol") != CORPUS_PROTOCOL
        or receipt.get("vocabulary_sha256") != sha256_file(path)
        or payload.get("protocol") != CORPUS_PROTOCOL
        or payload.get("train_only") is not True
        or not isinstance(tokens, list)
        or tuple(tokens[: len(SPECIAL_TOKENS)]) != SPECIAL_TOKENS
        or len(tokens) != len(set(tokens))
        or len(tokens) != receipt.get("vocabulary_size")
    ):
        raise ValueError("semantic train-only vocabulary is invalid")
    return FormulaVocabulary(tuple(str(token) for token in tokens))


def load_embeddings(
    path: Path,
    receipt_path: Path,
    target_manifest: Path,
    target_receipt: Path,
    expected_target_ids: Sequence[str],
) -> tuple[tuple[str, ...], Tensor]:
    receipt = json.loads(receipt_path.read_text(encoding="ascii"))
    if (
        receipt.get("protocol") != EMBEDDING_PROTOCOL
        or receipt.get("complete") is not True
        or receipt.get("embeddings_sha256") != sha256_file(path)
        or receipt.get("target_manifest_sha256") != sha256_file(target_manifest)
        or receipt.get("target_receipt_sha256") != sha256_file(target_receipt)
        or receipt.get("protected_data_inputs") != []
        or receipt.get("fault_label_inputs") != []
        or receipt.get("answer_workbook_inputs") != []
        or receipt.get("formula_roles_persisted") is not False
        or receipt.get("target_formula_tokens_entered_context_encoder") is not False
    ):
        raise ValueError("semantic embedding receipt violates the training contract")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    identifiers = tuple(sorted(expected_target_ids))
    states = _validate_embedding_payload(payload, identifiers)
    return identifiers, states


def _candidate_roles(role: str, alternatives: Sequence[str]) -> tuple[tuple[str, ...], int]:
    candidates = tuple(sorted({role, *alternatives}))
    return candidates, candidates.index(role)


def build_examples(
    targets: Sequence[Mapping[str, object]],
    vocabulary: FormulaVocabulary,
    role_ids: Mapping[str, int],
) -> list[CompatibilityExample]:
    examples = []
    for target in targets:
        role = str(target["role"])
        candidates, gold_index = _candidate_roles(
            role,
            [str(candidate) for candidate in target["local_candidate_roles"]],
        )
        examples.append(CompatibilityExample(
            target_id=str(target["target_id"]),
            structure_group=str(target["structure_group"]),
            role=role,
            role_id=role_ids.get(role, -1),
            correct_token_ids=vocabulary.encode(role),
            candidate_roles=candidates,
            candidate_token_ids=tuple(vocabulary.encode(candidate) for candidate in candidates),
            gold_index=gold_index,
            fallback_role=role.startswith("LEX("),
        ))
    return examples


def _batch_tensors(
    examples: Sequence[CompatibilityExample],
    context_states: Tensor,
    embedding_indices: Mapping[str, int],
    device: torch.device,
) -> tuple[Tensor, Tensor, Tensor, Tensor, Tensor, Tensor, Tensor, Tensor]:
    context = context_states[
        torch.tensor([embedding_indices[example.target_id] for example in examples])
    ].to(device=device, dtype=torch.float32)
    correct_rows, correct_lengths = pad_token_ids(
        tuple(example.correct_token_ids for example in examples)
    )
    correct_tokens = torch.tensor(correct_rows, dtype=torch.long, device=device)
    correct_length_tensor = torch.tensor(correct_lengths, dtype=torch.long, device=device)
    role_id_tensor = torch.tensor([example.role_id for example in examples], device=device)

    candidate_count = max(len(example.candidate_token_ids) for example in examples)
    sequence_length = max(
        len(tokens)
        for example in examples
        for tokens in example.candidate_token_ids
    )
    candidate_tokens = torch.zeros(
        (len(examples), candidate_count, sequence_length),
        dtype=torch.long,
        device=device,
    )
    candidate_lengths = torch.ones(
        (len(examples), candidate_count),
        dtype=torch.long,
        device=device,
    )
    candidate_mask = torch.zeros(
        (len(examples), candidate_count),
        dtype=torch.bool,
        device=device,
    )
    for row, example in enumerate(examples):
        for column, tokens in enumerate(example.candidate_token_ids):
            candidate_tokens[row, column, : len(tokens)] = torch.tensor(tokens, device=device)
            candidate_lengths[row, column] = len(tokens)
            candidate_mask[row, column] = True
    gold_indices = torch.tensor([example.gold_index for example in examples], device=device)
    return (
        context,
        correct_tokens,
        correct_length_tensor,
        role_id_tensor,
        candidate_tokens,
        candidate_lengths,
        candidate_mask,
        gold_indices,
    )


def _accuracy(values: Sequence[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


@torch.no_grad()
def evaluate(
    head: SemanticCompatibilityHead,
    examples: Sequence[CompatibilityExample],
    context_states: Tensor,
    embedding_indices: Mapping[str, int],
    train_frequency: Mapping[str, int],
    device: torch.device,
) -> tuple[dict[str, object], list[EvaluationRow]]:
    head.eval()
    rows: list[EvaluationRow] = []
    losses = []
    for start in range(0, len(examples), BATCH_SIZE):
        batch_examples = examples[start : start + BATCH_SIZE]
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
            if len(example.candidate_roles) < 2:
                continue
            scores = logits[index, : len(example.candidate_roles)]
            predicted_index = int(scores.argmax().item())
            gold_score = float(scores[example.gold_index].item())
            alternative_score = max(
                float(scores[position].item())
                for position in range(len(example.candidate_roles))
                if position != example.gold_index
            )
            frequency_prediction = min(
                example.candidate_roles,
                key=lambda role: (-int(train_frequency.get(role, 0)), role),
            )
            rows.append(EvaluationRow(
                structure_group=example.structure_group,
                model_correct=predicted_index == example.gold_index,
                strict_model_correct=gold_score > alternative_score,
                frequency_correct=frequency_prediction == example.role,
                candidate_count=len(example.candidate_roles),
                fallback_role=example.fallback_role,
                unseen_role=example.role not in train_frequency,
            ))
            losses.append(float(F.cross_entropy(
                scores.unsqueeze(0),
                torch.tensor([example.gold_index], device=device),
            ).item()))
    if not rows:
        raise ValueError("semantic evaluation has no hard-negative cases")
    model_accuracy = _accuracy([row.model_correct for row in rows])
    strict_accuracy = _accuracy([row.strict_model_correct for row in rows])
    frequency_accuracy = _accuracy([row.frequency_correct for row in rows])
    by_group: dict[str, list[EvaluationRow]] = defaultdict(list)
    for row in rows:
        by_group[row.structure_group].append(row)
    model_group_macro = sum(
        _accuracy([row.model_correct for row in group_rows])
        for group_rows in by_group.values()
    ) / len(by_group)
    frequency_group_macro = sum(
        _accuracy([row.frequency_correct for row in group_rows])
        for group_rows in by_group.values()
    ) / len(by_group)
    by_candidate_count = {
        str(count): _accuracy([
            row.model_correct for row in rows if row.candidate_count == count
        ])
        for count in sorted({row.candidate_count for row in rows})
    }
    seen_values = [row.model_correct for row in rows if not row.unseen_role]
    unseen_values = [row.model_correct for row in rows if row.unseen_role]
    fallback_values = [row.model_correct for row in rows if row.fallback_role]
    metrics: dict[str, object] = {
        "targets": len(examples),
        "eligible_hard_negative_cases": len(rows),
        "structure_groups": len(by_group),
        "candidate_accuracy": model_accuracy,
        "strict_candidate_accuracy": strict_accuracy,
        "train_frequency_accuracy": frequency_accuracy,
        "nearest_local_alternative_accuracy": 0.0,
        "random_expected_accuracy": sum(1.0 / row.candidate_count for row in rows) / len(rows),
        "accuracy_delta_over_train_frequency": model_accuracy - frequency_accuracy,
        "group_macro_accuracy": model_group_macro,
        "train_frequency_group_macro_accuracy": frequency_group_macro,
        "group_macro_delta_over_train_frequency": model_group_macro - frequency_group_macro,
        "mean_candidate_cross_entropy": sum(losses) / len(losses),
        "seen_role_accuracy": _accuracy(seen_values) if seen_values else None,
        "unseen_role_accuracy": _accuracy(unseen_values) if unseen_values else None,
        "fallback_role_accuracy": _accuracy(fallback_values) if fallback_values else None,
        "accuracy_by_candidate_count": by_candidate_count,
    }
    return metrics, rows


def group_bootstrap_interval(
    rows: Sequence[EvaluationRow],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = SEED,
) -> tuple[float, float]:
    if samples < 100:
        raise ValueError("semantic bootstrap sample count is too small")
    groups: dict[str, list[EvaluationRow]] = defaultdict(list)
    for row in rows:
        groups[row.structure_group].append(row)
    group_ids = sorted(groups)
    if len(group_ids) < 2:
        raise ValueError("semantic bootstrap requires multiple structure groups")
    rng = random.Random(seed)
    deltas = []
    for _ in range(samples):
        sampled = [rng.choice(group_ids) for _ in group_ids]
        numerator = denominator = 0
        for group in sampled:
            for row in groups[group]:
                numerator += int(row.model_correct) - int(row.frequency_correct)
                denominator += 1
        deltas.append(numerator / denominator)
    deltas.sort()
    return (
        deltas[int(0.025 * (samples - 1))],
        deltas[int(0.975 * (samples - 1))],
    )


def evaluate_gates(
    metrics: Mapping[str, object],
    *,
    require_bootstrap: bool,
) -> dict[str, bool]:
    gates = {
        "at_least_1000_hard_negative_cases": int(metrics["eligible_hard_negative_cases"]) >= MIN_ELIGIBLE_CASES,
        "candidate_accuracy_at_least_55pct": float(metrics["candidate_accuracy"]) >= MIN_CANDIDATE_ACCURACY,
        "accuracy_delta_over_train_frequency_at_least_3pp": float(
            metrics["accuracy_delta_over_train_frequency"]
        ) >= MIN_ACCURACY_DELTA,
        "group_macro_delta_over_train_frequency_at_least_2pp": float(
            metrics["group_macro_delta_over_train_frequency"]
        ) >= MIN_GROUP_MACRO_DELTA,
        "beats_random_expected_accuracy": float(metrics["candidate_accuracy"]) > float(
            metrics["random_expected_accuracy"]
        ),
        "beats_nearest_local_alternative": float(metrics["candidate_accuracy"]) > float(
            metrics["nearest_local_alternative_accuracy"]
        ),
    }
    if require_bootstrap:
        interval = metrics.get("group_bootstrap_delta_95ci")
        gates["group_bootstrap_delta_lower_bound_above_zero"] = (
            isinstance(interval, list)
            and len(interval) == 2
            and float(interval[0]) > 0.0
        )
    return gates


def _cpu_state(head: SemanticCompatibilityHead) -> dict[str, Tensor]:
    return {key: value.detach().cpu().clone() for key, value in head.state_dict().items()}


def train(
    *,
    target_manifest: Path,
    target_receipt: Path,
    vocabulary_path: Path,
    embeddings_path: Path,
    embedding_receipt: Path,
    output: Path,
    resume: bool,
) -> Path:
    require_clean_tracked_worktree()
    configure_determinism()
    if not torch.cuda.is_available():
        raise ValueError("semantic compatibility training requires CUDA")
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
    internal_test_targets = [target for target in targets if target["split"] == "internal_test"]
    train_frequency = Counter(str(target["role"]) for target in train_targets)
    role_ids = {role: index for index, role in enumerate(sorted(train_frequency))}
    train_examples = build_examples(train_targets, vocabulary, role_ids)
    calibration_examples = build_examples(calibration_targets, vocabulary, role_ids)

    output = output.resolve()
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "target_manifest_sha256": sha256_file(target_manifest),
        "target_receipt_sha256": sha256_file(target_receipt),
        "vocabulary_sha256": sha256_file(vocabulary_path),
        "embeddings_sha256": sha256_file(embeddings_path),
        "embedding_receipt_sha256": sha256_file(embedding_receipt),
        "train_targets": len(train_targets),
        "calibration_targets": len(calibration_targets),
        "internal_test_targets_locked": len(internal_test_targets),
        "batch_size": BATCH_SIZE,
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "gradient_clip": GRADIENT_CLIP,
        "hard_negative_weight": HARD_NEGATIVE_WEIGHT,
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "seed": SEED,
        "selection_split": "calibration",
        "internal_test_access": "once_after_calibration_gate_passes",
        "protected_data_inputs": [],
        "fault_label_inputs": [],
        "v4_rank_inputs": [],
    }
    metadata_path = output / "metadata.json"
    if output.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("semantic training output exists; pass --resume after audit")
        if json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
            raise ValueError("semantic training resume metadata differs")
    else:
        output.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)

    device = torch.device("cuda:0")
    head = SemanticCompatibilityHead(len(vocabulary.tokens), context_size=CONTEXT_SIZE).to(device)
    optimizer = torch.optim.AdamW(
        head.parameters(),
        lr=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
    )
    selected_model_path = output / "selected_model.pt"
    last_epoch_path = output / "last_complete_epoch.pt"
    history_path = output / "history.json"
    history: list[dict[str, object]] = []
    best_score: tuple[float, float, float] | None = None
    best_epoch = 0
    stale_epochs = 0
    start_epoch = 1
    if resume:
        state = torch.load(last_epoch_path, map_location=device, weights_only=False)
        if (
            state.get("protocol") != PROTOCOL
            or state.get("git_commit") != metadata["git_commit"]
            or state.get("target_manifest_sha256") != metadata["target_manifest_sha256"]
        ):
            raise ValueError("semantic epoch checkpoint identity changed")
        head.load_state_dict(state["model_state"], strict=True)
        optimizer.load_state_dict(state["optimizer_state"])
        history = list(state["history"])
        best_score = tuple(float(value) for value in state["best_score"])
        best_epoch = int(state["best_epoch"])
        stale_epochs = int(state["stale_epochs"])
        start_epoch = int(state["epoch"]) + 1
        torch.set_rng_state(state["torch_rng_cpu"].cpu())
        torch.cuda.set_rng_state_all([value.cpu() for value in state["torch_rng_cuda"]])

    for epoch in range(start_epoch, MAX_EPOCHS + 1):
        started = time.monotonic()
        head.train()
        generator = torch.Generator().manual_seed(SEED + epoch)
        order = torch.randperm(len(train_examples), generator=generator).tolist()
        total_loss = total_contrastive = total_candidate = 0.0
        trained = 0
        for start in range(0, len(order), BATCH_SIZE):
            batch_examples = [train_examples[index] for index in order[start : start + BATCH_SIZE]]
            (
                context,
                correct_tokens,
                correct_lengths,
                role_id_tensor,
                candidate_tokens,
                candidate_lengths,
                candidate_mask,
                gold_indices,
            ) = _batch_tensors(batch_examples, context_states, embedding_indices, device)
            optimizer.zero_grad(set_to_none=True)
            contrastive = head.contrastive_loss(
                context,
                correct_tokens,
                correct_lengths,
                role_id_tensor,
            )
            candidate = head.candidate_loss(
                context,
                candidate_tokens,
                candidate_lengths,
                candidate_mask,
                gold_indices,
            )
            loss = contrastive + HARD_NEGATIVE_WEIGHT * candidate
            if not bool(torch.isfinite(loss)):
                raise ValueError("semantic training loss is non-finite")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), GRADIENT_CLIP)
            optimizer.step()
            batch_size = len(batch_examples)
            trained += batch_size
            total_loss += float(loss.item()) * batch_size
            total_contrastive += float(contrastive.item()) * batch_size
            total_candidate += float(candidate.item()) * batch_size

        calibration_metrics, _rows = evaluate(
            head,
            calibration_examples,
            context_states,
            embedding_indices,
            train_frequency,
            device,
        )
        score = (
            float(calibration_metrics["candidate_accuracy"]),
            float(calibration_metrics["group_macro_accuracy"]),
            -float(calibration_metrics["mean_candidate_cross_entropy"]),
        )
        improved = best_score is None or score > best_score
        if improved:
            best_score = score
            best_epoch = epoch
            stale_epochs = 0
            atomic_torch_save({
                "protocol": PROTOCOL,
                "git_commit": metadata["git_commit"],
                "epoch": epoch,
                "vocabulary_sha256": metadata["vocabulary_sha256"],
                "model_state": _cpu_state(head),
            }, selected_model_path)
        else:
            stale_epochs += 1
        epoch_record = {
            "epoch": epoch,
            "train_loss": total_loss / trained,
            "train_contrastive_loss": total_contrastive / trained,
            "train_candidate_loss": total_candidate / trained,
            "calibration": calibration_metrics,
            "selected": improved,
            "elapsed_seconds": time.monotonic() - started,
        }
        history.append(epoch_record)
        write_json_atomic(history_path, {"protocol": PROTOCOL, "epochs": history})
        checkpoint = {
            "protocol": PROTOCOL,
            "git_commit": metadata["git_commit"],
            "target_manifest_sha256": metadata["target_manifest_sha256"],
            "epoch": epoch,
            "model_state": _cpu_state(head),
            "optimizer_state": optimizer.state_dict(),
            "history": history,
            "best_score": list(best_score),
            "best_epoch": best_epoch,
            "stale_epochs": stale_epochs,
            "torch_rng_cpu": torch.get_rng_state(),
            "torch_rng_cuda": torch.cuda.get_rng_state_all(),
        }
        atomic_torch_save(checkpoint, last_epoch_path)
        print(
            f"semantic epoch={epoch} train_loss={epoch_record['train_loss']:.4f} "
            f"cal_acc={float(calibration_metrics['candidate_accuracy']):.4f} "
            f"cal_delta={float(calibration_metrics['accuracy_delta_over_train_frequency']):+.4f} "
            f"selected={improved}",
            flush=True,
        )
        if stale_epochs >= PATIENCE:
            break

    selected = torch.load(selected_model_path, map_location=device, weights_only=True)
    head.load_state_dict(selected["model_state"], strict=True)
    calibration_metrics, calibration_rows = evaluate(
        head,
        calibration_examples,
        context_states,
        embedding_indices,
        train_frequency,
        device,
    )
    calibration_metrics["group_bootstrap_delta_95ci"] = list(group_bootstrap_interval(
        calibration_rows,
        seed=SEED + 1,
    ))
    calibration_gates = evaluate_gates(calibration_metrics, require_bootstrap=False)
    calibration_passed = all(calibration_gates.values())

    internal_metrics: dict[str, object] | None = None
    internal_gates: dict[str, bool] | None = None
    if calibration_passed:
        internal_examples = build_examples(internal_test_targets, vocabulary, role_ids)
        internal_metrics, internal_rows = evaluate(
            head,
            internal_examples,
            context_states,
            embedding_indices,
            train_frequency,
            device,
        )
        internal_metrics["group_bootstrap_delta_95ci"] = list(group_bootstrap_interval(
            internal_rows,
            seed=SEED + 2,
        ))
        internal_gates = evaluate_gates(internal_metrics, require_bootstrap=True)

    receipt = {
        **metadata,
        "complete": True,
        "best_epoch": best_epoch,
        "epochs_completed": len(history),
        "selected_model_sha256": sha256_file(selected_model_path),
        "calibration_metrics": calibration_metrics,
        "calibration_gates": calibration_gates,
        "calibration_passed": calibration_passed,
        "internal_test_evaluated": calibration_passed,
        "internal_test_metrics": internal_metrics,
        "internal_test_gates": internal_gates,
        "semantic_compatibility_passed": bool(
            calibration_passed
            and internal_gates is not None
            and all(internal_gates.values())
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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = train(
            target_manifest=args.target_manifest,
            target_receipt=args.target_receipt,
            vocabulary_path=args.vocabulary,
            embeddings_path=args.embeddings,
            embedding_receipt=args.embedding_receipt,
            output=args.output,
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
        raise SystemExit(f"semantic compatibility training refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
