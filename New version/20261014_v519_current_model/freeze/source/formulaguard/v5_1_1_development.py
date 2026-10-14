"""V5.1.1-development: conservative roles, consensus, and abstention.

This is a new development lineage built on top of the frozen V5.1 code.  It
keeps the original model untouched and tightens the semantic gate before
adding the natural-structure roles exposed by the V5.1 confirmation cohort.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .a1 import num_to_col
from .formula import (
    Binary,
    Func,
    Range,
    parse_formula,
    small_edit_candidates_with_kinds,
)
from .localize import LocalizationResult
from .v5_1_development import (
    _coordinate,
    _formula_regions,
    _headers,
    _safe_translate,
    _same_column_peers,
    _signature,
)
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5.1.1-development"
DEFAULT_RADIUS = 6
MIN_TEMPLATE_SUPPORT = 3
MIN_GROUP_SIZE = 3
MIN_CONFIDENCE = 0.75
MIN_ANOMALY = 0.70
MIN_DOMINANCE = 0.70
MIN_TEMPLATE_MARGIN = 0.20


def v5_1_1_development_default_parameters() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "architecture": "conservative_role_registry_consensus_function_compatibility",
        "radius": DEFAULT_RADIUS,
        "min_template_support": MIN_TEMPLATE_SUPPORT,
        "min_group_size": MIN_GROUP_SIZE,
        "min_candidate_confidence": MIN_CONFIDENCE,
        "min_anomaly_score": MIN_ANOMALY,
        "min_peer_dominance": MIN_DOMINANCE,
        "min_template_margin": MIN_TEMPLATE_MARGIN,
        "workbook_gate": "role_compatibility_and_consensus_or_anchored_region",
        "candidate_sources": ["peer_translation", "small_edit", "semantic_role_registry"],
        "ratio_columns_excluded": True,
        "unknown_function_abstention": True,
        "labels_at_localization": False,
        "automatic_edit_applied": False,
        "frozen_v5_1_untouched": True,
    }


def _contains(node: object, name: str) -> bool:
    return isinstance(node, Func) and (
        node.name == name or any(_contains(arg, name) for arg in node.args)
    )


def _function_names(node: object) -> set[str]:
    if isinstance(node, Func):
        return {node.name} | {
            name for arg in node.args for name in _function_names(arg)
        }
    if isinstance(node, Binary):
        return _function_names(node.left) | _function_names(node.right)
    if isinstance(node, Range):
        return _function_names(node.start) | _function_names(node.end)
    return set()


def _normalized(formula: str) -> str:
    return "".join(formula.split()).upper()


def _has_token(label: str, tokens: tuple[str, ...]) -> bool:
    for token in tokens:
        if any(ord(character) > 127 for character in token):
            if token in label:
                return True
        elif re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", label):
            return True
    return False


def _ratio_label(label: str) -> bool:
    return _has_token(
        label,
        ("%", "PERCENT", "PERCENTAGE", "RATIO", "百分比", "比率", "占比"),
    )


def _columns(headers: dict[int, str], tokens: tuple[str, ...]) -> list[int]:
    return [column for column, value in headers.items() if _has_token(value.upper(), tokens)]


def _role_candidates(model: WorkbookModel, cell: CellKey) -> list[tuple[str, str]]:
    headers = _headers(model, cell)
    _, row, col = _coordinate(cell)
    target = headers.get(col, "").upper()
    if not target or _ratio_label(target):
        return []
    units = _columns(
        headers,
        (
            "UNIT",
            "UNITS",
            "QUANTITY",
            "SEAT",
            "SEATS",
            "COUNT",
            "COUNTS",
            "数量",
            "单位",
            "UNIDAD",
        ),
    )
    prices = _columns(
        headers,
        ("PRICE", "RATE", "单价", "价格", "PRECIO", "TARIFA"),
    )
    result: list[tuple[str, str]] = []
    if _has_token(
        target,
        ("REVENUE", "SALES", "INCOME", "MRR", "RECURRING", "收入", "销售", "INGRESOS", "VENTAS"),
    ) and not _has_token(target, ("NET", "PER SEAT")) and units and prices:
        result.append(
            (
                f"={num_to_col(units[0])}{row}*{num_to_col(prices[0])}{row}",
                "semantic_revenue_product",
            )
        )

    opening = _columns(headers, ("OPENING", "BEGINNING", "期初", "开头"))
    inflow = _columns(headers, ("RECEIVED", "INCOMING", "PURCHASE", "收货", "收到"))
    outflow = _columns(headers, ("SHIPPED", "DELIVERED", "OUTFLOW", "发货", "交付"))
    if _has_token(target, ("CLOSING", "ENDING", "STOCK ON HAND", "期末", "结存")) and opening and inflow and outflow:
        result.append(
            (
                f"={num_to_col(opening[0])}{row}+{num_to_col(inflow[0])}{row}-{num_to_col(outflow[0])}{row}",
                "semantic_closing_reconciliation",
            )
        )

    if _has_token(target, ("AVERAGE", "AVG", "MEAN", "平均", "PROMEDIO")):
        ignored = ("ID", "STUDENT", "ACCOUNT", "SKU", "PERIOD", "DATE", "姓名", "编号")
        value_columns = [
            column
            for column, value in sorted(headers.items())
            if column < col and not _has_token(value.upper(), ignored)
        ]
        if len(value_columns) >= 2:
            result.append(
                (
                    f"=AVERAGE({num_to_col(value_columns[0])}{row}:{num_to_col(value_columns[-1])}{row})",
                    "semantic_average_inputs",
                )
            )

    revenue_cols = _columns(
        headers,
        ("REVENUE", "SALES", "INCOME", "收入", "销售", "INGRESOS", "VENTAS"),
    )
    cost_cols = _columns(headers, ("COST", "EXPENSE", "成本", "费用", "COSTE", "GASTO"))
    if _has_token(
        target,
        ("MARGIN", "PROFIT", "VARIANCE", "DIFFERENCE", "利润", "差异", "MARGEN", "BENEFICIO"),
    ) and revenue_cols and cost_cols:
        result.append(
            (
                f"={num_to_col(revenue_cols[0])}{row}-{num_to_col(cost_cols[0])}{row}",
                "semantic_margin_difference",
            )
        )
    return result


def _role_penalty(model: WorkbookModel, cell: CellKey, formula: str) -> float:
    candidates = _role_candidates(model, cell)
    if not candidates:
        return 0.0
    current = _normalized(formula)
    for candidate, _ in candidates:
        expected = _normalized(candidate)
        if expected == current:
            return 0.0
        # Preserve harmless legal variants such as ``=B*C+0`` without making
        # the semantic role gate accept arbitrary changed formulas.
        neutralized = current
        changed = True
        while changed:
            changed = False
            for suffix in ("+0", "-0", "*1", "/1"):
                if neutralized.endswith(suffix):
                    neutralized = neutralized[: -len(suffix)]
                    changed = True
        if neutralized == expected:
            return 0.0
    return 0.92


def _candidate_pool(
    model: WorkbookModel, cell: CellKey, peers: list[CellKey]
) -> dict[str, tuple[str, str, int]]:
    originals = model.formulas[cell]
    choices: list[tuple[str, str]] = [
        (formula, "small_edit")
        for formula, _ in small_edit_candidates_with_kinds(originals)
    ]
    choices.extend(_role_candidates(model, cell))
    for peer in peers:
        translated = _safe_translate(model.formulas[peer], peer[1], cell[1])
        if translated is not None:
            choices.append((translated, "peer_translation"))
    candidates: dict[str, tuple[str, str, int]] = {}
    for formula, source in choices:
        if _normalized(formula) == _normalized(originals):
            continue
        template = _signature(formula, cell[1])
        cost = 0 if source.startswith("semantic_") else 1
        previous = candidates.get(template)
        if previous is None or cost < previous[2]:
            candidates[template] = (formula, source, cost)
    return candidates


def _contiguous(cells: list[CellKey]) -> bool:
    rows = sorted(_coordinate(cell)[1] for cell in cells)
    return bool(rows) and rows == list(range(rows[0], rows[-1] + 1))


def _anchor_count(
    model: WorkbookModel,
    region: list[CellKey],
    cells: list[CellKey],
    template: str,
) -> int:
    selected = set(cells)
    anchors = 0
    for cell in region:
        if cell in selected:
            continue
        translated = _safe_translate(
            model.formulas[cell], cell[1], cells[0][1]
        )
        if translated is not None and _signature(translated, cells[0][1]) == template:
            anchors += 1
    return anchors


def v5_1_1_development_scores(
    model: WorkbookModel,
    *,
    radius: int = DEFAULT_RADIUS,
    min_template_support: int = MIN_TEMPLATE_SUPPORT,
    min_group_size: int = MIN_GROUP_SIZE,
) -> list[LocalizationResult]:
    signatures = {
        cell: _signature(model.formulas[cell], cell[1]) for cell in model.formula_cells
    }
    by_column: dict[tuple[str, int], list[CellKey]] = defaultdict(list)
    for cell in model.formula_cells:
        sheet, _, col = _coordinate(cell)
        by_column[(sheet, col)].append(cell)
    dominant: dict[tuple[str, int], tuple[str, int]] = {}
    dominant_formula: dict[tuple[str, int], str] = {}
    for key, cells in by_column.items():
        counts = Counter(signatures[cell] for cell in cells)
        dominant[key] = counts.most_common(1)[0]
        dominant_formula[key] = model.formulas[
            next(cell for cell in cells if signatures[cell] == dominant[key][0])
        ]

    records: dict[CellKey, dict[str, object]] = {}
    for cell in model.formula_cells:
        sheet, _, col = _coordinate(cell)
        peers = _same_column_peers(model, cell, radius)
        dominant_signature, support = dominant[(sheet, col)]
        counts = Counter(signatures[peer] for peer in peers)
        ranked = counts.most_common(2)
        peer_total = len(peers)
        peer_dominance = ranked[0][1] / max(1, peer_total) if ranked else 0.0
        second = ranked[1][1] if len(ranked) > 1 else 0
        peer_margin = (ranked[0][1] - second) / max(1, peer_total) if ranked else 0.0
        local_residual = 0.0 if signatures[cell] == dominant_signature else min(
            1.0, 1.0 - support / max(1, len(by_column[(sheet, col)]))
        )
        semantic = _role_penalty(model, cell, model.formulas[cell])
        pool = _candidate_pool(model, cell, peers)
        peer_templates = Counter(
            _signature(translated, cell[1])
            for peer in peers
            if (translated := _safe_translate(model.formulas[peer], peer[1], cell[1]))
            is not None
        )
        try:
            current_functions = _function_names(parse_formula(model.formulas[cell]))
            dominant_functions = _function_names(parse_formula(dominant_formula[(sheet, col)]))
        except ValueError:
            current_functions = set()
            dominant_functions = set()
        function_mismatch = bool(current_functions - dominant_functions)
        best: tuple[str, str, float, str] | None = None
        for template, (formula, source, _) in pool.items():
            peer_support = peer_templates.get(template, 0)
            confidence = peer_support / max(1, len(peers))
            gain = max(0.0, semantic - _role_penalty(model, cell, formula))
            quality = 0.55 * confidence + 0.45 * gain
            if source.startswith("semantic_") and peer_support == 0:
                quality = max(quality, 0.78 if peer_dominance >= MIN_DOMINANCE else 0.0)
            if best is None or quality > best[2]:
                best = (formula, source, quality, template)
        if function_mismatch:
            best = None
        anomaly = min(1.0, max(semantic, 0.55 * semantic + 0.45 * local_residual))
        records[cell] = {
            "semantic": semantic,
            "local_residual": local_residual,
            "anomaly": anomaly,
            "candidate": best,
            "peer_support": peer_templates.get(best[3], 0) if best else 0,
            "dominance": peer_dominance,
            "template_margin": peer_margin,
            "function_mismatch": function_mismatch,
        }

    accepted: dict[CellKey, tuple[str, str, str, int, str]] = {}
    for region in _formula_regions(model.formula_cells):
        suspicious = [
            cell
            for cell in region
            if records[cell]["anomaly"] >= MIN_ANOMALY
            and not records[cell]["function_mismatch"]
        ]
        groups: dict[str, list[CellKey]] = defaultdict(list)
        for cell in suspicious:
            best = records[cell]["candidate"]
            if best is not None:
                groups[str(best[3])].append(cell)
        for template, cells in groups.items():
            if not _contiguous(cells):
                continue
            group_quality = max(float(records[cell]["candidate"][2]) for cell in cells)
            stable = all(
                float(records[cell]["dominance"]) >= MIN_DOMINANCE
                and float(records[cell]["template_margin"]) >= MIN_TEMPLATE_MARGIN
                for cell in cells
            )
            anchors = _anchor_count(model, region, cells, template)
            if len(cells) == 1:
                cell = cells[0]
                if int(records[cell]["peer_support"]) < min_template_support or not stable:
                    continue
            elif not stable and (len(cells) < min_group_size or anchors < 2):
                continue
            if group_quality < MIN_CONFIDENCE:
                continue
            first_sheet, first_row, first_col = _coordinate(region[0])
            last_row = _coordinate(region[-1])[1]
            group_id = (
                f"{first_sheet}!{num_to_col(first_col)}{first_row}:"
                f"{num_to_col(first_col)}{last_row}#{template[:16]}"
            )
            for cell in cells:
                formula, source, _, _ = records[cell]["candidate"]  # type: ignore[misc]
                accepted[cell] = (formula, source, template, len(cells), group_id)

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
            "function_compatibility": "failed"
            if record["function_mismatch"]
            else "passed",
            "template_dominance": float(record["dominance"]),
            "template_margin": float(record["template_margin"]),
            "automatic_edit_applied": False,
            "group_state": "accepted" if candidate else "not_applicable",
            "group_reason": "conservative_role_consensus"
            if candidate
            else "role_function_or_template_gate",
            "group_propagated": int(candidate is not None and candidate[3] >= min_group_size),
            "group_size": candidate[3] if candidate else 0,
            "group_id": candidate[4] if candidate else "",
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


__all__ = [
    "MODEL_VERSION",
    "v5_1_1_development_default_parameters",
    "v5_1_1_development_scores",
]
