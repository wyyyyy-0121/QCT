"""Privacy-bounded structural primitives for cross-workbook role priors."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Mapping

from .a1 import Address, num_to_col, parse_address
from .formula import Binary, Func, Node, Number, Range, Ref, Unary, parse_formula
from .workbook import CellKey, WorkbookModel


PROFILE_PROTOCOL = "formulaguard_cwrp_workbook_profile_v1"
MASKED_EXAMPLE_PROTOCOL = "formulaguard_cwrp_masked_formula_example_v1"
LOCAL_PEER_RADIUS = 12
MAX_TARGETS_PER_WORKBOOK = 200


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sheet_relation(sheet: str | None, current_sheet: str) -> str:
    if sheet is None or sheet.casefold() == current_sheet.casefold():
        return "SELF"
    return "OTHER"


def _ref_fingerprint(
    ref: Ref,
    anchor: Address,
    current_sheet: str,
    *,
    inherited_relation: str | None = None,
) -> str:
    address = ref.address
    row = f"R{address.row}" if address.row_abs else f"R[{address.row - anchor.row:+d}]"
    col = f"C{address.col}" if address.col_abs else f"C[{address.col - anchor.col:+d}]"
    relation = inherited_relation or _sheet_relation(ref.sheet, current_sheet)
    return f"{relation}!{row}{col}"


def _node_fingerprint(node: Node, anchor: Address, current_sheet: str) -> str:
    if isinstance(node, Number):
        return "NUM"
    if isinstance(node, Ref):
        return _ref_fingerprint(node, anchor, current_sheet)
    if isinstance(node, Range):
        start_relation = _sheet_relation(node.start.sheet, current_sheet)
        return (
            "RANGE("
            + _ref_fingerprint(node.start, anchor, current_sheet)
            + ":"
            + _ref_fingerprint(
                node.end,
                anchor,
                current_sheet,
                inherited_relation=start_relation if node.end.sheet is None else None,
            )
            + ")"
        )
    if isinstance(node, Unary):
        return f"U{node.op}({_node_fingerprint(node.value, anchor, current_sheet)})"  # type: ignore[arg-type]
    if isinstance(node, Binary):
        return (
            f"B{node.op}("
            f"{_node_fingerprint(node.left, anchor, current_sheet)},"  # type: ignore[arg-type]
            f"{_node_fingerprint(node.right, anchor, current_sheet)})"  # type: ignore[arg-type]
        )
    if isinstance(node, Func):
        arguments = ",".join(
            _node_fingerprint(argument, anchor, current_sheet)  # type: ignore[arg-type]
            for argument in node.args
        )
        return f"F{node.name}({arguments})"
    raise TypeError(type(node))


def formula_role_fingerprint(formula: str, anchor_text: str, current_sheet: str) -> str:
    """Return a role fingerprint without literals or sheet-name text."""

    return _node_fingerprint(parse_formula(formula), parse_address(anchor_text), current_sheet)


def _value_type(value: object) -> str:
    if value is None or value == "":
        return "blank"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    return "other"


def _format_class(value: str) -> str:
    upper = value.upper()
    if "%" in upper:
        return "percent"
    if any(token in upper for token in ("YY", "DD", "MM", "H", "SS")):
        return "date_or_time"
    if upper in {"", "GENERAL", "@"}:
        return "general_or_text"
    return "numeric_or_custom"


def workbook_profile(model: WorkbookModel) -> dict[str, object]:
    """Build a translation/name-invariant profile without exporting values."""

    keys = set(model.cells) | set(model.formulas)
    by_sheet: dict[str, list[CellKey]] = defaultdict(list)
    for key in keys:
        by_sheet[key[0]].append(key)

    fingerprint_counts: Counter[str] = Counter()
    parseable_by_cell: dict[CellKey, str] = {}
    for key, formula in model.formulas.items():
        try:
            fingerprint = formula_role_fingerprint(formula, key[1], key[0])
        except (TypeError, ValueError):
            continue
        parseable_by_cell[key] = fingerprint
        fingerprint_counts[fingerprint] += 1

    sheet_signatures = []
    for sheet, sheet_keys in by_sheet.items():
        coordinates = [parse_address(key[1]) for key in sheet_keys]
        min_row = min((address.row for address in coordinates), default=1)
        min_col = min((address.col for address in coordinates), default=1)
        cells = []
        formulas = []
        for key in sorted(sheet_keys, key=lambda item: (parse_address(item[1]).row, parse_address(item[1]).col)):
            address = parse_address(key[1])
            relative = (address.row - min_row, address.col - min_col)
            if key in model.formulas:
                kind = "formula"
                formulas.append((*relative, parseable_by_cell.get(key, "UNSUPPORTED")))
            else:
                kind = _value_type(model.cells.get(key))
            cells.append((*relative, kind, _format_class(model.number_format(key))))
        sheet_signatures.append(stable_hash({"cells": cells, "formulas": formulas}))

    counts = [
        {"fingerprint": fingerprint, "count": count}
        for fingerprint, count in sorted(fingerprint_counts.items())
    ]
    return {
        "protocol": PROFILE_PROTOCOL,
        "sheet_count": len(by_sheet),
        "cell_count": len(keys),
        "formula_count": len(model.formulas),
        "parseable_formula_count": len(parseable_by_cell),
        "role_fingerprint_counts": counts,
        "formula_multiset_sha256": stable_hash(counts),
        "structural_signature": stable_hash(sorted(sheet_signatures)),
        "sensitive_text_features": 0,
        "raw_numeric_features": 0,
        "sheet_name_features": 0,
        "formula_literal_features": 0,
    }


def profile_counter(profile: Mapping[str, object]) -> Counter[str]:
    rows = profile.get("role_fingerprint_counts")
    if not isinstance(rows, list):
        raise ValueError("profile has no role fingerprint counts")
    counter: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("role fingerprint count row is malformed")
        fingerprint = str(row.get("fingerprint", ""))
        count = row.get("count")
        if not fingerprint or not isinstance(count, int) or count < 1:
            raise ValueError("role fingerprint count is invalid")
        counter[fingerprint] += count
    if sum(counter.values()) != profile.get("parseable_formula_count"):
        raise ValueError("role fingerprint counts do not match parseable formula count")
    return counter


def weighted_jaccard(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    numerator = sum(min(int(left.get(key, 0)), int(right.get(key, 0))) for key in keys)
    denominator = sum(max(int(left.get(key, 0)), int(right.get(key, 0))) for key in keys)
    return numerator / denominator if denominator else 0.0


def formula_count_ratio_eligible(left: int, right: int, *, minimum: float = 0.5, maximum: float = 2.0) -> bool:
    if left <= 0 or right <= 0:
        return False
    ratio = left / right
    return minimum <= ratio <= maximum


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2_3"
    if value <= 7:
        return "4_7"
    return "8_plus"


def _distance_bucket(value: int) -> str:
    if value <= 1:
        return "1"
    if value <= 3:
        return "2_3"
    if value <= 7:
        return "4_7"
    return "8_12"


def _position_bucket(value: int, minimum: int, maximum: int) -> int:
    if maximum <= minimum:
        return 0
    fraction = (value - minimum) / (maximum - minimum + 1)
    return min(4, max(0, int(fraction * 5)))


def _fingerprint_root(value: str) -> str:
    return value.split("(", 1)[0]


def _cell_category(model: WorkbookModel, key: CellKey) -> str:
    if key in model.formulas:
        return "formula"
    if key not in model.cells:
        return "blank"
    return _value_type(model.cells[key])


def masked_formula_examples(
    model: WorkbookModel,
    *,
    workbook_id: str,
    template_group_id: str,
    outer_fold: int,
    max_targets: int = MAX_TARGETS_PER_WORKBOOK,
    local_radius: int = LOCAL_PEER_RADIUS,
) -> list[dict[str, object]]:
    """Build deterministic self-supervised examples with the target masked."""

    if not workbook_id or not template_group_id:
        raise ValueError("masked examples require workbook and template group IDs")
    if outer_fold not in range(5):
        raise ValueError("outer_fold must be between 0 and 4")
    if max_targets < 1 or local_radius < 1:
        raise ValueError("target limit and local radius must be positive")

    parseable: dict[CellKey, str] = {}
    for key, formula in model.formulas.items():
        try:
            parseable[key] = formula_role_fingerprint(formula, key[1], key[0])
        except (TypeError, ValueError):
            continue
    if not parseable:
        return []

    sheet_order: dict[str, int] = {}
    for key in list(model.cells) + list(model.formulas):
        if key[0] not in sheet_order:
            sheet_order[key[0]] = len(sheet_order)
    all_keys = set(model.cells) | set(model.formulas)
    bounds: dict[str, tuple[int, int, int, int]] = {}
    for sheet in sheet_order:
        coordinates = [parse_address(key[1]) for key in all_keys if key[0] == sheet]
        bounds[sheet] = (
            min((address.row for address in coordinates), default=1),
            max((address.row for address in coordinates), default=1),
            min((address.col for address in coordinates), default=1),
            max((address.col for address in coordinates), default=1),
        )

    graph = model.dependency_graph()
    candidates = []
    for key in parseable:
        address = parse_address(key[1])
        selection_key = stable_hash({
            "workbook_id": workbook_id,
            "sheet_ordinal": sheet_order[key[0]],
            "row": address.row,
            "col": address.col,
        })
        candidates.append((selection_key, sheet_order[key[0]], address.row, address.col, key))
    candidates.sort()
    selected = [item[-1] for item in candidates[:max_targets]]

    by_sheet: dict[str, list[CellKey]] = defaultdict(list)
    for key in parseable:
        by_sheet[key[0]].append(key)
    for values in by_sheet.values():
        values.sort(key=lambda key: (parse_address(key[1]).row, parse_address(key[1]).col))

    examples = []
    for key in selected:
        sheet, address_text = key
        address = parse_address(address_text)
        row_min, row_max, col_min, col_max = bounds[sheet]
        peers = []
        directional: dict[str, tuple[int, str] | None] = {
            "up": None, "down": None, "left": None, "right": None,
        }
        for other in by_sheet[sheet]:
            if other == key:
                continue
            other_address = parse_address(other[1])
            drow = other_address.row - address.row
            dcol = other_address.col - address.col
            if drow == 0 and 0 < abs(dcol) <= local_radius:
                peers.append(other)
                direction = "left" if dcol < 0 else "right"
                distance = abs(dcol)
            elif dcol == 0 and 0 < abs(drow) <= local_radius:
                peers.append(other)
                direction = "up" if drow < 0 else "down"
                distance = abs(drow)
            else:
                continue
            current = directional[direction]
            if current is None or distance < current[0] or (distance == current[0] and parseable[other] < current[1]):
                directional[direction] = (distance, parseable[other])

        local_counts = Counter(parseable[other] for other in peers)
        local_candidates = [
            {"fingerprint": fingerprint, "count": count}
            for fingerprint, count in sorted(local_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        target_fingerprint = parseable[key]
        locally_unsupported = local_counts[target_fingerprint] == 0

        topology = []
        for drow in (-1, 0, 1):
            for dcol in (-1, 0, 1):
                if drow == 0 and dcol == 0:
                    continue
                row = address.row + drow
                col = address.col + dcol
                if row < 1 or col < 1:
                    topology.append("outside")
                    continue
                topology.append(_cell_category(model, (sheet, f"{num_to_col(col)}{row}")))

        row_formula_count = sum(
            other != key
            and parse_address(other[1]).row == address.row
            and abs(parse_address(other[1]).col - address.col) <= local_radius
            for other in by_sheet[sheet]
        )
        col_formula_count = sum(
            other != key
            and parse_address(other[1]).col == address.col
            and abs(parse_address(other[1]).row - address.row) <= local_radius
            for other in by_sheet[sheet]
        )
        dependent_fingerprints = sorted(
            parseable[dependent]
            for dependent in graph.dependents.get(key, ())
            if dependent != key and dependent in parseable
        )
        dependent_roots = sorted(_fingerprint_root(value) for value in dependent_fingerprints)
        neighbor_fingerprints = {
            direction: "NONE" if item is None else f"{_distance_bucket(item[0])}:{item[1]}"
            for direction, item in sorted(directional.items())
        }
        neighbor_roots = {
            direction: "NONE" if item is None else f"{_distance_bucket(item[0])}:{_fingerprint_root(item[1])}"
            for direction, item in sorted(directional.items())
        }
        coarse = {
            "row_position": _position_bucket(address.row, row_min, row_max),
            "col_position": _position_bucket(address.col, col_min, col_max),
            "format": _format_class(model.number_format(key)),
            "topology_3x3": topology,
            "row_formula_density": _count_bucket(row_formula_count),
            "col_formula_density": _count_bucket(col_formula_count),
            "dependent_formula_count": _count_bucket(len(dependent_fingerprints)),
        }
        role = {
            **coarse,
            "neighbor_roots": neighbor_roots,
            "dependent_roots": dependent_roots[:8],
        }
        exact = {
            **role,
            "neighbor_fingerprints": neighbor_fingerprints,
            "dependent_fingerprints": dependent_fingerprints[:8],
        }
        example_id = "masked:" + stable_hash({
            "workbook_id": workbook_id,
            "sheet_ordinal": sheet_order[sheet],
            "row": address.row,
            "col": address.col,
        })
        examples.append({
            "protocol": MASKED_EXAMPLE_PROTOCOL,
            "example_id": example_id,
            "workbook_id": workbook_id,
            "template_group_id": template_group_id,
            "outer_fold": outer_fold,
            "target_fingerprint": target_fingerprint,
            "context_keys": {
                "exact": stable_hash(exact),
                "role": stable_hash(role),
                "coarse": stable_hash(coarse),
            },
            "local_peer_candidates": local_candidates[:5],
            "locally_unsupported": locally_unsupported,
            "sensitive_text_features": 0,
            "raw_numeric_features": 0,
            "sheet_name_features": 0,
            "target_formula_features": 0,
        })
    return sorted(examples, key=lambda item: str(item["example_id"]))
