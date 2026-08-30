"""Deterministic XLSX-to-ForTaP adapter for the preregistered FCRL line."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .a1 import num_to_col, parse_address
from .formula import (
    Binary,
    FormulaSyntaxError,
    Func,
    Node,
    Number,
    Range,
    Ref,
    Unary,
    normalized_formula,
    parse_formula,
    translate_formula,
)
from .workbook import CellKey, WorkbookModel


FCRL_PROTOCOL = "formulaguard_fcrl_adapter_v1"
MAX_TABLE_DIMENSION = 256
CONTEXT_DIMENSION = 32
MAX_INPUT_TOKENS = 512
MAX_CELL_TOKENS = 8
MAX_FORMULA_TOKENS = 64

FP_OPERATORS = {
    "+", "-", "*", "/", "^", "&", "=", "<>", ">", ">=", "<", "<=",
}
FP_FUNCTIONS = {
    "SUM", "IF", "ROUND", "VLOOKUP", "AVERAGE", "OFFSET", "ABS", "EOMONTH",
    "LN", "MAX", "ISERROR", "INDEX", "MATCH", "MONTH", "SQRT", "AND", "MIN",
    "EDATE", "YEAR", "SUBTOTAL",
}


class FCRLAdapterError(ValueError):
    """A stable, aggregate-safe rejection from the frozen adapter."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FormulaPrefix:
    tokens: tuple[str, ...]
    token_types: tuple[str, ...]
    reference_addresses: tuple[str, ...]


@dataclass(frozen=True)
class ComponentBounds:
    min_row: int
    max_row: int
    min_col: int
    max_col: int

    def contains(self, row: int, col: int) -> bool:
        return self.min_row <= row <= self.max_row and self.min_col <= col <= self.max_col


@dataclass(frozen=True)
class FCRLTableInput:
    """Transient adapter output. Raw members must never be serialized or logged."""

    target: CellKey
    table_range: str
    string_matrix: tuple[tuple[str, ...], ...]
    format_matrix: tuple[tuple[tuple[float, ...], ...], ...]
    top_positions: tuple[tuple[int, ...], ...]
    left_positions: tuple[tuple[int, ...], ...]
    header_rows: int
    header_columns: int
    formula_prefix: FormulaPrefix
    target_row: int
    target_column: int

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.string_matrix), len(self.string_matrix[0])

    def encoder_material_hash(self) -> str:
        """Hash context material without exposing transient workbook content."""
        material = {
            "protocol": FCRL_PROTOCOL,
            "table_range": self.table_range,
            "strings": self.string_matrix,
            "formats": self.format_matrix,
            "top": self.top_positions,
            "left": self.left_positions,
            "headers": [self.header_rows, self.header_columns],
            "target": [self.target_row, self.target_column],
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PeerCandidate:
    formula: str
    normalized: str
    block_ids: tuple[str, ...]
    nearest_distance: int


def formula_prefix_key(prefix: FormulaPrefix) -> str:
    """Return the exact public ForTaP prediction key for a parsed formula."""
    normalized_tokens = [
        "C-NUM" if token_type == "NUMBER" else token.upper()
        for token, token_type in zip(prefix.tokens, prefix.token_types, strict=True)
    ]
    return " ".join(normalized_tokens)


def formula_prediction_key(formula: str) -> str:
    return formula_prefix_key(formula_to_prefix(formula))


def _plain_ref(ref: Ref) -> str:
    if ref.sheet is not None:
        raise FCRLAdapterError("cross_sheet_reference")
    return f"{num_to_col(ref.address.col)}{ref.address.row}"


def formula_to_prefix(formula: str) -> FormulaPrefix:
    """Convert the QCT AST subset to the published ForTaP prefix contract."""
    try:
        root = parse_formula(formula)
    except (FormulaSyntaxError, ValueError) as exc:
        raise FCRLAdapterError("unsupported_formula_syntax") from exc

    tokens: list[str] = []
    types: list[str] = []
    references: list[str] = []

    def emit(node: Node) -> None:
        if isinstance(node, Number):
            value = str(int(node.value)) if node.value.is_integer() else f"{node.value:g}"
            tokens.append(value)
            types.append("NUMBER")
            return
        if isinstance(node, Ref):
            address = _plain_ref(node)
            tokens.append(address)
            types.append("CELL")
            references.append(address)
            return
        if isinstance(node, Range):
            start = _plain_ref(node.start)
            end = _plain_ref(node.end)
            tokens.extend((start, ":", end))
            types.extend(("CELL", "SPECIAL", "CELL"))
            references.extend((start, end))
            return
        if isinstance(node, Unary):
            if node.op not in FP_OPERATORS:
                raise FCRLAdapterError("unsupported_formula_operator")
            tokens.append(node.op)
            types.append("OP")
            emit(node.value)  # type: ignore[arg-type]
            return
        if isinstance(node, Binary):
            if node.op not in FP_OPERATORS:
                raise FCRLAdapterError("unsupported_formula_operator")
            tokens.append(node.op)
            types.append("OP")
            emit(node.left)  # type: ignore[arg-type]
            emit(node.right)  # type: ignore[arg-type]
            return
        if isinstance(node, Func):
            name = node.name.upper()
            if name not in FP_FUNCTIONS:
                raise FCRLAdapterError("unsupported_formula_function")
            tokens.append(name)
            types.append("FUNC")
            for argument in node.args:
                emit(argument)  # type: ignore[arg-type]
            return
        raise FCRLAdapterError("unsupported_formula_node")

    emit(root)
    if not references:
        raise FCRLAdapterError("formula_without_reference")
    if len(tokens) + 2 > MAX_FORMULA_TOKENS:
        raise FCRLAdapterError("formula_token_limit")
    return FormulaPrefix(tuple(tokens), tuple(types), tuple(references))


def _visible_occupied(model: WorkbookModel, sheet: str) -> set[tuple[int, int]]:
    occupied: set[tuple[int, int]] = set()
    for key in set(model.cells) | set(model.formulas):
        if key[0] != sheet or not model.is_visible(key):
            continue
        address = parse_address(key[1])
        occupied.add((address.row, address.col))
    return occupied


def component_bounds(model: WorkbookModel, target: CellKey) -> ComponentBounds:
    sheet, address_text = target
    address = parse_address(address_text)
    occupied = _visible_occupied(model, sheet)
    if (address.row, address.col) not in occupied or not model.is_visible(target):
        raise FCRLAdapterError("target_not_visible")
    occupied_rows = {row for row, _ in occupied}
    occupied_columns = {col for _, col in occupied}

    min_row = max_row = address.row
    min_col = max_col = address.col
    while min_row - 1 in occupied_rows:
        min_row -= 1
    while max_row + 1 in occupied_rows:
        max_row += 1
    while min_col - 1 in occupied_columns:
        min_col -= 1
    while max_col + 1 in occupied_columns:
        max_col += 1
    return ComponentBounds(min_row, max_row, min_col, max_col)


def _expand_dimension(
    lower: int,
    upper: int,
    component_lower: int,
    component_upper: int,
    desired: int = CONTEXT_DIMENSION,
) -> tuple[int, int]:
    missing = max(0, desired - (upper - lower + 1))
    before_goal = (missing + 1) // 2
    before = min(before_goal, lower - component_lower)
    after = min(missing - before, component_upper - upper)
    remaining = missing - before - after
    if remaining:
        before_more = min(remaining, lower - component_lower - before)
        before += before_more
        remaining -= before_more
    if remaining:
        after += min(remaining, component_upper - upper - after)
    return lower - before, upper + after


def _crop_bounds(
    target_address: str,
    prefix: FormulaPrefix,
    component: ComponentBounds,
) -> ComponentBounds:
    target = parse_address(target_address)
    refs = [parse_address(address) for address in prefix.reference_addresses]
    for ref in refs:
        if not component.contains(ref.row, ref.col):
            raise FCRLAdapterError("reference_outside_component")
    rows = [target.row, *(ref.row for ref in refs)]
    columns = [target.col, *(ref.col for ref in refs)]
    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(columns), max(columns)
    if max_row - min_row + 1 > MAX_TABLE_DIMENSION or max_col - min_col + 1 > MAX_TABLE_DIMENSION:
        raise FCRLAdapterError("mandatory_crop_limit")
    min_row, max_row = _expand_dimension(
        min_row, max_row, component.min_row, component.max_row
    )
    min_col, max_col = _expand_dimension(
        min_col, max_col, component.min_col, component.max_col
    )
    return ComponentBounds(min_row, max_row, min_col, max_col)


def _cell_string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".15g") if math.isfinite(value) else ""
    return str(value)


def _is_date_format(number_format: str) -> bool:
    compact = re.sub(r'"[^"]*"|\\.|\[[^]]*\]', "", number_format.lower())
    return bool(re.search(r"[ymdhis]", compact))


def _format_vector(model: WorkbookModel, key: CellKey) -> tuple[float, ...]:
    return (
        1.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        float(_is_date_format(model.number_format(key))),
        float(key in model.formulas),
        0.0,
        1.0,
        1.0,
    )


def build_table_input(model: WorkbookModel, target: CellKey) -> FCRLTableInput:
    if target not in model.formulas:
        raise FCRLAdapterError("target_not_formula")
    prefix = formula_to_prefix(model.formulas[target])
    component = component_bounds(model, target)
    crop = _crop_bounds(target[1], prefix, component)

    strings: list[tuple[str, ...]] = []
    formats: list[tuple[tuple[float, ...], ...]] = []
    for row in range(crop.min_row, crop.max_row + 1):
        string_row: list[str] = []
        format_row: list[tuple[float, ...]] = []
        for col in range(crop.min_col, crop.max_col + 1):
            key = (target[0], f"{num_to_col(col)}{row}")
            string_row.append("" if key == target else _cell_string(model.cells.get(key)))
            format_row.append(_format_vector(model, key))
        strings.append(tuple(string_row))
        formats.append(tuple(format_row))

    row_count = crop.max_row - crop.min_row + 1
    column_count = crop.max_col - crop.min_col + 1
    top_positions = tuple(
        (-1, -1, -1, col)
        for _row in range(row_count)
        for col in range(column_count)
    )
    left_positions = tuple(
        (-1, -1, -1, row)
        for row in range(row_count)
        for _col in range(column_count)
    )
    target_address = parse_address(target[1])
    table_range = (
        f"{num_to_col(crop.min_col)}{crop.min_row}:"
        f"{num_to_col(crop.max_col)}{crop.max_row}"
    )
    return FCRLTableInput(
        target=target,
        table_range=table_range,
        string_matrix=tuple(strings),
        format_matrix=tuple(formats),
        top_positions=top_positions,
        left_positions=left_positions,
        header_rows=int(crop.min_row == component.min_row),
        header_columns=int(crop.min_col == component.min_col),
        formula_prefix=prefix,
        target_row=target_address.row - crop.min_row,
        target_column=target_address.col - crop.min_col,
    )


def translated_peer_candidates(
    model: WorkbookModel,
    target: CellKey,
    *,
    exclude_observed: bool = True,
) -> tuple[PeerCandidate, ...]:
    """Return deterministic peer proposals with contiguous formula blocks deduplicated."""
    if target not in model.formulas:
        raise FCRLAdapterError("target_not_formula")
    component = component_bounds(model, target)
    target_address = parse_address(target[1])
    observed = normalized_formula(model.formulas[target]) if exclude_observed else None

    records: list[tuple[str, int, int, str, str, int]] = []
    for peer in model.formula_cells:
        if peer == target or peer[0] != target[0] or not model.is_visible(peer):
            continue
        address = parse_address(peer[1])
        if not component.contains(address.row, address.col):
            continue
        if address.row != target_address.row and address.col != target_address.col:
            continue
        orientation = "row" if address.row == target_address.row else "column"
        axis = address.col if orientation == "row" else address.row
        fixed = address.row if orientation == "row" else address.col
        try:
            translated = translate_formula(model.formulas[peer], peer[1], target[1])
            translated_prefix = formula_to_prefix(translated)
            for reference in translated_prefix.reference_addresses:
                ref = parse_address(reference)
                if not component.contains(ref.row, ref.col):
                    raise FCRLAdapterError("reference_outside_component")
        except (FormulaSyntaxError, ValueError, FCRLAdapterError):
            continue
        normalized = normalized_formula(translated)
        if observed is not None and normalized == observed:
            continue
        distance = abs(address.row - target_address.row) + abs(address.col - target_address.col)
        records.append((orientation, fixed, axis, normalized, translated, distance))

    by_line: dict[tuple[str, int], list[tuple[int, str, str, int]]] = {}
    for orientation, fixed, axis, normalized, translated, distance in records:
        by_line.setdefault((orientation, fixed), []).append((axis, normalized, translated, distance))

    support: dict[str, dict[str, object]] = {}
    for (orientation, fixed), line_records in sorted(by_line.items()):
        prior_axis: int | None = None
        prior_normalized: str | None = None
        block_index = 0
        for axis, normalized, translated, distance in sorted(line_records):
            if prior_axis is None or axis != prior_axis + 1 or normalized != prior_normalized:
                block_index += 1
            block_id = f"{orientation}:{fixed}:{block_index}"
            item = support.setdefault(
                normalized,
                {"formulas": set(), "blocks": set(), "distance": distance},
            )
            formulas = item["formulas"]
            blocks = item["blocks"]
            assert isinstance(formulas, set) and isinstance(blocks, set)
            formulas.add(translated)
            blocks.add(block_id)
            item["distance"] = min(int(item["distance"]), distance)
            prior_axis = axis
            prior_normalized = normalized

    candidates = [
        PeerCandidate(
            formula=min(item["formulas"]),  # type: ignore[arg-type]
            normalized=normalized,
            block_ids=tuple(sorted(item["blocks"])),  # type: ignore[arg-type]
            nearest_distance=int(item["distance"]),
        )
        for normalized, item in support.items()
    ]
    return tuple(sorted(candidates, key=lambda item: (item.nearest_distance, item.normalized)))


def local_peer_completion_keys(model: WorkbookModel, target: CellKey) -> tuple[str, ...]:
    """Top-5 U1 peer completions computed without inspecting the target formula."""
    candidates = translated_peer_candidates(model, target, exclude_observed=False)
    keyed: dict[str, tuple[int, int]] = {}
    for candidate in candidates:
        try:
            key = formula_prediction_key(candidate.formula)
        except FCRLAdapterError:
            continue
        ordering = (-len(candidate.block_ids), candidate.nearest_distance)
        if key not in keyed or ordering < keyed[key]:
            keyed[key] = ordering
    return tuple(
        key
        for key, _ in sorted(keyed.items(), key=lambda item: (*item[1], item[0]))[:5]
    )


def independently_supported_alternatives(
    observed_formula: str,
    peer_candidates: Sequence[PeerCandidate],
    decoder_candidates: Iterable[str],
) -> tuple[str, ...]:
    observed = normalized_formula(observed_formula)
    decoder = {normalized_formula(formula) for formula in decoder_candidates}
    supported = {
        candidate.normalized
        for candidate in peer_candidates
        if candidate.normalized != observed
        and (len(candidate.block_ids) >= 2 or candidate.normalized in decoder)
    }
    return tuple(sorted(supported))
