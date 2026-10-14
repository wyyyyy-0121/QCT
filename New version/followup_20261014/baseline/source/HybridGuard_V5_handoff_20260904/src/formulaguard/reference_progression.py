"""Direction-conditioned reference progression for masked formula contexts."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from .a1 import parse_address
from .pcrc import DIRECTIONAL_PEERS, PEER_CONFIG, formula_tokens
from .workbook import CellKey, WorkbookModel


@dataclass(frozen=True)
class ProgressionPeer:
    axis: str
    delta: int
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class FormulaOffsets:
    skeleton: tuple[str, ...]
    values: tuple[int, ...]


@dataclass(frozen=True)
class ProgressionDecision:
    candidate_index: int | None
    axes: tuple[str, ...]
    peer_count: int
    slopes: tuple[str, ...]
    peer_error: float
    candidate_error: float
    reason: str


@dataclass(frozen=True)
class ProgressionResidual:
    supported: bool
    residual: float
    axes: tuple[str, ...]
    peer_count: int
    slopes: tuple[str, ...]
    expected_values: tuple[int, ...]
    reason: str


def directional_progression_peers(
    model: WorkbookModel,
    target: CellKey,
) -> tuple[ProgressionPeer, ...]:
    """Return bounded same-axis peers without reading the target formula."""
    if target not in model.formulas:
        raise ValueError("reference progression target is not a formula")
    sheet, address_text = target
    address = parse_address(address_text)
    directions: dict[str, list[tuple[int, CellKey]]] = {
        "up": [], "down": [], "left": [], "right": [],
    }
    for peer in model.formula_cells:
        if peer == target or peer[0] != sheet or not model.is_visible(peer):
            continue
        other = parse_address(peer[1])
        drow, dcol = other.row - address.row, other.col - address.col
        if dcol == 0 and 0 < abs(drow) <= PEER_CONFIG.axis_radius:
            directions["up" if drow < 0 else "down"].append((drow, peer))
        elif drow == 0 and 0 < abs(dcol) <= PEER_CONFIG.axis_radius:
            directions["left" if dcol < 0 else "right"].append((dcol, peer))

    selected: list[ProgressionPeer] = []
    for direction in ("up", "down", "left", "right"):
        rows = sorted(
            directions[direction],
            key=lambda item: (abs(item[0]), item[1][0], item[1][1]),
        )[:DIRECTIONAL_PEERS]
        axis = "row" if direction in {"up", "down"} else "column"
        for delta, peer in rows:
            try:
                tokens = formula_tokens(model.formulas[peer], peer[1], peer[0])
            except (TypeError, ValueError):
                continue
            selected.append(ProgressionPeer(axis=axis, delta=delta, tokens=tokens))
    return tuple(selected)


def formula_offsets(tokens: Sequence[str]) -> FormulaOffsets:
    """Replace reference coordinates with slots and retain their signed values."""
    skeleton: list[str] = []
    values: list[int] = []
    index = 0
    while index < len(tokens):
        token = str(tokens[index])
        if token.startswith(("ROW_", "COL_")) and index + 2 < len(tokens):
            offset = str(tokens[index + 1])
            if offset in {"OFFSET_NEG", "OFFSET_ZERO", "OFFSET_POS"}:
                end = index + 2
                digits: list[str] = []
                while end < len(tokens) and str(tokens[end]).startswith("DIGIT_"):
                    digits.append(str(tokens[end]).removeprefix("DIGIT_"))
                    end += 1
                if digits and all(value.isdigit() and len(value) == 1 for value in digits):
                    magnitude = int("".join(digits))
                    sign = -1 if offset == "OFFSET_NEG" else 1 if offset == "OFFSET_POS" else 0
                    values.append(sign * magnitude)
                    skeleton.extend((token, "OFFSET_VALUE"))
                    index = end
                    continue
        skeleton.append(token)
        index += 1
    return FormulaOffsets(tuple(skeleton), tuple(values))


def _fraction_median(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise ValueError("reference progression median requires values")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _fit_offsets(
    rows: Sequence[tuple[int, tuple[int, ...]]],
) -> tuple[tuple[Fraction, ...], tuple[Fraction, ...], Fraction]:
    width = len(rows[0][1])
    if width == 0 or any(len(values) != width for _, values in rows):
        raise ValueError("reference progression offset width differs")
    slopes: list[Fraction] = []
    intercepts: list[Fraction] = []
    residuals: list[Fraction] = []
    for column in range(width):
        pair_slopes = [
            Fraction(right_values[column] - left_values[column], right_x - left_x)
            for left_index, (left_x, left_values) in enumerate(rows)
            for right_x, right_values in rows[left_index + 1 :]
            if right_x != left_x
        ]
        slope = _fraction_median(pair_slopes)
        intercept = _fraction_median([
            Fraction(values[column]) - slope * x for x, values in rows
        ])
        slopes.append(slope)
        intercepts.append(intercept)
        residuals.extend(
            abs(Fraction(values[column]) - (intercept + slope * x))
            for x, values in rows
        )
    return tuple(slopes), tuple(intercepts), sum(residuals, Fraction()) / len(residuals)


def _exact_progression_fits(
    peers: Sequence[ProgressionPeer],
    minimum_peers: int,
) -> list[
    tuple[
        str,
        tuple[str, ...],
        int,
        tuple[Fraction, ...],
        tuple[Fraction, ...],
    ]
]:
    grouped: dict[tuple[str, tuple[str, ...]], list[tuple[int, tuple[int, ...]]]] = {}
    for peer in peers:
        parsed = formula_offsets(peer.tokens)
        if not parsed.values:
            continue
        grouped.setdefault((peer.axis, parsed.skeleton), []).append(
            (peer.delta, parsed.values)
        )
    fits = []
    for (axis, skeleton), rows in grouped.items():
        if len(rows) < minimum_peers or len({x for x, _ in rows}) < minimum_peers:
            continue
        slopes, intercepts, peer_error = _fit_offsets(rows)
        if peer_error == 0 and any(slope != 0 for slope in slopes):
            fits.append((axis, skeleton, len(rows), slopes, intercepts))
    return fits


def progression_decision(
    candidates: Sequence[Sequence[str]],
    peers: Sequence[ProgressionPeer],
    *,
    minimum_peers: int = 3,
) -> ProgressionDecision:
    """Return a candidate only for an exact, non-constant peer progression."""
    if minimum_peers < 3:
        raise ValueError("reference progression requires at least three peers")
    parsed_candidates = [formula_offsets(candidate) for candidate in candidates]
    predictions: list[
        tuple[int, str, int, tuple[Fraction, ...], Fraction]
    ] = []
    for axis, skeleton, peer_count, slopes, intercepts in _exact_progression_fits(
        peers, minimum_peers
    ):
        errors = []
        for index, candidate in enumerate(parsed_candidates):
            if candidate.skeleton != skeleton or len(candidate.values) != len(intercepts):
                continue
            error = sum(
                abs(Fraction(value) - intercept)
                for value, intercept in zip(candidate.values, intercepts, strict=True)
            ) / len(intercepts)
            errors.append((error, index))
        if not errors:
            continue
        best_error = min(error for error, _ in errors)
        winners = [index for error, index in errors if error == best_error]
        if best_error == 0 and len(winners) == 1:
            predictions.append(
                (winners[0], axis, peer_count, slopes, best_error)
            )

    candidate_indexes = {row[0] for row in predictions}
    if len(candidate_indexes) != 1:
        return ProgressionDecision(
            candidate_index=None,
            axes=tuple(sorted({row[1] for row in predictions})),
            peer_count=max((row[2] for row in predictions), default=0),
            slopes=(),
            peer_error=0.0,
            candidate_error=0.0,
            reason="no_unique_exact_progression",
        )
    selected = next(iter(candidate_indexes))
    supporting = [row for row in predictions if row[0] == selected]
    slopes = tuple(
        str(value) for row in supporting for value in row[3] if value != 0
    )
    return ProgressionDecision(
        candidate_index=selected,
        axes=tuple(sorted({row[1] for row in supporting})),
        peer_count=max(row[2] for row in supporting),
        slopes=slopes,
        peer_error=0.0,
        candidate_error=float(min(row[4] for row in supporting)),
        reason="unique_exact_nonconstant_progression",
    )


def progression_residual(
    observed: Sequence[str],
    peers: Sequence[ProgressionPeer],
    *,
    minimum_peers: int = 3,
) -> ProgressionResidual:
    """Measure an observed formula against a unique peer-only expectation."""
    if minimum_peers < 3:
        raise ValueError("reference progression requires at least three peers")
    parsed = formula_offsets(observed)
    matching = [
        (axis, peer_count, slopes, intercepts)
        for axis, skeleton, peer_count, slopes, intercepts in _exact_progression_fits(
            peers, minimum_peers
        )
        if skeleton == parsed.skeleton
        and len(intercepts) == len(parsed.values)
        and all(value.denominator == 1 for value in intercepts)
    ]
    expectations = {
        tuple(int(value) for value in intercepts)
        for _, _, _, intercepts in matching
    }
    if len(expectations) != 1:
        return ProgressionResidual(
            supported=False,
            residual=0.0,
            axes=tuple(sorted({row[0] for row in matching})),
            peer_count=max((row[1] for row in matching), default=0),
            slopes=(),
            expected_values=(),
            reason="no_unique_integer_expectation",
        )
    expected = next(iter(expectations))
    residual = sum(
        abs(observed_value - expected_value)
        for observed_value, expected_value in zip(parsed.values, expected, strict=True)
    ) / len(expected)
    supporting = [
        row
        for row in matching
        if tuple(int(value) for value in row[3]) == expected
    ]
    return ProgressionResidual(
        supported=True,
        residual=residual,
        axes=tuple(sorted({row[0] for row in supporting})),
        peer_count=max(row[1] for row in supporting),
        slopes=tuple(
            str(value) for row in supporting for value in row[2] if value != 0
        ),
        expected_values=expected,
        reason="progression_anomaly" if residual > 0 else "progression_match",
    )


__all__ = [
    "FormulaOffsets",
    "ProgressionDecision",
    "ProgressionPeer",
    "ProgressionResidual",
    "directional_progression_peers",
    "formula_offsets",
    "progression_decision",
    "progression_residual",
]
