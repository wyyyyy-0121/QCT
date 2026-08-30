"""Privacy-bounded structural primitives for cross-workbook role priors."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Mapping

from .a1 import Address, parse_address
from .formula import Binary, Func, Node, Number, Range, Ref, Unary, parse_formula
from .workbook import CellKey, WorkbookModel


PROFILE_PROTOCOL = "formulaguard_cwrp_workbook_profile_v1"


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
