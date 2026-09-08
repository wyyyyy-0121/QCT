"""Small dual encoder used by the formula-compatibility development pilot."""

from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.nn import functional as F


class SequenceEncoder(nn.Module):
    def __init__(
        self,
        vocabulary_size: int,
        *,
        embedding_size: int = 128,
        hidden_size: int = 192,
        output_size: int = 256,
        padding_id: int = 0,
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocabulary_size, embedding_size, padding_idx=padding_id)
        self.encoder = nn.GRU(
            embedding_size,
            hidden_size,
            batch_first=True,
            bidirectional=True,
        )
        self.projection = nn.Linear(hidden_size * 2, output_size)

    def forward(self, token_ids: Tensor, lengths: Tensor) -> Tensor:
        if token_ids.ndim != 2 or lengths.ndim != 1 or token_ids.size(0) != lengths.size(0):
            raise ValueError("compatibility sequence batch shape differs")
        packed = nn.utils.rnn.pack_padded_sequence(
            self.embedding(token_ids),
            lengths.detach().cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        _, hidden = self.encoder(packed)
        representation = torch.cat((hidden[-2], hidden[-1]), dim=-1)
        return F.normalize(self.projection(representation), dim=-1)


class FormulaCompatibilityPilot(nn.Module):
    def __init__(
        self,
        vocabulary_size: int,
        *,
        temperature: float = 0.10,
    ) -> None:
        super().__init__()
        if temperature <= 0:
            raise ValueError("compatibility temperature must be positive")
        self.context_encoder = SequenceEncoder(vocabulary_size)
        self.formula_encoder = SequenceEncoder(vocabulary_size)
        self.temperature = temperature

    def candidate_logits(
        self,
        context_ids: Tensor,
        context_lengths: Tensor,
        formula_ids: Tensor,
        formula_lengths: Tensor,
        candidate_mask: Tensor,
        *,
        formula_only: bool = False,
    ) -> Tensor:
        if (
            formula_ids.ndim != 3
            or formula_lengths.ndim != 2
            or candidate_mask.ndim != 2
            or formula_ids.shape[:2] != formula_lengths.shape
            or formula_lengths.shape != candidate_mask.shape
            or context_ids.size(0) != formula_ids.size(0)
            or not bool(candidate_mask.any(dim=1).all())
        ):
            raise ValueError("compatibility candidate batch shape differs")
        batch, candidates, width = formula_ids.shape
        contexts = self.context_encoder(context_ids, context_lengths)
        if formula_only:
            contexts = torch.ones_like(contexts)
            contexts = F.normalize(contexts, dim=-1)
        formulas = self.formula_encoder(
            formula_ids.reshape(batch * candidates, width),
            formula_lengths.reshape(batch * candidates),
        ).reshape(batch, candidates, -1)
        logits = torch.einsum("bd,bcd->bc", contexts, formulas) / self.temperature
        return logits.masked_fill(~candidate_mask, float("-inf"))


__all__ = ["FormulaCompatibilityPilot", "SequenceEncoder"]
