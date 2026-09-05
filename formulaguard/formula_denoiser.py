"""Context-conditioned Transformer for complete structural formula generation."""

from __future__ import annotations

import math
from collections.abc import Sequence

import torch
from torch import Tensor, nn
from torch.nn import functional as F

CONTEXT_SEGMENT = 0
CORRUPTED_FORMULA_SEGMENT = 1


def denoising_source(
    context_ids: Sequence[int],
    corrupted_formula_ids: Sequence[int],
    *,
    maximum_length: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Join masked workbook context and the observed formula without ambiguity."""

    if maximum_length < 4:
        raise ValueError("formula denoising source length is too small")
    if not context_ids or not corrupted_formula_ids:
        raise ValueError("formula denoising source sequences must be non-empty")
    source = tuple(context_ids) + tuple(corrupted_formula_ids)
    if len(source) > maximum_length:
        raise ValueError("formula denoising source exceeds the fixed model limit")
    segments = (CONTEXT_SEGMENT,) * len(context_ids) + (
        CORRUPTED_FORMULA_SEGMENT,
    ) * len(corrupted_formula_ids)
    return source, segments


class FormulaDenoiser(nn.Module):
    """Generate a canonical formula token sequence from context and corruption."""

    def __init__(
        self,
        vocabulary_size: int,
        *,
        allowed_output_ids: Sequence[int] | None = None,
        padding_id: int = 0,
        maximum_source_length: int = 480,
        maximum_target_length: int = 96,
        model_size: int = 192,
        attention_heads: int = 8,
        encoder_layers: int = 3,
        decoder_layers: int = 3,
        feedforward_size: int = 768,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if vocabulary_size < 4:
            raise ValueError("formula denoiser vocabulary is too small")
        if model_size % attention_heads:
            raise ValueError("formula denoiser heads must divide the model size")
        if maximum_source_length < 1 or maximum_target_length < 2:
            raise ValueError("formula denoiser sequence limits are invalid")
        self.padding_id = padding_id
        self.maximum_source_length = maximum_source_length
        self.maximum_target_length = maximum_target_length
        self.model_size = model_size
        self.token_embedding = nn.Embedding(
            vocabulary_size, model_size, padding_idx=padding_id
        )
        self.segment_embedding = nn.Embedding(2, model_size)
        self.source_position = nn.Embedding(maximum_source_length, model_size)
        self.target_position = nn.Embedding(maximum_target_length, model_size)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=model_size,
            nhead=attention_heads,
            dim_feedforward=feedforward_size,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        decoder_layer = nn.TransformerDecoderLayer(
            d_model=model_size,
            nhead=attention_heads,
            dim_feedforward=feedforward_size,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(
            encoder_layer,
            encoder_layers,
            norm=nn.LayerNorm(model_size),
            enable_nested_tensor=False,
        )
        self.decoder = nn.TransformerDecoder(
            decoder_layer, decoder_layers, norm=nn.LayerNorm(model_size)
        )
        self.source_norm = nn.LayerNorm(model_size)
        self.target_norm = nn.LayerNorm(model_size)
        self.output_bias = nn.Parameter(torch.zeros(vocabulary_size))
        self.copy_gate = nn.Linear(model_size, 1)
        allowed = torch.ones(vocabulary_size, dtype=torch.bool)
        if allowed_output_ids is not None:
            allowed.zero_()
            for token_id in allowed_output_ids:
                if token_id < 0 or token_id >= vocabulary_size:
                    raise ValueError("formula denoiser output token is outside the vocabulary")
                allowed[token_id] = True
            if not bool(allowed.any()):
                raise ValueError("formula denoiser has no allowed output tokens")
        self.register_buffer("allowed_output", allowed, persistent=True)
        self._reset_parameters()

    def _reset_parameters(self) -> None:
        nn.init.normal_(self.token_embedding.weight, mean=0.0, std=0.02)
        if self.token_embedding.padding_idx is not None:
            with torch.no_grad():
                self.token_embedding.weight[self.token_embedding.padding_idx].zero_()
        nn.init.normal_(self.segment_embedding.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.source_position.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.target_position.weight, mean=0.0, std=0.02)
        nn.init.zeros_(self.output_bias)
        nn.init.zeros_(self.copy_gate.weight)
        nn.init.constant_(self.copy_gate.bias, 4.0)

    def aligned_copy_ids(
        self,
        source_ids: Tensor,
        source_segments: Tensor,
        target_length: int,
    ) -> Tensor:
        """Align each predicted position with the observed formula token to preserve."""

        if source_ids.shape != source_segments.shape or target_length < 1:
            raise ValueError("formula denoiser copy alignment shape differs")
        result = torch.full(
            (source_ids.size(0), target_length),
            self.padding_id,
            dtype=torch.long,
            device=source_ids.device,
        )
        for row in range(source_ids.size(0)):
            formula = source_ids[row][
                source_segments[row].eq(CORRUPTED_FORMULA_SEGMENT)
                & source_ids[row].ne(self.padding_id)
            ]
            # Decoder position zero predicts the token after <START>.
            available = min(target_length, max(0, formula.numel() - 1))
            if available:
                result[row, :available] = formula[1 : available + 1]
        return result

    def encode(self, source_ids: Tensor, source_segments: Tensor) -> tuple[Tensor, Tensor]:
        if (
            source_ids.ndim != 2
            or source_segments.shape != source_ids.shape
            or source_ids.size(1) > self.maximum_source_length
        ):
            raise ValueError("formula denoiser source batch shape differs")
        if bool(((source_segments < 0) | (source_segments > 1)).any()):
            raise ValueError("formula denoiser source segment is invalid")
        positions = torch.arange(source_ids.size(1), device=source_ids.device)
        values = (
            self.token_embedding(source_ids) * math.sqrt(self.model_size)
            + self.segment_embedding(source_segments)
            + self.source_position(positions)[None, :, :]
        )
        padding_mask = source_ids.eq(self.padding_id)
        memory = self.encoder(
            self.source_norm(values), src_key_padding_mask=padding_mask
        )
        return memory, padding_mask

    def decode_logits(
        self,
        memory: Tensor,
        source_padding_mask: Tensor,
        target_input_ids: Tensor,
        copy_token_ids: Tensor | None = None,
    ) -> Tensor:
        if (
            target_input_ids.ndim != 2
            or target_input_ids.size(0) != memory.size(0)
            or target_input_ids.size(1) > self.maximum_target_length
            or source_padding_mask.shape != memory.shape[:2]
        ):
            raise ValueError("formula denoiser target batch shape differs")
        positions = torch.arange(target_input_ids.size(1), device=target_input_ids.device)
        values = (
            self.token_embedding(target_input_ids) * math.sqrt(self.model_size)
            + self.target_position(positions)[None, :, :]
        )
        length = target_input_ids.size(1)
        causal_mask = torch.triu(
            torch.ones((length, length), dtype=torch.bool, device=target_input_ids.device),
            diagonal=1,
        )
        decoded = self.decoder(
            self.target_norm(values),
            memory,
            tgt_mask=causal_mask,
            tgt_key_padding_mask=target_input_ids.eq(self.padding_id),
            memory_key_padding_mask=source_padding_mask,
        )
        logits = decoded @ self.token_embedding.weight.transpose(0, 1) + self.output_bias
        if copy_token_ids is not None:
            if copy_token_ids.shape != target_input_ids.shape:
                raise ValueError("formula denoiser copy token batch shape differs")
            copy_boost = F.softplus(self.copy_gate(decoded)).squeeze(-1)
            copy_boost = copy_boost * copy_token_ids.ne(self.padding_id)
            logits.scatter_add_(2, copy_token_ids[:, :, None], copy_boost[:, :, None])
        return logits.masked_fill(~self.allowed_output[None, None, :], float("-inf"))

    def forward(
        self,
        source_ids: Tensor,
        source_segments: Tensor,
        target_input_ids: Tensor,
    ) -> Tensor:
        memory, source_padding_mask = self.encode(source_ids, source_segments)
        copy_token_ids = self.aligned_copy_ids(
            source_ids, source_segments, target_input_ids.size(1)
        )
        return self.decode_logits(
            memory, source_padding_mask, target_input_ids, copy_token_ids
        )

    @torch.no_grad()
    def beam_generate(
        self,
        source_ids: Tensor,
        source_segments: Tensor,
        *,
        start_id: int,
        end_id: int,
        beam_size: int = 5,
        length_penalty: float = 0.6,
    ) -> tuple[Tensor, Tensor]:
        if beam_size < 1:
            raise ValueError("formula denoiser beam size must be positive")
        if length_penalty < 0:
            raise ValueError("formula denoiser length penalty cannot be negative")
        self.eval()
        memory, source_padding_mask = self.encode(source_ids, source_segments)
        batch = source_ids.size(0)
        vocabulary_size = self.token_embedding.num_embeddings
        sequences = torch.full(
            (batch, beam_size, 1), start_id, dtype=torch.long, device=source_ids.device
        )
        scores = torch.full(
            (batch, beam_size), float("-inf"), device=source_ids.device
        )
        scores[:, 0] = 0.0
        finished = torch.zeros(
            (batch, beam_size), dtype=torch.bool, device=source_ids.device
        )
        expanded_memory = memory[:, None, :, :].expand(
            batch, beam_size, *memory.shape[1:]
        ).reshape(batch * beam_size, *memory.shape[1:])
        expanded_padding = source_padding_mask[:, None, :].expand(
            batch, beam_size, source_padding_mask.size(1)
        ).reshape(batch * beam_size, source_padding_mask.size(1))
        expanded_source = source_ids[:, None, :].expand(
            batch, beam_size, source_ids.size(1)
        ).reshape(batch * beam_size, source_ids.size(1))
        expanded_segments = source_segments[:, None, :].expand(
            batch, beam_size, source_segments.size(1)
        ).reshape(batch * beam_size, source_segments.size(1))

        for _ in range(self.maximum_target_length - 1):
            copy_token_ids = self.aligned_copy_ids(
                expanded_source, expanded_segments, sequences.size(2)
            )
            logits = self.decode_logits(
                expanded_memory,
                expanded_padding,
                sequences.reshape(batch * beam_size, -1),
                copy_token_ids,
            )[:, -1, :]
            log_probabilities = torch.log_softmax(logits.float(), dim=-1).reshape(
                batch, beam_size, vocabulary_size
            )
            if bool(finished.any()):
                log_probabilities = log_probabilities.masked_fill(
                    finished[:, :, None], float("-inf")
                )
                end_scores = log_probabilities[:, :, end_id]
                log_probabilities[:, :, end_id] = torch.where(
                    finished, torch.zeros_like(end_scores), end_scores
                )
            candidates = scores[:, :, None] + log_probabilities
            next_scores, flat_positions = candidates.reshape(batch, -1).topk(
                beam_size, dim=-1
            )
            parents = torch.div(flat_positions, vocabulary_size, rounding_mode="floor")
            tokens = flat_positions.remainder(vocabulary_size)
            sequences = torch.cat(
                (
                    sequences.gather(
                        1, parents[:, :, None].expand(-1, -1, sequences.size(2))
                    ),
                    tokens[:, :, None],
                ),
                dim=2,
            )
            finished = finished.gather(1, parents) | tokens.eq(end_id)
            scores = next_scores
            if bool(finished.all()):
                break

        lengths = sequences.ne(end_id).sum(dim=2).clamp_min(1)
        normalized = scores / lengths.float().pow(length_penalty)
        order = normalized.argsort(dim=1, descending=True)
        sequences = sequences.gather(
            1, order[:, :, None].expand(-1, -1, sequences.size(2))
        )
        return sequences, scores.gather(1, order)


__all__ = [
    "CONTEXT_SEGMENT",
    "CORRUPTED_FORMULA_SEGMENT",
    "FormulaDenoiser",
    "denoising_source",
]
