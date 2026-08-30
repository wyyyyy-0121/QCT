"""Strict ForTaP loading and tensorization for the preregistered FCRL adapter."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Sequence

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .fcrl import (
    FCRLTableInput,
    MAX_CELL_TOKENS,
    MAX_INPUT_TOKENS,
)


EXPECTED_CHECKPOINT_SHA256 = "42c2166afb60fedf833fcdbc4469dd6e23611f786aa7220a20375117c6c5a4a1"
EXPECTED_SOURCE_COMMIT = "4de8bba4e9bf6a89b2e131bfb471b4db2c45b951"
EXPECTED_BACKBONE_TENSORS = 205
SEED = 260831


class FCRLTorchError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialModules:
    tokenizer: ModuleType
    backbones: ModuleType
    generation: ModuleType
    utils: ModuleType


@dataclass
class FCRLTensorBatch:
    token_id: Tensor
    num_mag: Tensor
    num_pre: Tensor
    num_top: Tensor
    num_low: Tensor
    token_order: Tensor
    pos_row: Tensor
    pos_col: Tensor
    pos_top: Tensor
    pos_left: Tensor
    format_vec: Tensor
    indicator: Tensor
    formula_label: Tensor
    src_sketch: Tensor
    tgt_sketch: Tensor
    candi_cell_token_mask: Tensor
    range_label: Tensor
    range_maps: tuple[dict[int, str], ...]
    encoder_hashes: tuple[str, ...]
    reachable_references: tuple[int, ...]
    total_references: tuple[int, ...]

    def to(self, device: str | torch.device) -> "FCRLTensorBatch":
        values: dict[str, object] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            values[field.name] = value.to(device) if isinstance(value, Tensor) else value
        return FCRLTensorBatch(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class FCRLTokenizerRuntime:
    args: SimpleNamespace
    official: OfficialModules
    tokenizer: object


@dataclass(frozen=True)
class FCRLRuntime(FCRLTokenizerRuntime):
    model: "FCRLModel"
    checkpoint_sha256: str
    checkpoint_bytes: int
    loaded_backbone_tensors: int


@dataclass
class _Prepared:
    token_id: list[int]
    num_mag: list[int]
    num_pre: list[int]
    num_top: list[int]
    num_low: list[int]
    token_order: list[int]
    pos_row: list[int]
    pos_col: list[int]
    pos_top: list[list[int]]
    pos_left: list[list[int]]
    format_vec: list[list[float]]
    indicator: list[int]
    formula_label: list[int]
    src_sketch: list[int]
    tgt_sketch: list[int]
    candi_cell_token_mask: list[int]
    range_label: list[int]
    range_map: dict[int, str]
    encoder_hash: str
    reachable_references: int
    total_references: int


@dataclass(frozen=True)
class BeamPrediction:
    key: str
    sketch_token_ids: tuple[int, ...]
    range_token_indices: tuple[int, ...]
    normalized_log_probability: float


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_module_location(module: ModuleType, root: Path) -> None:
    module_file = Path(str(module.__file__)).resolve()
    try:
        module_file.relative_to(root)
    except ValueError as exc:
        raise FCRLTorchError(f"official_module_outside_fixed_source:{module.__name__}") from exc


def import_official_fortap(source_root: str | Path) -> OfficialModules:
    """Import only official modules that do not require torch_scatter."""
    fortap_root = Path(source_root).resolve() / "fortap"
    required = (
        fortap_root / "tokenizer.py",
        fortap_root / "model" / "backbones.py",
        fortap_root / "model" / "generation.py",
    )
    if not all(path.is_file() for path in required):
        raise FCRLTorchError("official_fortap_source_missing")
    root_text = str(fortap_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    tokenizer_module = importlib.import_module("tokenizer")
    backbones_module = importlib.import_module("model.backbones")
    generation_module = importlib.import_module("model.generation")
    utils_module = importlib.import_module("utils")
    for module in (tokenizer_module, backbones_module, generation_module, utils_module):
        _assert_module_location(module, fortap_root)
    return OfficialModules(tokenizer_module, backbones_module, generation_module, utils_module)


def fixed_config(vocab_path: str | Path) -> SimpleNamespace:
    return SimpleNamespace(
        vocab_path=str(Path(vocab_path)),
        context_repo_path=None,
        cellstr_repo_path=None,
        vocab_size=30522,
        hidden_size=768,
        intermediate_size=3072,
        magnitude_size=10,
        precision_size=10,
        top_digit_size=10,
        low_digit_size=10,
        row_size=256,
        column_size=256,
        tree_depth=4,
        node_degree=[32, 32, 64, 256],
        num_format_feature=11,
        attention_distance=8,
        attention_step=0,
        num_attention_heads=12,
        num_encoder_layers=12,
        hidden_dropout_prob=0.1,
        attention_dropout_prob=0.1,
        layer_norm_eps=1e-6,
        hidden_act="gelu",
        max_cell_length=64,
        max_seq_len=MAX_INPUT_TOKENS,
        text_threshold=0.5,
        value_threshold=0.1,
        clc_rate=0.3,
        wcm_rate=0.3,
        target="formula_prediction",
        attn_method="add",
        generation_model="LSTM_attn",
        gen_hidden_size=768,
        gen_num_attention_heads=8,
        LSTM_num_layers=3,
        beam_size=5,
        beam_alpha=1.0,
        beam_gamma=0.0,
        ideal_length=10,
        max_length=64,
    )


class FCRLModel(nn.Module):
    def __init__(self, backbone: nn.Module, decoder: nn.Module, hidden_size: int):
        super().__init__()
        self.backbone = backbone
        self.decoder = decoder
        self.hidden_size = hidden_size
        self.backbone.eval()

    def train(self, mode: bool = True) -> "FCRLModel":
        super().train(mode)
        self.backbone.eval()
        return self

    def encode(self, batch: FCRLTensorBatch) -> Tensor:
        with torch.no_grad():
            return self.backbone(
                token_id=batch.token_id,
                num_mag=batch.num_mag,
                num_pre=batch.num_pre,
                num_top=batch.num_top,
                num_low=batch.num_low,
                token_order=batch.token_order,
                pos_row=batch.pos_row,
                pos_col=batch.pos_col,
                pos_top=batch.pos_top,
                pos_left=batch.pos_left,
                format_vec=batch.format_vec,
                indicator=batch.indicator,
            )

    def decoder_loss(self, batch: FCRLTensorBatch) -> tuple[Tensor, Tensor, Tensor]:
        encoded = self.encode(batch).detach()
        batch_size = encoded.size(0)
        selected = encoded[batch.formula_label == 1]
        if selected.numel() != batch_size * 2 * self.hidden_size:
            raise FCRLTorchError("formula_marker_count_changed")
        formula_states = selected.view(batch_size, 2, self.hidden_size)[:, 0, :]
        sketch_logits, sketch_hidden = self.decoder.sketch_logits(
            batch.src_sketch, encoded, formula_states
        )
        sketch_loss = F.nll_loss(
            F.log_softmax(sketch_logits, dim=-1).view(-1, sketch_logits.size(-1)),
            batch.tgt_sketch.view(-1),
            reduction="mean",
            ignore_index=self.decoder.padding_idx,
        )
        range_logits, _ = self.decoder.range_logits(
            sketch_hidden, encoded, batch.candi_cell_token_mask, formula_states
        )
        flat_labels = batch.range_label.view(-1)
        valid_ranges = flat_labels != 0
        if bool(valid_ranges.any()):
            flat_log_probs = F.log_softmax(range_logits, dim=-1).view(-1, range_logits.size(-1))
            range_loss = F.nll_loss(
                flat_log_probs[valid_ranges],
                flat_labels[valid_ranges],
                reduction="mean",
            )
        else:
            range_loss = range_logits.sum() * 0.0
        return sketch_loss + range_loss, sketch_loss, range_loss


def load_tokenizer_runtime(source_root: str | Path) -> FCRLTokenizerRuntime:
    source_root = Path(source_root).resolve()
    official = import_official_fortap(source_root)
    args = fixed_config(source_root / "fortap" / "vocab" / "bert_vocab.txt")
    tokenizer = official.tokenizer.FPTokenizer(args)
    args.tokenizer = tokenizer
    return FCRLTokenizerRuntime(args=args, official=official, tokenizer=tokenizer)


def load_runtime(source_root: str | Path, checkpoint_path: str | Path) -> FCRLRuntime:
    source_root = Path(source_root).resolve()
    checkpoint_path = Path(checkpoint_path).resolve()
    checkpoint_hash = sha256_file(checkpoint_path)
    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise FCRLTorchError("checkpoint_hash_mismatch_or_forbidden_checkpoint")
    tokenizer_runtime = load_tokenizer_runtime(source_root)
    official = tokenizer_runtime.official
    args = tokenizer_runtime.args
    tokenizer = tokenizer_runtime.tokenizer

    backbone = official.backbones.BbForTuta(args)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    backbone_state = {
        key.removeprefix("backbone."): value
        for key, value in checkpoint.items()
        if key.startswith("backbone.")
    }
    current_state = backbone.state_dict()
    if len(backbone_state) != EXPECTED_BACKBONE_TENSORS:
        raise FCRLTorchError("backbone_tensor_count_mismatch")
    if set(backbone_state) != set(current_state):
        raise FCRLTorchError("backbone_key_mismatch")
    if any(backbone_state[key].shape != current_state[key].shape for key in current_state):
        raise FCRLTorchError("backbone_shape_mismatch")
    backbone.load_state_dict(backbone_state, strict=True)
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)
    backbone.eval()

    devices = [] if not torch.cuda.is_available() else list(range(torch.cuda.device_count()))
    with torch.random.fork_rng(devices=devices):
        torch.manual_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        decoder = official.generation.LSTMLM(args)
        for name, parameter in decoder.named_parameters():
            if "gamma" not in name and "beta" not in name:
                parameter.data.normal_(0.0, 0.02)
    original_attention_forward = decoder.attn.forward

    def attention_layout_compat(query, key, value, *forward_args, **forward_kwargs):
        return original_attention_forward(
            query,
            key.transpose(0, 1),
            value.transpose(0, 1),
            *forward_args,
            **forward_kwargs,
        )

    decoder.attn.forward = attention_layout_compat
    decoder.decoder.dropout = 0.1
    decoder.range_encoder.dropout = 0.1
    decoder.attn.dropout = 0.1
    model = FCRLModel(backbone, decoder, args.hidden_size)
    return FCRLRuntime(
        args=args,
        official=official,
        tokenizer=tokenizer,
        model=model,
        checkpoint_sha256=checkpoint_hash,
        checkpoint_bytes=checkpoint_path.stat().st_size,
        loaded_backbone_tensors=len(backbone_state),
    )


def _encoder_hash(values: dict[str, object]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prepare(table: FCRLTableInput, runtime: FCRLTokenizerRuntime) -> _Prepared:
    tokenizer = runtime.tokenizer
    token_matrix, number_matrix = tokenizer.tokenize_string_matrix(
        table.string_matrix,
        add_separate=True,
        max_cell_len=MAX_CELL_TOKENS,
    )
    formula_info = {
        "A1": table.target[1],
        "FormulaTokens": list(table.formula_prefix.tokens),
        "FormulaTokenTypes": list(table.formula_prefix.token_types),
    }
    semi = tokenizer.fp_preprocess(
        token_matrix,
        number_matrix,
        (table.top_positions, table.left_positions),
        (table.header_rows, table.header_columns),
        table.target_row,
        table.target_column,
        table.table_range,
        formula_info,
        format_matrix=table.format_matrix,
        context=None,
        add_sep=True,
    )
    (
        token_cells,
        number_cells,
        position_cells,
        format_cells,
        indicator_cells,
        formula_cells,
        complete_sketch,
        candidate_cells,
        range_label,
        range_map,
    ) = semi

    token_id: list[int] = []
    num_mag: list[int] = []
    num_pre: list[int] = []
    num_top: list[int] = []
    num_low: list[int] = []
    token_order: list[int] = []
    pos_row: list[int] = []
    pos_col: list[int] = []
    pos_top: list[list[int]] = []
    pos_left: list[list[int]] = []
    format_vec: list[list[float]] = []
    indicator: list[int] = []
    formula_label: list[int] = []
    candidate_mask: list[int] = []
    full_range_map: dict[int, str] = {}
    top_left = table.table_range.split(":", 1)[0]
    from .a1 import parse_address, num_to_col

    top_left_address = parse_address(top_left)
    for tokens, numbers, position, fmt, cell_indicator, cell_formula, cell_candidate in zip(
        token_cells,
        number_cells,
        position_cells,
        format_cells,
        indicator_cells,
        formula_cells,
        candidate_cells,
        strict=True,
    ):
        cell_len = len(tokens)
        sequence_start = len(token_id)
        token_id.extend(tokens)
        token_order.extend(range(cell_len))
        num_mag.extend(number[0] for number in numbers)
        num_pre.extend(number[1] for number in numbers)
        num_top.extend(number[2] for number in numbers)
        num_low.extend(number[3] for number in numbers)
        row, col, top, left = position
        pos_row.extend([row] * cell_len)
        pos_col.extend([col] * cell_len)
        expanded_top = runtime.official.utils.zip_to_index(top, runtime.args.node_degree, sum(runtime.args.node_degree))
        expanded_left = runtime.official.utils.zip_to_index(left, runtime.args.node_degree, sum(runtime.args.node_degree))
        pos_top.extend([expanded_top] * cell_len)
        pos_left.extend([expanded_left] * cell_len)
        format_vec.extend([list(fmt)] * cell_len)
        indicator.extend(cell_indicator)
        formula_label.extend(cell_formula)
        candidate_mask.extend(cell_candidate)
        row, col, _top, _left = position
        if (
            cell_candidate
            and cell_candidate[0] == 1
            and sequence_start < MAX_INPUT_TOKENS - 1
            and row < runtime.args.row_size
            and col < runtime.args.column_size
        ):
            full_range_map[sequence_start] = (
                f"{num_to_col(top_left_address.col + col)}{top_left_address.row + row}"
            )

    encoder_values = {
        "token_id": token_id[:MAX_INPUT_TOKENS],
        "num_mag": num_mag[:MAX_INPUT_TOKENS],
        "num_pre": num_pre[:MAX_INPUT_TOKENS],
        "num_top": num_top[:MAX_INPUT_TOKENS],
        "num_low": num_low[:MAX_INPUT_TOKENS],
        "token_order": token_order[:MAX_INPUT_TOKENS],
        "pos_row": pos_row[:MAX_INPUT_TOKENS],
        "pos_col": pos_col[:MAX_INPUT_TOKENS],
        "pos_top": pos_top[:MAX_INPUT_TOKENS],
        "pos_left": pos_left[:MAX_INPUT_TOKENS],
        "format_vec": format_vec[:MAX_INPUT_TOKENS],
        "indicator": indicator[:MAX_INPUT_TOKENS],
        "formula_label": formula_label[:MAX_INPUT_TOKENS],
        "candidate_mask": candidate_mask[:MAX_INPUT_TOKENS],
    }
    if sum(encoder_values["formula_label"]) != 2:  # type: ignore[arg-type]
        raise FCRLTorchError("target_marker_truncated")

    official_null = runtime.official.tokenizer.DEFAULT_RANGE_LABEL
    retained_range = [
        official_null if value >= MAX_INPUT_TOKENS - 1 else value
        for value in range_label
    ]
    cell_positions = [
        index
        for index, token_type in enumerate(table.formula_prefix.token_types)
        if token_type == "CELL"
    ]
    reachable = sum(retained_range[index] != official_null for index in cell_positions)
    retained_map = full_range_map
    return _Prepared(
        token_id=encoder_values["token_id"],  # type: ignore[arg-type]
        num_mag=encoder_values["num_mag"],  # type: ignore[arg-type]
        num_pre=encoder_values["num_pre"],  # type: ignore[arg-type]
        num_top=encoder_values["num_top"],  # type: ignore[arg-type]
        num_low=encoder_values["num_low"],  # type: ignore[arg-type]
        token_order=encoder_values["token_order"],  # type: ignore[arg-type]
        pos_row=encoder_values["pos_row"],  # type: ignore[arg-type]
        pos_col=encoder_values["pos_col"],  # type: ignore[arg-type]
        pos_top=encoder_values["pos_top"],  # type: ignore[arg-type]
        pos_left=encoder_values["pos_left"],  # type: ignore[arg-type]
        format_vec=encoder_values["format_vec"],  # type: ignore[arg-type]
        indicator=encoder_values["indicator"],  # type: ignore[arg-type]
        formula_label=encoder_values["formula_label"],  # type: ignore[arg-type]
        src_sketch=list(complete_sketch[:-1]),
        tgt_sketch=list(complete_sketch[1:]),
        candi_cell_token_mask=encoder_values["candidate_mask"],  # type: ignore[arg-type]
        range_label=retained_range,
        range_map=retained_map,
        encoder_hash=_encoder_hash(encoder_values),
        reachable_references=reachable,
        total_references=len(cell_positions),
    )


def tensorize_tables(
    tables: Sequence[FCRLTableInput], runtime: FCRLTokenizerRuntime
) -> FCRLTensorBatch:
    if not tables:
        raise FCRLTorchError("empty_batch")
    prepared = [_prepare(table, runtime) for table in tables]
    seq_len = min(
        MAX_INPUT_TOKENS,
        ((max(len(item.token_id) for item in prepared) + 7) // 8) * 8,
    )
    sketch_len = ((max(len(item.src_sketch) for item in prepared) + 7) // 8) * 8
    default_number = runtime.args.magnitude_size + 1
    default_position = [sum(runtime.args.node_degree)] * runtime.args.tree_depth
    pad_id = runtime.official.tokenizer.PAD_ID
    fp_pad = runtime.official.tokenizer.FP_PAD_TAG

    def pad(values: list, length: int, default: object) -> list:
        return values + [default for _ in range(length - len(values))]

    return FCRLTensorBatch(
        token_id=torch.tensor([pad(item.token_id, seq_len, pad_id) for item in prepared], dtype=torch.long),
        num_mag=torch.tensor([pad(item.num_mag, seq_len, default_number) for item in prepared], dtype=torch.long),
        num_pre=torch.tensor([pad(item.num_pre, seq_len, runtime.args.precision_size + 1) for item in prepared], dtype=torch.long),
        num_top=torch.tensor([pad(item.num_top, seq_len, runtime.args.top_digit_size + 1) for item in prepared], dtype=torch.long),
        num_low=torch.tensor([pad(item.num_low, seq_len, runtime.args.low_digit_size + 1) for item in prepared], dtype=torch.long),
        token_order=torch.tensor([pad(item.token_order, seq_len, 0) for item in prepared], dtype=torch.long),
        pos_row=torch.tensor([pad(item.pos_row, seq_len, runtime.args.row_size) for item in prepared], dtype=torch.long),
        pos_col=torch.tensor([pad(item.pos_col, seq_len, runtime.args.column_size) for item in prepared], dtype=torch.long),
        pos_top=torch.tensor([pad(item.pos_top, seq_len, default_position) for item in prepared], dtype=torch.long),
        pos_left=torch.tensor([pad(item.pos_left, seq_len, default_position) for item in prepared], dtype=torch.long),
        format_vec=torch.tensor([pad(item.format_vec, seq_len, runtime.tokenizer.default_format) for item in prepared], dtype=torch.float),
        indicator=torch.tensor([pad(item.indicator, seq_len, 0) for item in prepared], dtype=torch.long),
        formula_label=torch.tensor([pad(item.formula_label, seq_len, 0) for item in prepared], dtype=torch.long),
        src_sketch=torch.tensor([pad(item.src_sketch, sketch_len, fp_pad) for item in prepared], dtype=torch.long),
        tgt_sketch=torch.tensor([pad(item.tgt_sketch, sketch_len, fp_pad) for item in prepared], dtype=torch.long),
        candi_cell_token_mask=torch.tensor([pad(item.candi_cell_token_mask, seq_len, 0) for item in prepared], dtype=torch.long),
        range_label=torch.tensor([pad(item.range_label, sketch_len, 0) for item in prepared], dtype=torch.long),
        range_maps=tuple(item.range_map for item in prepared),
        encoder_hashes=tuple(item.encoder_hash for item in prepared),
        reachable_references=tuple(item.reachable_references for item in prepared),
        total_references=tuple(item.total_references for item in prepared),
    )


@torch.no_grad()
def generate_prefix_beam(
    runtime: FCRLRuntime,
    batch: FCRLTensorBatch,
    *,
    sample_index: int = 0,
    encoded_states: Tensor | None = None,
) -> tuple[BeamPrediction, ...]:
    """Deterministic beam-5 decoding through the official LSTMLM primitives."""
    model = runtime.model
    model.eval()
    if sample_index < 0 or sample_index >= batch.token_id.size(0):
        raise FCRLTorchError("beam_sample_index_out_of_range")

    def one(tensor: Tensor) -> Tensor:
        return tensor[sample_index : sample_index + 1]

    single = FCRLTensorBatch(
        **{
            field.name: (
                one(getattr(batch, field.name))
                if isinstance(getattr(batch, field.name), Tensor)
                else (getattr(batch, field.name)[sample_index],)
            )
            for field in fields(batch)
        }
    )
    encoded = (
        model.encode(single)
        if encoded_states is None
        else encoded_states[sample_index : sample_index + 1]
    )
    selected = encoded[single.formula_label == 1]
    if selected.numel() != 2 * model.hidden_size:
        raise FCRLTorchError("formula_marker_count_changed")
    formula_state = selected.view(1, 2, model.hidden_size)[:, 0, :]
    start_id = runtime.tokenizer.fp_tok2id("<START>")
    end_id = runtime.tokenizer.fp_tok2id("<END>")
    beam_size = runtime.args.beam_size
    active: list[tuple[tuple[int, ...], float]] = [((start_id,), 0.0)]
    completed: list[tuple[tuple[int, ...], float, float]] = []

    for _ in range(1, runtime.args.max_length):
        if not active or len(completed) >= beam_size:
            break
        sequences = torch.tensor([ids for ids, _ in active], dtype=torch.long, device=encoded.device)
        repeated_encoded = encoded.repeat(len(active), 1, 1)
        repeated_formula = formula_state.repeat(len(active), 1)
        logits, _ = model.decoder.sketch_logits(
            sequences,
            repeated_encoded,
            repeated_formula,
            last_token=True,
        )
        log_probs = F.log_softmax(logits[:, -1, :], dim=-1)
        prior = torch.tensor([score for _, score in active], device=encoded.device).unsqueeze(1)
        combined = log_probs + prior
        values, flat_indices = torch.topk(combined.reshape(-1), k=min(beam_size, combined.numel()))
        next_active: list[tuple[tuple[int, ...], float]] = []
        vocab_size = combined.size(1)
        for value, flat_index in zip(values.tolist(), flat_indices.tolist(), strict=True):
            parent_index, token_id = divmod(flat_index, vocab_size)
            ids = (*active[parent_index][0], int(token_id))
            normalized_score = float(value) / ((len(ids) + 1) ** runtime.args.beam_alpha)
            if token_id == end_id:
                completed.append((ids, float(value), normalized_score))
            else:
                next_active.append((ids, float(value)))
        active = next_active

    if not completed:
        completed = [
            (ids, score, score / ((len(ids) + 1) ** runtime.args.beam_alpha))
            for ids, score in active
        ]
    completed.sort(key=lambda item: (-item[2], item[0]))
    range_map = single.range_maps[0]
    predictions: list[BeamPrediction] = []
    seen_keys: set[str] = set()
    reverse_vocab = runtime.official.generation.REV_FP_VOCAB
    range_id = runtime.tokenizer.fp_tok2id("<RANGE>")
    for ids, _raw_score, normalized_score in completed:
        source_ids = ids[:-1] if ids and ids[-1] == end_id else ids
        source = torch.tensor([source_ids], dtype=torch.long, device=encoded.device)
        _, sketch_hidden = model.decoder.sketch_logits(source, encoded, formula_state)
        range_logits, _ = model.decoder.range_logits(
            sketch_hidden,
            encoded,
            single.candi_cell_token_mask,
            formula_state,
        )
        key_tokens: list[str] = []
        pointer_indices: list[int] = []
        valid = True
        for token_index, token_id in enumerate(source_ids):
            if token_id == start_id:
                continue
            if token_id == range_id:
                if token_index == 0:
                    valid = False
                    break
                pointer = int(torch.argmax(range_logits[0, token_index - 1]).item())
                address = range_map.get(pointer)
                if address is None:
                    valid = False
                    break
                key_tokens.append(address.upper())
                pointer_indices.append(pointer)
            else:
                token = reverse_vocab.get(int(token_id))
                if token is None or token in {"<START>", "<END>"}:
                    valid = False
                    break
                key_tokens.append(token.upper())
        if not valid:
            continue
        key = " ".join(key_tokens)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        predictions.append(
            BeamPrediction(
                key=key,
                sketch_token_ids=tuple(source_ids),
                range_token_indices=tuple(pointer_indices),
                normalized_log_probability=normalized_score,
            )
        )
        if len(predictions) == beam_size:
            break
    return tuple(predictions)
