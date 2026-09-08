"""Masked structural tokens and peer candidates for PCRC."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence

from .a1 import Address, parse_address
from .formula import Binary, Func, Node, Number, Range, Ref, Unary, parse_formula
from .model_discovery import SignalAuditConfig, audit_workbook
from .workbook import CellKey, WorkbookModel

PROTOCOL = "formulaguard_pcrc_v1"
CORPUS_PROTOCOL = "formulaguard_pcrc_corpus_v1"
MAX_TARGETS_PER_WORKBOOK = 200
MAX_CONTEXT_TOKENS = 384
MAX_FORMULA_TOKENS = 96
DIRECTIONAL_PEERS = 4
DEPENDENT_FORMULAS = 8
PEER_CONFIG = SignalAuditConfig(
    axis_radius=12,
    local_radius=6,
    max_axis_peers=16,
    max_local_peers=24,
    max_role_peers=16,
    max_hypotheses=4,
)
SPECIAL_TOKENS = ("<PAD>", "<UNK>", "<START>", "<END>")


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def cell_label(cell: CellKey) -> str:
    return f"{cell[0]}!{cell[1]}"


def _cell_sort(cell: CellKey) -> tuple[str, int, int, str]:
    address = parse_address(cell[1])
    return cell[0], address.row, address.col, cell[1]


def _reference_tokens(
    ref: Ref,
    anchor: Address,
    current_sheet: str,
    *,
    inherited_relation: str | None = None,
) -> list[str]:
    relation = inherited_relation or (
        "SELF" if ref.sheet is None or ref.sheet.casefold() == current_sheet.casefold() else "OTHER"
    )
    tokens = ["REF", relation]
    for axis, absolute, value, origin in (
        ("ROW", ref.address.row_abs, ref.address.row, anchor.row),
        ("COL", ref.address.col_abs, ref.address.col, anchor.col),
    ):
        tokens.append(f"{axis}_{'ABS' if absolute else 'REL'}")
        coordinate = value if absolute else value - origin
        tokens.append("OFFSET_ZERO" if coordinate == 0 else "OFFSET_POS" if coordinate > 0 else "OFFSET_NEG")
        tokens.extend(f"DIGIT_{digit}" for digit in str(abs(coordinate)))
    return tokens


def numeric_category(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("formula numeric literal is non-finite")
    if value == 0:
        return "NUM_ZERO"
    if value == 1:
        return "NUM_ONE"
    if value == -1:
        return "NUM_NEG_ONE"
    prefix = "NUM_NEG_" if value < 0 else "NUM_"
    magnitude = float(abs(value))
    if not magnitude.is_integer():
        return prefix + "FRACTION"
    if magnitude < 10:
        return prefix + "INTEGER_2_9"
    if magnitude < 100:
        return prefix + "INTEGER_10_99"
    return prefix + "INTEGER_100_PLUS"


def _ast_tokens(node: Node, anchor: Address, current_sheet: str) -> list[str]:
    if isinstance(node, Number):
        return [numeric_category(node.value)]
    if isinstance(node, Ref):
        return _reference_tokens(node, anchor, current_sheet)
    if isinstance(node, Range):
        start_relation = (
            "SELF"
            if node.start.sheet is None or node.start.sheet.casefold() == current_sheet.casefold()
            else "OTHER"
        )
        return [
            "RANGE_START",
            *_reference_tokens(node.start, anchor, current_sheet),
            "RANGE_SEP",
            *_reference_tokens(
                node.end,
                anchor,
                current_sheet,
                inherited_relation=start_relation if node.end.sheet is None else None,
            ),
            "RANGE_END",
        ]
    if isinstance(node, Unary):
        return ["UNARY", f"OP_{node.op}", *_ast_tokens(node.value, anchor, current_sheet), "UNARY_END"]  # type: ignore[arg-type]
    if isinstance(node, Binary):
        return [
            "BINARY", f"OP_{node.op}", "LEFT",
            *_ast_tokens(node.left, anchor, current_sheet),  # type: ignore[arg-type]
            "RIGHT", *_ast_tokens(node.right, anchor, current_sheet),  # type: ignore[arg-type]
            "BINARY_END",
        ]
    if isinstance(node, Func):
        tokens = ["FUNCTION", f"FUNC_{node.name}", f"ARITY_{min(len(node.args), 8)}"]
        for index, argument in enumerate(node.args):
            tokens.extend((f"ARG_{min(index, 7)}", *_ast_tokens(argument, anchor, current_sheet)))  # type: ignore[arg-type]
        tokens.append("FUNCTION_END")
        return tokens
    raise TypeError(type(node))


def formula_tokens(formula: str, anchor_text: str, current_sheet: str) -> tuple[str, ...]:
    tokens = _ast_tokens(parse_formula(formula), parse_address(anchor_text), current_sheet)
    return tuple(tokens[:MAX_FORMULA_TOKENS])


def _context_formula_tokens(formula: str, anchor_text: str, current_sheet: str) -> tuple[str, ...]:
    try:
        return formula_tokens(formula, anchor_text, current_sheet)
    except (TypeError, ValueError):
        return ("UNSUPPORTED_FORMULA",)


def _format_class(value: str) -> str:
    upper = value.upper()
    if "%" in upper:
        return "FORMAT_PERCENT"
    if any(token in upper for token in ("YY", "DD", "MM", "H", "SS")):
        return "FORMAT_DATE_TIME"
    if upper in {"", "GENERAL", "@"}:
        return "FORMAT_GENERAL_TEXT"
    return "FORMAT_NUMERIC_CUSTOM"


def _count_bucket(value: int) -> str:
    if value == 0:
        return "COUNT_0"
    if value == 1:
        return "COUNT_1"
    if value <= 3:
        return "COUNT_2_3"
    if value <= 7:
        return "COUNT_4_7"
    return "COUNT_8_PLUS"


def _distance_bucket(value: int) -> str:
    if value <= 1:
        return "DIST_1"
    if value <= 3:
        return "DIST_2_3"
    if value <= 7:
        return "DIST_4_7"
    return "DIST_8_PLUS"


def _position_bucket(value: int, minimum: int, maximum: int) -> str:
    if maximum <= minimum:
        return "POSITION_0"
    bucket = min(4, max(0, int((value - minimum) / (maximum - minimum + 1) * 5)))
    return f"POSITION_{bucket}"


def _cell_kind(model: WorkbookModel, key: CellKey, target: CellKey) -> str:
    if key == target:
        return "MASK"
    if key in model.formulas:
        return "FORMULA"
    if key not in model.cells or model.cells[key] in (None, ""):
        return "BLANK"
    return "CONSTANT"


def masked_context_tokens(model: WorkbookModel, target: CellKey) -> tuple[str, ...]:
    """Encode context without reading the target formula or cached value."""

    if target not in model.formulas:
        raise ValueError("PCRC target is not a formula")
    sheet, address_text = target
    address = parse_address(address_text)
    keys = set(model.cells) | set(model.formulas)
    sheet_addresses = [parse_address(key[1]) for key in keys if key[0] == sheet]
    row_min = min((item.row for item in sheet_addresses), default=address.row)
    row_max = max((item.row for item in sheet_addresses), default=address.row)
    col_min = min((item.col for item in sheet_addresses), default=address.col)
    col_max = max((item.col for item in sheet_addresses), default=address.col)

    formula_cells = [
        key for key in model.formula_cells
        if key != target and key[0] == sheet and model.is_visible(key)
    ]
    row_count = sum(
        parse_address(key[1]).row == address.row
        and abs(parse_address(key[1]).col - address.col) <= PEER_CONFIG.axis_radius
        for key in formula_cells
    )
    col_count = sum(
        parse_address(key[1]).col == address.col
        and abs(parse_address(key[1]).row - address.row) <= PEER_CONFIG.axis_radius
        for key in formula_cells
    )
    tokens = [
        "CTX", "ROW_" + _position_bucket(address.row, row_min, row_max),
        "COL_" + _position_bucket(address.col, col_min, col_max),
        _format_class(model.number_format(target)),
        "ROW_" + _count_bucket(row_count), "COL_" + _count_bucket(col_count),
        "TOPOLOGY_START",
    ]
    for drow in range(-2, 3):
        for dcol in range(-2, 3):
            row, col = address.row + drow, address.col + dcol
            kind = "OUTSIDE" if row < 1 or col < 1 else _cell_kind(model, (sheet, _a1(row, col)), target)
            tokens.append(f"TOPO_{drow + 2}_{dcol + 2}_{kind}")
    tokens.append("TOPOLOGY_END")

    directions: dict[str, list[tuple[int, CellKey]]] = defaultdict(list)
    for peer in formula_cells:
        other = parse_address(peer[1])
        drow, dcol = other.row - address.row, other.col - address.col
        if dcol == 0 and drow:
            direction = "UP" if drow < 0 else "DOWN"
            directions[direction].append((abs(drow), peer))
        elif drow == 0 and dcol:
            direction = "LEFT" if dcol < 0 else "RIGHT"
            directions[direction].append((abs(dcol), peer))
    for direction in ("UP", "DOWN", "LEFT", "RIGHT"):
        for distance, peer in sorted(directions[direction], key=lambda item: (item[0], _cell_sort(item[1])))[:DIRECTIONAL_PEERS]:
            tokens.extend(("PEER_START", f"DIR_{direction}", _distance_bucket(distance)))
            tokens.extend(_context_formula_tokens(model.formulas[peer], peer[1], peer[0]))
            tokens.append("PEER_END")

    graph = model.dependency_graph()
    dependents = []
    for dependent in graph.dependents.get(target, ()):
        if dependent == target or dependent not in model.formulas or not model.is_visible(dependent):
            continue
        other = parse_address(dependent[1])
        distance = abs(other.row - address.row) + abs(other.col - address.col) if dependent[0] == sheet else 10**9
        dependents.append((dependent[0] != sheet, distance, dependent))
    for cross_sheet, distance, dependent in sorted(dependents, key=lambda item: (item[0], item[1], _cell_sort(item[2])))[:DEPENDENT_FORMULAS]:
        tokens.extend(("DEPENDENT_START", "CROSS_SHEET" if cross_sheet else "SAME_SHEET", _distance_bucket(distance)))
        tokens.extend(_context_formula_tokens(model.formulas[dependent], dependent[1], dependent[0]))
        tokens.append("DEPENDENT_END")
    tokens.append("CTX_END")
    return tuple(tokens[:MAX_CONTEXT_TOKENS])


def _a1(row: int, col: int) -> str:
    letters = []
    value = col
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters)) + str(row)


def selected_targets(
    model: WorkbookModel,
    *,
    workbook_id: str,
    maximum: int = MAX_TARGETS_PER_WORKBOOK,
) -> tuple[CellKey, ...]:
    if maximum < 1:
        raise ValueError("PCRC target cap must be positive")
    sheets = list(model.sheet_visibility)
    for key in (*model.cells, *model.formulas):
        if key[0] not in sheets:
            sheets.append(key[0])
    sheet_order = {sheet: index for index, sheet in enumerate(sheets)}
    candidates = []
    for key in model.formula_cells:
        if key[0] not in sheet_order or not model.is_visible(key):
            continue
        try:
            formula_tokens(model.formulas[key], key[1], key[0])
        except (TypeError, ValueError):
            continue
        address = parse_address(key[1])
        target_hash = stable_hash({
            "workbook_id": workbook_id,
            "sheet_ordinal": sheet_order[key[0]],
            "row": address.row,
            "col": address.col,
        })
        candidates.append((target_hash, sheet_order[key[0]], address.row, address.col, key))
    candidates.sort()
    return tuple(item[-1] for item in candidates[:maximum])


def workbook_examples(
    model: WorkbookModel,
    *,
    workbook_id: str,
    structure_group: str,
    split: str,
) -> list[dict[str, object]]:
    audit = audit_workbook(model, config=PEER_CONFIG)
    records = {
        str(record["cell"]): record
        for record in audit["records"]  # type: ignore[index]
        if isinstance(record, Mapping)
    }
    examples = []
    for target in selected_targets(model, workbook_id=workbook_id):
        record = records.get(cell_label(target))
        if record is None:
            raise ValueError(f"PCRC peer record missing: {cell_label(target)}")
        observed = formula_tokens(model.formulas[target], target[1], target[0])
        candidates = []
        seen = {observed}
        hypotheses = record.get("repair_hypotheses", [])
        if not isinstance(hypotheses, list):
            raise ValueError("PCRC repair hypotheses are malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        for hypothesis in hypotheses:
            if not isinstance(hypothesis, Mapping) or not isinstance(hypothesis.get("formula"), str):
                raise ValueError("PCRC repair hypothesis is malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
            encoded = formula_tokens(str(hypothesis["formula"]), target[1], target[0])
            if encoded in seen:
                continue
            seen.add(encoded)
            candidates.append({
                "tokens": list(encoded),
                "support_count": int(hypothesis.get("support_count", 0)),
                "support_axis_count": len(hypothesis.get("support_axes", [])),
            })
        address = parse_address(target[1])
        target_id = "pcrc-target:" + stable_hash({
            "workbook_id": workbook_id,
            "sheet": target[0],
            "row": address.row,
            "col": address.col,
        })
        examples.append({
            "protocol": CORPUS_PROTOCOL,
            "target_id": target_id,
            "workbook_id": workbook_id,
            "structure_group": structure_group,
            "split": split,
            "context_tokens": list(masked_context_tokens(model, target)),
            "observed_tokens": list(observed),
            "repair_candidates": candidates,
            "raw_formula_strings_persisted": False,
            "raw_numeric_values_persisted": False,
            "target_formula_tokens_entered_context": False,
        })
    return sorted(examples, key=lambda item: str(item["target_id"]))


class PCRCVocabulary:
    def __init__(self, tokens: Sequence[str]) -> None:
        if tuple(tokens[: len(SPECIAL_TOKENS)]) != SPECIAL_TOKENS or len(tokens) != len(set(tokens)):
            raise ValueError("PCRC vocabulary is invalid")
        self.tokens = tuple(tokens)
        self.ids = {token: index for index, token in enumerate(self.tokens)}

    @classmethod
    def build(cls, token_rows: Sequence[Sequence[str]]) -> PCRCVocabulary:
        counts: dict[str, int] = {}
        for row in token_rows:
            for token in row:
                counts[token] = counts.get(token, 0) + 1
        selected = sorted(counts, key=lambda token: (-counts[token], token))
        return cls((*SPECIAL_TOKENS, *(token for token in selected if token not in SPECIAL_TOKENS)))

    def encode(self, tokens: Sequence[str], *, maximum: int) -> tuple[int, ...]:
        if maximum < 2:
            raise ValueError("PCRC maximum sequence length is too small")
        body = [self.ids.get(token, self.ids["<UNK>"]) for token in tokens[: maximum - 2]]
        return (self.ids["<START>"], *body, self.ids["<END>"])


__all__ = [
    "CORPUS_PROTOCOL",
    "MAX_CONTEXT_TOKENS",
    "MAX_FORMULA_TOKENS",
    "MAX_TARGETS_PER_WORKBOOK",
    "PEER_CONFIG",
    "PROTOCOL",
    "SPECIAL_TOKENS",
    "PCRCVocabulary",
    "formula_tokens",
    "masked_context_tokens",
    "numeric_category",
    "selected_targets",
    "stable_hash",
    "workbook_examples",
]
