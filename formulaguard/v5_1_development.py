"""V5.1-development: gated workbook diagnosis with robust template repair.

This module is intentionally separate from the frozen V5-R2 implementation.
It first decides whether a workbook has actionable evidence, then reconstructs
candidate templates from unaffected peers and semantic column roles.  It never
mutates the workbook and only emits a repair candidate when a workbook-level
gate and a candidate-level gate both pass.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from .a1 import num_to_col, parse_address
from .formula import (
    Binary,
    Func,
    Range,
    Ref,
    fingerprint,
    parse_formula,
    small_edit_candidates_with_kinds,
    translate_formula,
)
from .localize import LocalizationResult
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5.1-development"
DEFAULT_RADIUS = 6
MIN_TEMPLATE_SUPPORT = 3
MIN_GROUP_SIZE = 3
MIN_CONFIDENCE = 0.75
MIN_ANOMALY = 0.70
VOLATILE_HEADERS = ("tax", "vat", "调整", "ajuste")


def v5_1_development_default_parameters() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "architecture": "workbook_gate_robust_template_consensus_semantic_synthesis",
        "radius": DEFAULT_RADIUS,
        "min_template_support": MIN_TEMPLATE_SUPPORT,
        "min_group_size": MIN_GROUP_SIZE,
        "min_candidate_confidence": MIN_CONFIDENCE,
        "min_anomaly_score": MIN_ANOMALY,
        "workbook_gate": "two_channel_or_stable_template_consensus",
        "candidate_sources": ["peer_translation", "small_edit", "semantic_synthesis"],
        "labels_at_localization": False,
        "automatic_edit_applied": False,
        "frozen_v5_r2_untouched": True,
    }


def _coordinate(cell: CellKey) -> tuple[str, int, int]:
    address = parse_address(cell[1])
    return cell[0], address.row, address.col


def _header_row(model: WorkbookModel, cell: CellKey) -> int | None:
    sheet, row, col = _coordinate(cell)
    for candidate in range(row - 1, 0, -1):
        value = model.cells.get((sheet, f"{num_to_col(col)}{candidate}"))
        if isinstance(value, str) and value.strip() and not value.startswith("="):
            return candidate
    return None


def _headers(model: WorkbookModel, cell: CellKey) -> dict[int, str]:
    header_row = _header_row(model, cell)
    if header_row is None:
        return {}
    sheet, _, _ = _coordinate(cell)
    return {
        col: value.strip().lower()
        for col in range(1, 40)
        if isinstance(
            (value := model.cells.get((sheet, f"{num_to_col(col)}{header_row}"))),
            str,
        )
        and value.strip()
        and not value.startswith("=")
    }


def _signature(formula: str, address: str) -> str:
    try:
        return fingerprint(parse_formula(formula), parse_address(address))
    except ValueError:
        return "UNSUPPORTED:" + "".join(formula.split()).upper()


def _same_column_peers(
    model: WorkbookModel, cell: CellKey, radius: int
) -> list[CellKey]:
    sheet, row, col = _coordinate(cell)
    formula_set = set(model.formula_cells)
    peers: list[CellKey] = []
    for distance in range(1, radius + 1):
        for peer_row in (row - distance, row + distance):
            if peer_row < 1:
                continue
            peer = (sheet, f"{num_to_col(col)}{peer_row}")
            if peer in formula_set:
                peers.append(peer)
    return peers


def _role_penalty(model: WorkbookModel, cell: CellKey, formula: str) -> float:
    header = _headers(model, cell)
    sheet, row, col = _coordinate(cell)
    # Totals/subtotals are aggregate rows, not row-wise formula roles.  Their
    # formulas legitimately differ from the repeated data-row template and
    # must not open the repair gate on an otherwise clean workbook.
    row_text = " ".join(
        str(model.cells.get((sheet, f"{num_to_col(number)}{row}"), ""))
        for number in range(1, 40)
    ).upper()
    if any(
        token in row_text for token in ("TOTAL", "SUBTOTAL", "总计", "小计", "TOTAL")
    ):
        return 0.0
    label = header.get(col, "").upper()
    try:
        node = parse_formula(formula)
    except ValueError:
        return 0.0

    def contains(node_value: object, name: str) -> bool:
        return isinstance(node_value, Func) and (
            node_value.name == name
            or any(contains(arg, name) for arg in node_value.args)
        )

    refs = {ref.address.col for ref in _iter_refs(node) if ref.sheet in (None, cell[0])}
    unit_cols = {
        number
        for number, value in header.items()
        if any(
            token in value.upper()
            for token in ("UNIT", "QUANTITY", "SEAT", "COUNT", "数量", "单位", "UNIDAD")
        )
    }
    price_cols = {
        number
        for number, value in header.items()
        if any(
            token in value.upper()
            for token in ("PRICE", "RATE", "单价", "价格", "PRECIO", "TARIFA")
        )
    }
    revenue = any(
        token in label
        for token in (
            "REVENUE",
            "SALES",
            "INCOME",
            "收入",
            "销售",
            "INGRESOS",
            "VENTAS",
        )
    )
    margin = any(
        token in label
        for token in (
            "MARGIN",
            "PROFIT",
            "VARIANCE",
            "DIFFERENCE",
            "利润",
            "差异",
            "MARGEN",
            "BENEFICIO",
        )
    )
    average = any(token in label for token in ("AVERAGE", "MEAN", "平均", "PROMEDIO"))
    penalty = 0.0
    if revenue and unit_cols and price_cols:
        has_unit = bool(refs & unit_cols)
        has_price = bool(refs & price_cols)
        has_multiply = _has_operator(node, "*")
        if not (has_unit and has_price and has_multiply):
            penalty = max(penalty, 0.92)
    if margin and not _has_operator(node, "-") and not contains(node, "SUM"):
        penalty = max(penalty, 0.90)
    if (
        average
        and not contains(node, "AVERAGE")
        and not contains(node, "SUM")
        and not contains(node, "IF")
    ):
        penalty = max(penalty, 0.75)
    return penalty


def _iter_refs(node: object) -> Iterable[Ref]:
    if isinstance(node, Ref):
        yield node
    elif isinstance(node, Range):
        yield node.start
        yield node.end
    elif isinstance(node, Binary):
        yield from _iter_refs(node.left)
        yield from _iter_refs(node.right)
    elif isinstance(node, Func):
        for arg in node.args:
            yield from _iter_refs(arg)


def _has_operator(node: object, operator: str) -> bool:
    if isinstance(node, Binary):
        return (
            node.op == operator
            or _has_operator(node.left, operator)
            or _has_operator(node.right, operator)
        )
    if isinstance(node, Func):
        return any(_has_operator(arg, operator) for arg in node.args)
    return False


def _semantic_candidates(model: WorkbookModel, cell: CellKey) -> list[tuple[str, str]]:
    headers = _headers(model, cell)
    _, row, col = _coordinate(cell)
    target_label = headers.get(col, "").upper()
    result: list[tuple[str, str]] = []
    unit_cols = [
        number
        for number, value in headers.items()
        if any(
            token in value.upper()
            for token in ("UNIT", "QUANTITY", "SEAT", "COUNT", "数量", "单位", "UNIDAD")
        )
    ]
    price_cols = [
        number
        for number, value in headers.items()
        if any(
            token in value.upper()
            for token in ("PRICE", "RATE", "单价", "价格", "PRECIO", "TARIFA")
        )
    ]
    revenue = any(
        token in target_label
        for token in (
            "REVENUE",
            "SALES",
            "INCOME",
            "收入",
            "销售",
            "INGRESOS",
            "VENTAS",
        )
    )
    if revenue and unit_cols and price_cols:
        result.append(
            (
                f"={num_to_col(unit_cols[0])}{row}*{num_to_col(price_cols[0])}{row}",
                "semantic_revenue_product",
            )
        )
    if any(
        token in target_label
        for token in (
            "MARGIN",
            "PROFIT",
            "VARIANCE",
            "DIFFERENCE",
            "利润",
            "差异",
            "MARGEN",
            "BENEFICIO",
        )
    ):
        revenue_cols = [
            number
            for number, value in headers.items()
            if any(
                token in value.upper()
                for token in (
                    "REVENUE",
                    "SALES",
                    "INCOME",
                    "收入",
                    "销售",
                    "INGRESOS",
                    "VENTAS",
                )
            )
        ]
        cost_cols = [
            number
            for number, value in headers.items()
            if any(
                token in value.upper()
                for token in ("COST", "EXPENSE", "成本", "费用", "COSTE", "GASTO")
            )
        ]
        if revenue_cols and cost_cols:
            result.append(
                (
                    f"={num_to_col(revenue_cols[0])}{row}-{num_to_col(cost_cols[0])}{row}",
                    "semantic_margin_difference",
                )
            )
    return result


def _candidate_pool(
    model: WorkbookModel, cell: CellKey, peers: list[CellKey]
) -> dict[str, tuple[str, str, int]]:
    candidates: dict[str, tuple[str, str, int]] = {}
    originals = model.formulas[cell]
    choices: list[tuple[str, str]] = [
        (formula, "small_edit")
        for formula, _ in small_edit_candidates_with_kinds(originals)
    ]
    choices.extend(_semantic_candidates(model, cell))
    for peer in peers:
        try:
            choices.append(
                (
                    translate_formula(model.formulas[peer], peer[1], cell[1]),
                    "peer_translation",
                )
            )
        except ValueError:
            continue
    for formula, source in choices:
        if formula == originals:
            continue
        template = _signature(formula, cell[1])
        previous = candidates.get(template)
        # Prefer an explicit semantic reconstruction over a coincidentally
        # identical one-edit candidate. This lets systematic columns rely on
        # semantics even when every peer is corrupted.
        cost = 0 if source.startswith("semantic_") else 1
        if previous is None or cost < previous[2]:
            candidates[template] = (formula, source, cost)
    return candidates


def _formula_regions(cells: Iterable[CellKey]) -> list[list[CellKey]]:
    buckets: dict[tuple[str, int], list[CellKey]] = defaultdict(list)
    for cell in cells:
        sheet, _, col = _coordinate(cell)
        buckets[(sheet, col)].append(cell)
    regions: list[list[CellKey]] = []
    for values in buckets.values():
        values.sort(key=lambda item: _coordinate(item)[1])
        current: list[CellKey] = []
        for cell in values:
            if current and _coordinate(cell)[1] != _coordinate(current[-1])[1] + 1:
                regions.append(current)
                current = []
            current.append(cell)
        if current:
            regions.append(current)
    return regions


def v5_1_development_scores(
    model: WorkbookModel,
    *,
    radius: int = DEFAULT_RADIUS,
    min_template_support: int = MIN_TEMPLATE_SUPPORT,
    min_group_size: int = MIN_GROUP_SIZE,
) -> list[LocalizationResult]:
    """Return a complete ranking with gated cell and region candidates."""
    signatures = {
        cell: _signature(model.formulas[cell], cell[1]) for cell in model.formula_cells
    }
    by_column: dict[tuple[str, int], list[CellKey]] = defaultdict(list)
    for cell in model.formula_cells:
        sheet, _, col = _coordinate(cell)
        by_column[(sheet, col)].append(cell)
    dominant: dict[tuple[str, int], tuple[str, int]] = {}
    for key, cells in by_column.items():
        counts = Counter(signatures[cell] for cell in cells)
        dominant[key] = counts.most_common(1)[0]

    records: dict[CellKey, dict[str, object]] = {}
    for cell in model.formula_cells:
        sheet, _, col = _coordinate(cell)
        peers = _same_column_peers(model, cell, radius)
        signature, support = dominant[(sheet, col)]
        local_signature = signatures[cell]
        local_residual = (
            0.0
            if local_signature == signature
            else min(1.0, 1.0 - support / max(1, len(by_column[(sheet, col)])))
        )
        semantic = _role_penalty(model, cell, model.formulas[cell])
        pool = _candidate_pool(model, cell, peers)
        peer_templates = Counter(
            _signature(translate_formula(model.formulas[p], p[1], cell[1]), cell[1])
            for p in peers
            if _safe_translate(model.formulas[p], p[1], cell[1])
        )
        best: tuple[str, str, float, str] | None = None
        for template, (formula, source, _) in pool.items():
            peer_support = peer_templates.get(template, 0)
            confidence = max(
                peer_support / max(1, len(peers)),
                1.0 if source.startswith("semantic_") else 0.0,
            )
            gain = max(0.0, semantic - _role_penalty(model, cell, formula))
            quality = 0.55 * confidence + 0.45 * gain
            if best is None or quality > best[2]:
                best = (formula, source, quality, template)
        # A strong semantic contradiction is actionable even when the wrong
        # template has become the observed majority (systematic-column case).
        # Residual disagreement adds evidence for isolated/block anomalies but
        # must not be required when an entire region is poisoned.
        anomaly = min(1.0, max(semantic, 0.55 * semantic + 0.45 * local_residual))
        records[cell] = {
            "semantic": semantic,
            "local_residual": local_residual,
            "anomaly": anomaly,
            "candidate": best,
            "peer_support": peer_templates.get(best[3], 0) if best else 0,
            "dominance": support / max(1, len(by_column[(sheet, col)])),
        }

    accepted: dict[CellKey, tuple[str, str, str, int]] = {}
    for region in _formula_regions(model.formula_cells):
        suspicious = [
            cell for cell in region if records[cell]["anomaly"] >= MIN_ANOMALY
        ]
        if not suspicious:
            continue
        groups: dict[str, list[CellKey]] = defaultdict(list)
        for cell in suspicious:
            best = records[cell]["candidate"]
            if best is not None:
                groups[str(best[3])].append(cell)
        for template, cells in groups.items():
            if len(cells) < min_group_size and len(region) > 1 and len(cells) != 1:
                # A single semantic contradiction may still be actionable when
                # its candidate is strongly supported by unaffected peers.
                # Smaller confidence is allowed only for a multi-cell region
                # whose candidate template wins by consensus.
                continue
            if len(cells) / max(1, len(suspicious)) < 0.60:
                continue
            group_quality = max(float(records[cell]["candidate"][2]) for cell in cells)
            for cell in cells:
                formula, source, quality, _ = records[cell]["candidate"]  # type: ignore[misc]
                required_confidence = 0.90 if len(cells) == 1 else MIN_CONFIDENCE
                if len(cells) == 1 and (
                    int(records[cell]["peer_support"]) < min_template_support
                    or float(records[cell]["dominance"]) < 0.70
                ):
                    continue
                if group_quality >= required_confidence:
                    accepted[cell] = (formula, source, template, len(cells))

    results: list[LocalizationResult] = []
    for cell in model.formula_cells:
        record = records[cell]
        candidate = accepted.get(cell)
        evidence: dict[str, float | int | str] = {
            "model_version": MODEL_VERSION,
            "workbook_gate": "passed" if candidate else "abstained",
            "anomaly_score": float(record["anomaly"]),
            "local_template_residual": float(record["local_residual"]),
            "header_role_penalty": float(record["semantic"]),
            "candidate_confidence": float(record["candidate"][2])
            if record["candidate"]
            else 0.0,
            "candidate_origin": str(candidate[1]) if candidate else "none",
            "automatic_edit_applied": False,
            "group_state": "accepted" if candidate else "not_applicable",
            "group_reason": "robust_template_consensus"
            if candidate
            else "workbook_gate_or_insufficient_consensus",
            "group_propagated": int(
                candidate is not None and candidate[3] >= min_group_size
            ),
            "group_size": candidate[3] if candidate else 0,
        }
        score = min(
            1.0,
            0.60 * float(record["anomaly"])
            + 0.40 * (float(record["candidate"][2]) if record["candidate"] else 0.0),
        )
        results.append(
            LocalizationResult(
                cell=cell,
                score=score,
                candidate_formula=candidate[0] if candidate else None,
                evidence=evidence,
            )
        )
    results.sort(key=lambda item: (-item.score, item.cell))
    for rank, result in enumerate(results, 1):
        result.evidence["final_rank"] = rank
    return results


def _safe_translate(formula: str, source: str, target: str) -> str | None:
    try:
        return translate_formula(formula, source, target)
    except ValueError:
        return None
