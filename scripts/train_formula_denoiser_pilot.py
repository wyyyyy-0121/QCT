#!/usr/bin/env python3
"""Train a public-data Transformer to generate complete repaired formula tokens."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import Tensor
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from formulaguard.formula_compatibility_pilot import token_mutations
from formulaguard.formula_denoiser import FormulaDenoiser, denoising_source
from formulaguard.pcrc import (
    CORPUS_PROTOCOL,
    MAX_CONTEXT_TOKENS,
    MAX_FORMULA_TOKENS,
    PCRCVocabulary,
)
from formulaguard.v5_psl_protocol import sha256 as sha256_file


PROTOCOL = "formulaguard_formula_denoiser_pilot_v3"
SEED = 260902
MASK_TOKEN = "<MASK>"
MUTATION_FAMILIES = (
    "operator",
    "function",
    "reference_offset",
    "anchor",
    "numeric",
    "sheet_relation",
)
MAX_SOURCE_TOKENS = MAX_CONTEXT_TOKENS + MAX_FORMULA_TOKENS
DEFAULT_CORPUS = ROOT / "results/pcrc_corpus_v1"
DEFAULT_OUTPUT = ROOT / "results/formula_denoiser_pilot_v3"


def write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, path)


@dataclass(frozen=True)
class FormulaBase:
    target_id: str
    workbook_id: str
    structure_group: str
    context_ids: tuple[int, ...]
    clean_ids: tuple[int, ...]
    corruptions: Mapping[str, tuple[int, ...]]


class DenoisingDataset(Dataset[tuple[FormulaBase, str, tuple[int, ...]]]):
    def __init__(
        self,
        bases: Sequence[FormulaBase],
        families: Sequence[str],
        *,
        include_clean: bool,
    ) -> None:
        self.bases = tuple(bases)
        rows: list[tuple[int, str]] = []
        for index, base in enumerate(self.bases):
            if include_clean:
                rows.append((index, "clean"))
            rows.extend(
                (index, family) for family in families if family in base.corruptions
            )
        self.rows = tuple(rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[FormulaBase, str, tuple[int, ...]]:
        base_index, family = self.rows[index]
        base = self.bases[base_index]
        corrupted = base.clean_ids if family == "clean" else base.corruptions[family]
        return base, family, corrupted


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_clean_tracked_worktree() -> None:
    status = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise ValueError("tracked worktree must be clean before formula denoiser training")


def configure(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.set_float32_matmul_precision("high")
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True


def load_vocabulary(path: Path) -> PCRCVocabulary:
    payload = json.loads(path.read_text(encoding="ascii"))
    if payload.get("protocol") != CORPUS_PROTOCOL or payload.get("train_only") is not True:
        raise ValueError("formula denoiser vocabulary contract differs")
    tokens = payload.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError("formula denoiser vocabulary is malformed")
    values = tuple(str(token) for token in tokens)
    if MASK_TOKEN in values:
        raise ValueError("formula denoiser mask token unexpectedly entered the base vocabulary")
    return PCRCVocabulary((*values, MASK_TOKEN))


def masked_reference_corruption(
    clean_tokens: Sequence[str],
    *,
    target_id: str,
) -> tuple[str, ...] | None:
    positions = [
        index
        for index, token in enumerate(clean_tokens)
        if token.startswith("OFFSET_")
        or token.startswith("DIGIT_")
        or token in {"ROW_REL", "ROW_ABS", "COL_REL", "COL_ABS", "SELF", "OTHER"}
    ]
    if not positions:
        return None
    choice = int(hashlib.sha256(target_id.encode("ascii")).hexdigest(), 16) % len(positions)
    result = list(clean_tokens)
    result[positions[choice]] = MASK_TOKEN
    return tuple(result)


def _stable_limit(rows: Sequence[FormulaBase], maximum: int) -> list[FormulaBase]:
    ordered = sorted(rows, key=lambda row: row.target_id)
    return ordered if maximum <= 0 else ordered[:maximum]


def load_bases(
    corpus: Path,
    vocabulary: PCRCVocabulary,
    *,
    maximum_targets_per_split: int = 0,
) -> dict[str, list[FormulaBase]]:
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
        raise ValueError("formula denoiser corpus receipt violates the public pilot contract")
    splits: dict[str, list[FormulaBase]] = defaultdict(list)
    for path in sorted((corpus / "workbook_shards").glob("*.json")):
        payload = json.loads(path.read_text(encoding="ascii"))
        for item in payload["examples"]:
            clean_tokens = tuple(str(token) for token in item["observed_tokens"])
            mutations = token_mutations(clean_tokens, maximum=len(MUTATION_FAMILIES))
            corruption_ids = {
                family: vocabulary.encode(tokens, maximum=MAX_FORMULA_TOKENS)
                for family, tokens in mutations
            }
            masked_reference = masked_reference_corruption(
                clean_tokens, target_id=str(item["target_id"])
            )
            if masked_reference is not None:
                corruption_ids["masked_reference"] = vocabulary.encode(
                    masked_reference, maximum=MAX_FORMULA_TOKENS
                )
            if not corruption_ids:
                continue
            split = str(item["split"])
            splits[split].append(FormulaBase(
                target_id=str(item["target_id"]),
                workbook_id=str(item["workbook_id"]),
                structure_group=str(item["structure_group"]),
                context_ids=vocabulary.encode(
                    item["context_tokens"], maximum=MAX_CONTEXT_TOKENS
                ),
                clean_ids=vocabulary.encode(clean_tokens, maximum=MAX_FORMULA_TOKENS),
                corruptions=corruption_ids,
            ))
    return {
        split: _stable_limit(rows, maximum_targets_per_split)
        for split, rows in splits.items()
    }


def collate_rows(
    rows: Sequence[tuple[FormulaBase, str, tuple[int, ...]]],
) -> dict[str, object]:
    sources: list[tuple[int, ...]] = []
    segments: list[tuple[int, ...]] = []
    targets: list[tuple[int, ...]] = []
    corrupted: list[tuple[int, ...]] = []
    for base, _, corrupted_ids in rows:
        source, segment = denoising_source(
            base.context_ids,
            corrupted_ids,
            maximum_length=MAX_SOURCE_TOKENS,
        )
        sources.append(source)
        segments.append(segment)
        targets.append(base.clean_ids)
        corrupted.append(corrupted_ids)
    source_width = max(map(len, sources))
    target_width = max(map(len, targets))
    source_tensor = torch.zeros((len(rows), source_width), dtype=torch.long)
    segment_tensor = torch.zeros_like(source_tensor)
    target_tensor = torch.zeros((len(rows), target_width), dtype=torch.long)
    for index, (source, segment, target) in enumerate(zip(sources, segments, targets)):
        source_tensor[index, : len(source)] = torch.tensor(source)
        segment_tensor[index, : len(segment)] = torch.tensor(segment)
        target_tensor[index, : len(target)] = torch.tensor(target)
    return {
        "source_ids": source_tensor,
        "source_segments": segment_tensor,
        "target_ids": target_tensor,
        "targets": targets,
        "corrupted": corrupted,
        "bases": [row[0] for row in rows],
        "families": [row[1] for row in rows],
    }


def make_loader(
    dataset: DenoisingDataset,
    *,
    batch_size: int,
    workers: int,
    shuffle: bool,
    seed: int,
) -> DataLoader:
    generator = torch.Generator()
    generator.manual_seed(seed)
    options: dict[str, object] = {}
    if workers:
        options.update(persistent_workers=True, prefetch_factor=2)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=workers,
        pin_memory=True,
        collate_fn=collate_rows,
        generator=generator,
        **options,
    )


def _sequence_key(ids: Sequence[int]) -> str:
    digest = hashlib.sha256()
    for value in ids:
        digest.update(int(value).to_bytes(4, "little"))
    return digest.hexdigest()


def peer_formula_bodies(context_ids: Sequence[int], vocabulary: PCRCVocabulary) -> list[tuple[int, ...]]:
    try:
        peer_start = vocabulary.ids["PEER_START"]
        peer_end = vocabulary.ids["PEER_END"]
    except KeyError as exc:
        raise ValueError("formula denoiser vocabulary lacks peer markers") from exc
    peers: list[tuple[int, ...]] = []
    position = 0
    while position < len(context_ids):
        if context_ids[position] != peer_start:
            position += 1
            continue
        try:
            end = context_ids.index(peer_end, position + 1)
        except ValueError:
            break
        if end > position + 3:
            peers.append(tuple(context_ids[position + 3 : end]))
        position = end + 1
    return peers


def peer_mode_prediction(
    base: FormulaBase,
    corrupted_ids: Sequence[int],
    frequency: Mapping[tuple[int, ...], int],
    vocabulary: PCRCVocabulary,
) -> tuple[int, ...]:
    peers = peer_formula_bodies(base.context_ids, vocabulary)
    if not peers:
        return tuple(corrupted_ids)
    counts = Counter(peers)
    body = max(
        counts,
        key=lambda candidate: (
            counts[candidate],
            frequency.get((vocabulary.ids["<START>"], *candidate, vocabulary.ids["<END>"]), 0),
            _sequence_key(candidate),
        ),
    )
    return (vocabulary.ids["<START>"], *body, vocabulary.ids["<END>"])


def canonical_generated(ids: Iterable[int], *, end_id: int) -> tuple[int, ...]:
    result = []
    for value in ids:
        result.append(int(value))
        if int(value) == end_id:
            break
    return tuple(result)


def _accuracy(values: Sequence[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


@torch.no_grad()
def evaluate(
    model: FormulaDenoiser,
    dataset: DenoisingDataset,
    *,
    vocabulary: PCRCVocabulary,
    frequency: Mapping[tuple[int, ...], int],
    device: torch.device,
    batch_size: int,
    workers: int,
    beam_size: int,
) -> dict[str, object]:
    model.eval()
    rows: list[dict[str, object]] = []
    loader = make_loader(
        dataset,
        batch_size=batch_size,
        workers=workers,
        shuffle=False,
        seed=SEED,
    )
    start_id = vocabulary.ids["<START>"]
    end_id = vocabulary.ids["<END>"]
    for batch in loader:
        source_ids = batch["source_ids"].to(device, non_blocking=True)
        source_segments = batch["source_segments"].to(device, non_blocking=True)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            beams, _ = model.beam_generate(
                source_ids,
                source_segments,
                start_id=start_id,
                end_id=end_id,
                beam_size=beam_size,
            )
        generated = beams.detach().cpu().tolist()
        for index, base in enumerate(batch["bases"]):
            target = tuple(batch["targets"][index])
            corrupted = tuple(batch["corrupted"][index])
            predictions = [
                canonical_generated(sequence, end_id=end_id)
                for sequence in generated[index]
            ]
            peer = peer_mode_prediction(base, corrupted, frequency, vocabulary)
            rows.append({
                "family": batch["families"][index],
                "group": base.structure_group,
                "top1": predictions[0] == target,
                "topk": target in predictions,
                "peer": peer == target,
                "acted": predictions[0] != corrupted,
            })
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    families: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["group"])].append(row)
        families[str(row["family"])].append(row)
    top1 = _accuracy([bool(row["top1"]) for row in rows])
    peer = _accuracy([bool(row["peer"]) for row in rows])
    return {
        "targets": len(rows),
        "structure_groups": len(groups),
        "beam_size": beam_size,
        "top1_exact_recovery": top1,
        "topk_exact_coverage": _accuracy([bool(row["topk"]) for row in rows]),
        "peer_mode_exact_recovery": peer,
        "top1_delta_over_peer_mode": top1 - peer,
        "action_rate": _accuracy([bool(row["acted"]) for row in rows]),
        "structure_group_macro_top1": sum(
            _accuracy([bool(row["top1"]) for row in values])
            for values in groups.values()
        ) / len(groups),
        "by_family": {
            family: {
                "targets": len(values),
                "top1_exact_recovery": _accuracy([
                    bool(row["top1"]) for row in values
                ]),
                "topk_exact_coverage": _accuracy([
                    bool(row["topk"]) for row in values
                ]),
                "peer_mode_exact_recovery": _accuracy([
                    bool(row["peer"]) for row in values
                ]),
                "action_rate": _accuracy([bool(row["acted"]) for row in values]),
            }
            for family, values in sorted(families.items())
        },
    }


def cpu_state(model: FormulaDenoiser) -> dict[str, Tensor]:
    return {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}


def train_epoch(
    model: FormulaDenoiser,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    *,
    device: torch.device,
    gradient_clip: float,
) -> float:
    model.train()
    total_loss = 0.0
    target_tokens = 0
    for batch in loader:
        source_ids = batch["source_ids"].to(device, non_blocking=True)
        source_segments = batch["source_segments"].to(device, non_blocking=True)
        target_ids = batch["target_ids"].to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            logits = model(source_ids, source_segments, target_ids[:, :-1])
            labels = target_ids[:, 1:]
            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                labels.reshape(-1),
                ignore_index=0,
            )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)
        optimizer.step()
        count = int(labels.ne(0).sum().item())
        total_loss += float(loss.item()) * count
        target_tokens += count
    return total_loss / target_tokens


def train(
    *,
    corpus: Path,
    output: Path,
    held_out_family: str | None,
    evaluation_family: str,
    epochs: int,
    batch_size: int,
    workers: int,
    maximum_targets_per_split: int,
    final_beam_size: int,
) -> Path:
    require_clean_tracked_worktree()
    if held_out_family is not None and held_out_family not in MUTATION_FAMILIES:
        raise ValueError("unknown formula denoiser held-out family")
    if evaluation_family not in MUTATION_FAMILIES:
        raise ValueError("unknown formula denoiser evaluation family")
    if not torch.cuda.is_available():
        raise ValueError("formula denoiser training requires CUDA")
    if epochs < 1 or batch_size < 1 or workers < 0 or workers > 24:
        raise ValueError("formula denoiser training configuration is invalid")
    if output.exists():
        raise ValueError("formula denoiser output already exists")
    configure(SEED)
    vocabulary = load_vocabulary(corpus / "vocabulary.json")
    complete_splits = load_bases(
        corpus,
        vocabulary,
        maximum_targets_per_split=0,
    )
    splits = {
        split: _stable_limit(rows, maximum_targets_per_split)
        for split, rows in complete_splits.items()
    }
    train_bases = splits["train"]
    calibration_bases = splits["calibration"]
    internal_bases = splits["internal_test"]
    train_families = tuple(
        family for family in MUTATION_FAMILIES if family != held_out_family
    ) + ("masked_reference",)
    training = DenoisingDataset(train_bases, train_families, include_clean=True)
    calibration_recovery = DenoisingDataset(
        calibration_bases, (evaluation_family,), include_clean=False
    )
    calibration_controls = DenoisingDataset(
        calibration_bases, (), include_clean=True
    )
    internal_recovery = DenoisingDataset(
        internal_bases, (evaluation_family,), include_clean=False
    )
    internal_controls = DenoisingDataset(internal_bases, (), include_clean=True)
    selection_bases = calibration_bases[: min(512, len(calibration_bases))]
    selection_recovery = DenoisingDataset(
        selection_bases, (evaluation_family,), include_clean=False
    )
    selection_controls = DenoisingDataset(selection_bases, (), include_clean=True)
    if not all((len(training), len(calibration_recovery), len(internal_recovery))):
        raise ValueError("formula denoiser split has no eligible examples")
    frequency = Counter(base.clean_ids for base in train_bases)
    allowed_output_ids = {
        vocabulary.ids["<UNK>"],
        vocabulary.ids["<END>"],
        *(
            token
            for base in complete_splits["train"]
            for token in base.clean_ids[1:-1]
        ),
    }
    output.mkdir(parents=True)
    metadata = {
        "protocol": PROTOCOL,
        "status": "exploratory_public_development",
        "git_commit": git_commit(),
        "corpus_receipt_sha256": sha256_file(corpus / "corpus_receipt.json"),
        "vocabulary_sha256": sha256_file(corpus / "vocabulary.json"),
        "model_vocabulary_sha256": hashlib.sha256(
            "\0".join(vocabulary.tokens).encode("ascii")
        ).hexdigest(),
        "held_out_explicit_mutation_family": held_out_family,
        "evaluation_mutation_family": evaluation_family,
        "training_mutation_families": list(train_families),
        "evaluation_mutation_family_entered_training": evaluation_family in train_families,
        "reference_structure_self_supervision": "single_token_masking",
        "train_bases": len(train_bases),
        "training_rows": len(training),
        "calibration_recovery_rows": len(calibration_recovery),
        "calibration_control_rows": len(calibration_controls),
        "internal_recovery_rows": len(internal_recovery),
        "internal_control_rows": len(internal_controls),
        "selection_calibration_bases": len(selection_bases),
        "maximum_targets_per_split": maximum_targets_per_split,
        "output_grammar_train_bases": len(complete_splits["train"]),
        "epochs": epochs,
        "batch_size": batch_size,
        "workers": workers,
        "seed": SEED,
        "learning_rate": 3e-4,
        "weight_decay": 1e-4,
        "gradient_clip": 1.0,
        "precision": "bfloat16",
        "model": {
            "type": "transformer_encoder_decoder",
            "model_size": 192,
            "attention_heads": 8,
            "encoder_layers": 3,
            "decoder_layers": 3,
            "feedforward_size": 768,
            "maximum_source_tokens": MAX_SOURCE_TOKENS,
            "maximum_target_tokens": MAX_FORMULA_TOKENS,
        },
        "fault_label_inputs": [],
        "answer_workbook_inputs": [],
        "protected_data_inputs": [],
    }
    write_json_atomic(output / "metadata.json", metadata)
    device = torch.device("cuda:0")
    model = FormulaDenoiser(
        len(vocabulary.tokens),
        allowed_output_ids=sorted(allowed_output_ids),
        maximum_source_length=MAX_SOURCE_TOKENS,
        maximum_target_length=MAX_FORMULA_TOKENS,
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=3e-4, weight_decay=1e-4, fused=True
    )
    loader = make_loader(
        training,
        batch_size=batch_size,
        workers=workers,
        shuffle=True,
        seed=SEED,
    )
    history = []
    best_score: tuple[float, ...] | None = None
    best_state: dict[str, Tensor] | None = None
    best_epoch = 0
    stale = 0
    for epoch in range(1, epochs + 1):
        mean_loss = train_epoch(
            model, loader, optimizer, device=device, gradient_clip=1.0
        )
        recovery = evaluate(
            model,
            selection_recovery,
            vocabulary=vocabulary,
            frequency=frequency,
            device=device,
            batch_size=max(8, batch_size // 2),
            workers=workers,
            beam_size=1,
        )
        controls = evaluate(
            model,
            selection_controls,
            vocabulary=vocabulary,
            frequency=frequency,
            device=device,
            batch_size=max(8, batch_size // 2),
            workers=workers,
            beam_size=1,
        )
        net_recovery = (
            float(recovery["top1_exact_recovery"])
            - float(controls["action_rate"])
        )
        score = (
            net_recovery,
            float(recovery["top1_exact_recovery"]),
            -float(controls["action_rate"]),
            float(recovery["structure_group_macro_top1"]),
            -mean_loss,
        )
        history.append({
            "epoch": epoch,
            "mean_token_loss": mean_loss,
            "calibration_recovery": recovery,
            "calibration_controls": controls,
            "selection_score": list(score),
        })
        write_json_atomic(output / "history.json", {"protocol": PROTOCOL, "epochs": history})
        if best_score is None or score > best_score:
            best_score = score
            best_state = cpu_state(model)
            best_epoch = epoch
            stale = 0
        else:
            stale += 1
            if stale >= 3:
                break
    if best_state is None:
        raise ValueError("formula denoiser did not produce a checkpoint")
    model.load_state_dict(best_state, strict=True)
    calibration_metrics = evaluate(
        model,
        calibration_recovery,
        vocabulary=vocabulary,
        frequency=frequency,
        device=device,
        batch_size=max(4, batch_size // final_beam_size),
        workers=workers,
        beam_size=final_beam_size,
    )
    calibration_control_metrics = evaluate(
        model,
        calibration_controls,
        vocabulary=vocabulary,
        frequency=frequency,
        device=device,
        batch_size=max(4, batch_size // final_beam_size),
        workers=workers,
        beam_size=1,
    )
    internal_metrics = evaluate(
        model,
        internal_recovery,
        vocabulary=vocabulary,
        frequency=frequency,
        device=device,
        batch_size=max(4, batch_size // final_beam_size),
        workers=workers,
        beam_size=final_beam_size,
    )
    internal_control_metrics = evaluate(
        model,
        internal_controls,
        vocabulary=vocabulary,
        frequency=frequency,
        device=device,
        batch_size=max(4, batch_size // final_beam_size),
        workers=workers,
        beam_size=1,
    )
    model_path = output / "selected_model.pt"
    temporary = model_path.with_suffix(".pt.tmp")
    torch.save({
        "protocol": PROTOCOL,
        "git_commit": metadata["git_commit"],
        "held_out_explicit_mutation_family": held_out_family,
        "evaluation_mutation_family": evaluation_family,
        "best_epoch": best_epoch,
        "vocabulary_sha256": metadata["vocabulary_sha256"],
        "model_vocabulary_sha256": metadata["model_vocabulary_sha256"],
        "model_state": best_state,
    }, temporary)
    os.replace(temporary, model_path)
    promising = (
        float(internal_metrics["top1_delta_over_peer_mode"]) >= 0.02
        and float(internal_metrics["topk_exact_coverage"]) >= 0.60
        and float(internal_control_metrics["action_rate"]) <= 0.10
    )
    receipt = {
        **metadata,
        "complete": True,
        "selected_epoch": best_epoch,
        "selected_model_sha256": sha256_file(model_path),
        "final_beam_size": final_beam_size,
        "calibration_recovery_metrics": calibration_metrics,
        "calibration_control_metrics": calibration_control_metrics,
        "internal_recovery_metrics": internal_metrics,
        "internal_control_metrics": internal_control_metrics,
        "development_gate": {
            "minimum_delta_over_peer_mode": 0.02,
            "minimum_topk_exact_coverage": 0.60,
            "maximum_clean_control_action_rate": 0.10,
        },
        "model_development_result": "promising" if promising else "insufficient",
        "public_localization_authorized": promising,
        "formal_version_authorized": False,
    }
    receipt_path = output / "receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--held-out-family", choices=("none", *MUTATION_FAMILIES), default="none"
    )
    parser.add_argument(
        "--evaluation-family", choices=MUTATION_FAMILIES, default="reference_offset"
    )
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=192)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--maximum-targets-per-split", type=int, default=0)
    parser.add_argument("--final-beam-size", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        print(train(
            corpus=args.corpus.resolve(),
            output=args.output.resolve(),
            held_out_family=(
                None if args.held_out_family == "none" else args.held_out_family
            ),
            evaluation_family=args.evaluation_family,
            epochs=args.epochs,
            batch_size=args.batch_size,
            workers=args.workers,
            maximum_targets_per_split=args.maximum_targets_per_split,
            final_beam_size=args.final_beam_size,
        ))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"formula denoiser pilot refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
