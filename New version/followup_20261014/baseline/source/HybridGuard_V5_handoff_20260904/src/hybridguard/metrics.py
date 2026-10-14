"""Small, dependency-free ranking metrics used by the experiment."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def average_precision(ranked_cells: Sequence[str], truth: set[str]) -> float:
    if not truth:
        return 0.0
    hits = 0
    total = 0.0
    for rank, cell in enumerate(ranked_cells, 1):
        if cell in truth:
            hits += 1
            total += hits / rank
    return total / len(truth)


def top_k_stats(ranked_cells: Sequence[str], truth: set[str], k: int) -> dict[str, float | int]:
    selected = ranked_cells[: min(k, len(ranked_cells))]
    hits = sum(cell in truth for cell in selected)
    return {
        "k": k,
        "hits": hits,
        "precision": hits / max(1, len(selected)),
        "recall": hits / max(1, len(truth)),
    }


def rank_lookup(ranked_cells: Iterable[str]) -> dict[str, int]:
    return {cell: rank for rank, cell in enumerate(ranked_cells, 1)}

