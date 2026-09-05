"""Neural compatibility head over frozen table context and formula roles."""

from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .fcrl_torch import FCRLRuntime, FCRLTensorBatch, FCRLTorchError


class FormulaRoleEncoder(nn.Module):
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
        if vocabulary_size < 4:
            raise ValueError("formula vocabulary is too small")
        self.padding_id = padding_id
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
            raise ValueError("formula token batch shape differs")
        packed = nn.utils.rnn.pack_padded_sequence(
            self.embedding(token_ids),
            lengths.detach().cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        _, hidden = self.encoder(packed)
        representation = torch.cat((hidden[-2], hidden[-1]), dim=-1)
        return F.normalize(self.projection(representation), dim=-1)


class SemanticCompatibilityHead(nn.Module):
    def __init__(
        self,
        vocabulary_size: int,
        *,
        context_size: int = 768,
        output_size: int = 256,
        temperature: float = 0.07,
    ) -> None:
        super().__init__()
        if temperature <= 0.0:
            raise ValueError("temperature must be positive")
        self.context_projection = nn.Sequential(
            nn.LayerNorm(context_size),
            nn.Linear(context_size, output_size),
            nn.GELU(),
            nn.Linear(output_size, output_size),
        )
        self.formula_encoder = FormulaRoleEncoder(
            vocabulary_size,
            output_size=output_size,
        )
        self.temperature = temperature

    def encode_context(self, states: Tensor) -> Tensor:
        return F.normalize(self.context_projection(states), dim=-1)

    def encode_formulas(self, token_ids: Tensor, lengths: Tensor) -> Tensor:
        return self.formula_encoder(token_ids, lengths)

    def logits(self, context_states: Tensor, token_ids: Tensor, lengths: Tensor) -> Tensor:
        context = self.encode_context(context_states)
        formulas = self.encode_formulas(token_ids, lengths)
        return context @ formulas.transpose(0, 1) / self.temperature

    def contrastive_loss(
        self,
        context_states: Tensor,
        token_ids: Tensor,
        lengths: Tensor,
        role_ids: Tensor,
    ) -> Tensor:
        logits = self.logits(context_states, token_ids, lengths)
        if role_ids.ndim != 1 or role_ids.size(0) != logits.size(0):
            raise ValueError("role identity batch shape differs")
        positives = role_ids[:, None] == role_ids[None, :]
        log_probabilities = F.log_softmax(logits, dim=1)
        positive_counts = positives.sum(dim=1)
        if bool((positive_counts == 0).any()):
            raise ValueError("contrastive row has no positive formula")
        return -(
            (log_probabilities * positives).sum(dim=1) / positive_counts
        ).mean()

    def candidate_logits(
        self,
        context_states: Tensor,
        token_ids: Tensor,
        lengths: Tensor,
        candidate_mask: Tensor,
    ) -> Tensor:
        if (
            token_ids.ndim != 3
            or lengths.ndim != 2
            or candidate_mask.ndim != 2
            or token_ids.shape[:2] != lengths.shape
            or lengths.shape != candidate_mask.shape
            or context_states.size(0) != token_ids.size(0)
            or not bool(candidate_mask.any(dim=1).all())
        ):
            raise ValueError("formula candidate batch shape differs")
        batch_size, candidate_count, sequence_length = token_ids.shape
        formulas = self.encode_formulas(
            token_ids.reshape(batch_size * candidate_count, sequence_length),
            lengths.reshape(batch_size * candidate_count),
        ).reshape(batch_size, candidate_count, -1)
        contexts = self.encode_context(context_states)
        logits = torch.einsum("bd,bcd->bc", contexts, formulas) / self.temperature
        return logits.masked_fill(~candidate_mask, float("-inf"))

    def candidate_loss(
        self,
        context_states: Tensor,
        token_ids: Tensor,
        lengths: Tensor,
        candidate_mask: Tensor,
        gold_indices: Tensor,
    ) -> Tensor:
        logits = self.candidate_logits(
            context_states,
            token_ids,
            lengths,
            candidate_mask,
        )
        if gold_indices.ndim != 1 or gold_indices.size(0) != logits.size(0):
            raise ValueError("formula candidate labels differ")
        rows = torch.arange(logits.size(0), device=logits.device)
        if (
            bool((gold_indices < 0).any())
            or bool((gold_indices >= logits.size(1)).any())
            or not bool(candidate_mask[rows, gold_indices].all())
        ):
            raise ValueError("formula candidate gold index is invalid")
        eligible = candidate_mask.sum(dim=1) > 1
        if not bool(eligible.any()):
            return logits[eligible].sum()
        return F.cross_entropy(logits[eligible], gold_indices[eligible])


@torch.no_grad()
def frozen_context_states(runtime: FCRLRuntime, batch: FCRLTensorBatch) -> Tensor:
    runtime.model.eval()
    encoded = runtime.model.encode(batch)
    selected = encoded[batch.formula_label == 1]
    batch_size = encoded.size(0)
    if selected.numel() != batch_size * 2 * runtime.model.hidden_size:
        raise FCRLTorchError("formula_marker_count_changed")
    return selected.view(batch_size, 2, runtime.model.hidden_size)[:, 0, :].detach()


__all__ = [
    "FormulaRoleEncoder",
    "SemanticCompatibilityHead",
    "frozen_context_states",
]
