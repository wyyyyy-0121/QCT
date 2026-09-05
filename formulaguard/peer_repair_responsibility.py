"""Label-free output-coupled responsibility of one fixed Peer repair."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

from .a1 import parse_address
from .localize import (
    _energy,
    _v4_bounded_change,
    _v4_local_energy,
    _v4_scope_weights,
)
from .model_discovery import validate_label_free_output
from .peer_repair_closure import (
    FORBIDDEN_OUTPUT_FIELDS,
    REVIEW_BUDGET,
    select_peer_candidate,
)
from .workbook import CellKey, WorkbookModel

PROTOCOL = "formulaguard_peer_repair_responsibility_v1"
MODEL_VERSION = "peer-repair-output-responsibility-label-free-v1"
ACTION_RULE = "positive_exact_delta_and_changed_visible_sink_without_new_errors"
_CELL_LABEL = re.compile(r"(?:^|[^A-Za-z0-9_])[A-Za-z]{1,4}[1-9][0-9]*(?:$|[^A-Za-z0-9_])")


def _round(value: float) -> float:
    return round(float(value), 12)


def _cell_key(label: str, model: WorkbookModel) -> CellKey:
    if "!" not in label:
        raise ValueError("peer candidate is not a sheet-qualified cell")
    key = tuple(label.rsplit("!", 1))
    if key not in model.formulas:
        raise ValueError("peer candidate is absent from the workbook formula inventory")
    return key  # type: ignore[return-value]


def _record_map(audit: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    records = audit.get("records")
    if not isinstance(records, list):
        raise ValueError("peer audit records are malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    result: dict[str, Mapping[str, object]] = {}
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("peer audit record is malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        label = str(row.get("cell", ""))
        if not label or label in result:
            raise ValueError("peer audit contains an empty or duplicate cell")
        result[label] = row
    return result


def _values_differ(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left != right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if not math.isfinite(float(left)) or not math.isfinite(float(right)):
            return left != right
        return not math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    return left != right


def _key_output(model: WorkbookModel) -> CellKey | None:
    graph = model.dependency_graph()
    formula_set = set(model.formula_cells)
    visible_sinks = [
        cell for cell in graph.sinks(model.formula_cells)
        if model.is_visible(cell)
    ]
    if not visible_sinks:
        return None

    def key(cell: CellKey) -> tuple[int, str, int, int]:
        address = parse_address(cell[1])
        cone = (graph.ancestors(cell) | {cell}) & formula_set
        return len(cone), cell[0], address.row, address.col

    return max(visible_sinks, key=key)


def _sensitive_errors(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            if name in FORBIDDEN_OUTPUT_FIELDS:
                errors.append(f"forbidden field {path}.{name}")
            errors.extend(_sensitive_errors(child, f"{path}.{name}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_sensitive_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if value.startswith("="):
            errors.append(f"raw formula text at {path}")
        if "!" in value and _CELL_LABEL.search(value.rsplit("!", 1)[-1]):
            errors.append(f"cell label at {path}")
    return errors


def probe_repair_responsibility(
    model: WorkbookModel,
    v4_ranking: Sequence[str],
    source_audit: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate whether the fixed Peer repair has observable output responsibility."""

    audit_errors = validate_label_free_output(source_audit)
    if audit_errors:
        raise ValueError(f"source peer audit is invalid: {'; '.join(audit_errors)}")
    v4 = tuple(str(value) for value in v4_ranking)
    records = _record_map(source_audit)
    candidate, reason = select_peer_candidate(v4, source_audit)
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "model_version": MODEL_VERSION,
        "action_rule": ACTION_RULE,
        "review_budget": REVIEW_BUDGET,
        "candidate_selected": candidate is not None,
        "selection_reason": reason,
        "repair_hypothesis_available": False,
        "responsibility_evaluated": False,
        "responsibility": None,
        "label_inputs": [],
        "protected_data_inputs": [],
    }
    if candidate is None:
        return payload
    if candidate not in records:
        raise ValueError("selected peer candidate has no audit record")
    candidate_rank = v4.index(candidate) + 1
    payload["candidate_v4_rank"] = candidate_rank
    payload["candidate_peer_rank"] = 1
    hypotheses = records[candidate].get("repair_hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("selected peer repair hypotheses are malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    if not hypotheses:
        payload["selection_reason"] = "peer_top1_has_no_repair_hypothesis"
        return payload
    first = hypotheses[0]
    if not isinstance(first, Mapping):
        raise ValueError("first peer repair hypothesis is malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    repair_formula = first.get("formula")
    if not isinstance(repair_formula, str) or not repair_formula.startswith("="):
        raise ValueError("first peer repair hypothesis has no valid formula")
    cell = _cell_key(candidate, model)
    if repair_formula == model.formulas[cell]:
        raise ValueError("peer repair hypothesis does not change the formula")
    overrides = {cell: repair_formula}
    graph = model.dependency_graph()
    formula_set = set(model.formula_cells)
    descendants = graph.descendants(cell) & formula_set
    sinks = set(graph.sinks(model.formula_cells))
    visible_sinks = {sink for sink in sinks if model.is_visible(sink)}
    reachable_sinks = descendants & visible_sinks

    base_global, _, base_maps = _energy(model, include_maps=True)
    repaired_global, _, repaired_maps = _energy(model, overrides, include_maps=True)
    scope_weights = _v4_scope_weights(model, graph, cell)
    local_before, _ = _v4_local_energy(base_maps, scope_weights)
    local_after, _ = _v4_local_energy(repaired_maps, scope_weights)
    local_gain, local_harm = _v4_bounded_change(local_before, local_after)
    _, global_harm = _v4_bounded_change(base_global, repaired_global)
    side_effect = max(local_harm, global_harm)
    exact_delta = local_gain - 0.50 * side_effect

    base_values, base_errors = model.evaluate()
    repaired_values, repaired_errors = model.evaluate(overrides)
    comparable_descendants = {
        key for key in descendants
        if key not in base_errors and key not in repaired_errors
    }
    changed_descendants = {
        key for key in comparable_descendants
        if _values_differ(base_values.get(key), repaired_values.get(key))
    }
    comparable_sinks = reachable_sinks & comparable_descendants
    changed_sinks = reachable_sinks & changed_descendants
    key_output = _key_output(model)
    key_output_reachable = key_output is not None and key_output in descendants
    key_output_comparable = bool(
        key_output_reachable
        and key_output not in base_errors
        and key_output not in repaired_errors
    )
    key_output_changed = bool(
        key_output_comparable
        and _values_differ(base_values.get(key_output), repaired_values.get(key_output))
    )
    new_errors = set(repaired_errors) - set(base_errors)
    resolved_errors = set(base_errors) - set(repaired_errors)
    responsibility_pass = bool(
        exact_delta > 0.0
        and changed_sinks
        and not new_errors
    )
    payload.update({
        "repair_hypothesis_available": True,
        "responsibility_evaluated": True,
        "responsibility": {
            "scope_formula_count": len(scope_weights),
            "local_energy_before": _round(local_before),
            "local_energy_after": _round(local_after),
            "local_gain": _round(local_gain),
            "local_harm": _round(local_harm),
            "global_energy_before": _round(base_global),
            "global_energy_after": _round(repaired_global),
            "global_harm": _round(global_harm),
            "side_effect": _round(side_effect),
            "exact_repair_delta": _round(exact_delta),
            "positive_exact_repair_delta": exact_delta > 0.0,
            "downstream_formula_count": len(descendants),
            "comparable_downstream_formula_count": len(comparable_descendants),
            "changed_downstream_formula_count": len(changed_descendants),
            "visible_sink_count": len(visible_sinks),
            "reachable_visible_sink_count": len(reachable_sinks),
            "comparable_reachable_visible_sink_count": len(comparable_sinks),
            "changed_reachable_visible_sink_count": len(changed_sinks),
            "changed_reachable_visible_sink": bool(changed_sinks),
            "key_output_available": key_output is not None,
            "key_output_reachable": key_output_reachable,
            "key_output_comparable": key_output_comparable,
            "key_output_changed": key_output_changed,
            "baseline_evaluation_error_count": len(base_errors),
            "repaired_evaluation_error_count": len(repaired_errors),
            "new_evaluation_error_count": len(new_errors),
            "resolved_evaluation_error_count": len(resolved_errors),
            "no_new_evaluation_errors": not new_errors,
            "responsibility_pass": responsibility_pass,
        },
    })
    errors = validate_responsibility_output(payload)
    if errors:
        raise ValueError(f"repair-responsibility output is invalid: {'; '.join(errors)}")
    return payload


def validate_responsibility_output(payload: Mapping[str, object]) -> list[str]:
    """Validate the data and decision boundary of one responsibility probe."""

    errors: list[str] = []
    if payload.get("protocol") != PROTOCOL:
        errors.append("unexpected repair-responsibility protocol")
    if payload.get("model_version") != MODEL_VERSION:
        errors.append("unexpected repair-responsibility model version")
    if payload.get("action_rule") != ACTION_RULE:
        errors.append("unexpected repair-responsibility action rule")
    if payload.get("review_budget") != REVIEW_BUDGET:
        errors.append("unexpected repair-responsibility review budget")
    if payload.get("label_inputs") != []:
        errors.append("repair-responsibility label inputs are not empty")
    if payload.get("protected_data_inputs") != []:
        errors.append("repair-responsibility protected inputs are not empty")
    selected = payload.get("candidate_selected") is True
    evaluated = payload.get("responsibility_evaluated") is True
    responsibility = payload.get("responsibility")
    if evaluated and not selected:
        errors.append("responsibility evaluated without a selected candidate")
    if evaluated and not isinstance(responsibility, Mapping):
        errors.append("evaluated responsibility metrics are missing")
    if not evaluated and responsibility is not None:
        errors.append("unevaluated responsibility has metrics")
    if isinstance(responsibility, Mapping):
        expected_pass = bool(
            responsibility.get("positive_exact_repair_delta") is True
            and responsibility.get("changed_reachable_visible_sink") is True
            and responsibility.get("no_new_evaluation_errors") is True
        )
        if responsibility.get("responsibility_pass") is not expected_pass:
            errors.append("responsibility pass flag differs from the fixed rule")
    errors.extend(_sensitive_errors(payload))
    return errors


__all__ = [
    "ACTION_RULE",
    "MODEL_VERSION",
    "PROTOCOL",
    "probe_repair_responsibility",
    "validate_responsibility_output",
]
