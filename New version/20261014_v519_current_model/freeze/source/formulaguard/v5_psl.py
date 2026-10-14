"""V5-PSL: role-conditioned perturbation fingerprints with selective diagnosis.

The source ranking is computed without V4 or R2 scores and without labels.
Repair candidates are explanatory probes for the leading observationally
plausible cells; candidate coverage is not a prerequisite for a complete rank.
"""

from __future__ import annotations

import hashlib
import math
import re
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Callable, Mapping, Sequence

from .a1 import num_to_col, parse_address
from .formula import Binary, Func, Range, Ref, parse_formula, translate_formula
from .localize import LocalizationResult, formula_anomaly_scores, graph_anomaly_scores
from .v5_core import build_candidate_portfolio
from .workbook import CellKey, DependencyGraph, WorkbookModel


MODEL_VERSION = "v5-psl-dev1-rev1"
ARCHITECTURE = "static_anchor_repair_verified_selective_localization"
RANDOM_SEED = 20260830
ABLATIONS = (
    "no_perturbation",
    "no_role_conditioning",
    "no_identifiability_gate",
    "no_downstream_placebo",
)


class DiagnosticState(str, Enum):
    LOCALIZED = "localized"
    REVIEW = "review"
    ABSTAIN_UNIDENTIFIABLE = "abstain_unidentifiable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class PSLConfig:
    scenario_count: int = 12
    perturbation_magnitudes: tuple[float, ...] = (0.02, 0.05, 0.10)
    minimum_valid_scenarios: int = 9
    minimum_formula_coverage: float = 0.80
    minimum_input_roles: int = 1
    matched_controls: int = 12
    candidate_cells: int = 12
    candidate_formulas: int = 2
    explanatory_cells: int = 5
    placebo_controls: int = 12
    minimum_placebo_controls: int = 8
    strong_tail: float = 0.10
    strong_effect: float = 0.20
    strong_stability: float = 0.75
    weak_tail: float = 0.20
    weak_effect: float = 0.10
    weak_stability: float = 0.60
    localization_margin: float = 0.15
    allow_libreoffice_fallback: bool = True
    libreoffice_timeout_seconds: float = 180.0
    random_seed: int = RANDOM_SEED

    @classmethod
    def from_mapping(cls, values: Mapping[str, object] | None) -> "PSLConfig":
        if values is None:
            return cls()
        allowed = set(cls.__dataclass_fields__)
        metadata = {
            "model_version": MODEL_VERSION,
            "architecture": ARCHITECTURE,
            "diagnostic_states": [state.value for state in DiagnosticState],
            "label_inputs": [],
            "filename_features": False,
            "hidden_label_features": False,
            "development_ablations": list(ABLATIONS),
        }
        unknown = set(values) - allowed - set(metadata)
        if unknown:
            raise TypeError(f"Unsupported V5-PSL parameters: {', '.join(sorted(unknown))}")
        for key, expected in metadata.items():
            if key in values and values[key] != expected:
                raise ValueError(f"V5-PSL configuration metadata changed: {key}")
        kwargs = {key: value for key, value in values.items() if key in allowed}
        if "perturbation_magnitudes" in kwargs:
            kwargs["perturbation_magnitudes"] = tuple(float(v) for v in kwargs["perturbation_magnitudes"])  # type: ignore[index]
        config = cls(**kwargs)  # type: ignore[arg-type]
        if config.scenario_count != 12 or config.scenario_count % 2:
            raise ValueError("V5-PSL requires exactly 12 paired perturbation scenarios")
        if config.minimum_valid_scenarios > config.scenario_count:
            raise ValueError("minimum_valid_scenarios exceeds scenario_count")
        if config.explanatory_cells != 5:
            raise ValueError("V5-PSL revision 1 verifies exactly the static Top-5")
        if config.placebo_controls < config.minimum_placebo_controls:
            raise ValueError("placebo_controls is below the minimum evidence count")
        return config


@dataclass(frozen=True)
class EvidenceFamily:
    name: str
    effect: float
    empirical_tail: float
    stability: float
    strength: str
    cells: tuple[CellKey, ...] = ()
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["cells"] = [f"{sheet}!{address}" for sheet, address in self.cells]
        return _stable_payload(payload)  # type: ignore[return-value]


@dataclass(frozen=True)
class SupportReport:
    engine: str
    engine_version: str
    numeric_leaf_cells: int
    input_roles: int
    requested_scenarios: int
    valid_scenarios: int
    formula_coverage: float
    unsupported_formula_cells: tuple[CellKey, ...] = ()
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["unsupported_formula_cells"] = [
            f"{sheet}!{address}" for sheet, address in self.unsupported_formula_cells
        ]
        return _stable_payload(payload)  # type: ignore[return-value]


@dataclass(frozen=True)
class SelectiveDiagnosis:
    model_version: str
    state: DiagnosticState
    ranking: tuple[LocalizationResult, ...]
    review_cells: tuple[CellKey, ...]
    evidence_families: tuple[EvidenceFamily, ...]
    support: SupportReport
    reason_codes: tuple[str, ...]
    provenance: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return _stable_payload({
            "model_version": self.model_version,
            "state": self.state.value,
            "review_cells": [f"{sheet}!{address}" for sheet, address in self.review_cells],
            "evidence_families": [row.as_dict() for row in self.evidence_families],
            "support": self.support.as_dict(),
            "reason_codes": list(self.reason_codes),
            "provenance": dict(self.provenance),
            "ranking": [
                {
                    "rank": rank,
                    "cell": row.cell_label,
                    "score": row.score,
                    "candidate_formula": row.candidate_formula,
                    "evidence": row.evidence,
                }
                for rank, row in enumerate(self.ranking, 1)
            ],
        })  # type: ignore[return-value]


@dataclass(frozen=True)
class PerturbationScenario:
    scenario_id: str
    magnitude: float
    value_overrides: Mapping[CellKey, float | int]


@dataclass(frozen=True)
class ScenarioEvaluation:
    values: Mapping[CellKey, object]
    errors: Mapping[CellKey, str]


@dataclass(frozen=True)
class FormulaRole:
    outer_class: str
    indegree_band: int
    outdegree_band: int
    descendant_band: int
    orientation: str
    boundary: str
    label_token: str
    number_format: str


@dataclass
class CellAssessment:
    cell: CellKey
    families: list[EvidenceFamily]
    static_score: float
    propagation_score: float
    matched_peers: tuple[CellKey, ...]
    candidate_formula: str | None = None
    candidate_detail: dict[str, object] = field(default_factory=dict)

    @property
    def strong_count(self) -> int:
        return sum(row.strength == "strong" for row in self.families)

    @property
    def weak_count(self) -> int:
        return sum(row.strength == "weak" for row in self.families)

    @property
    def median_effect(self) -> float:
        positive = [row.effect for row in self.families if row.strength != "none"]
        return statistics.median(positive) if positive else 0.0

    @property
    def identifiability_index(self) -> float:
        return self.strong_count + 0.5 * self.weak_count + self.median_effect


def v5_psl_default_parameters() -> dict[str, object]:
    config = PSLConfig()
    return {
        "model_version": MODEL_VERSION,
        "architecture": ARCHITECTURE,
        **asdict(config),
        "diagnostic_states": [state.value for state in DiagnosticState],
        "label_inputs": [],
        "filename_features": False,
        "hidden_label_features": False,
        "development_ablations": list(ABLATIONS),
    }


def _stable_metric(value: float) -> float:
    rounded = round(float(value), 12)
    return 0.0 if rounded == 0 else rounded


def _stable_payload(value: object) -> object:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return _stable_metric(value)
    if isinstance(value, Mapping):
        return {str(key): _stable_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable_payload(item) for item in value]
    return value


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _format_class(format_code: str) -> str:
    lowered = re.sub(r'"[^"]*"', "", format_code.lower())
    if re.search(r"(^|[^a-z])(yy|yyyy|dd|mmm|hh|ss)([^a-z]|$)", lowered):
        return "date_time"
    if "%" in lowered:
        return "percentage"
    if any(token in lowered for token in ("$", "€", "£", "¥")):
        return "currency"
    if "." not in lowered and "0" in lowered:
        return "integer"
    return "number"


def _normal_label(value: str) -> str:
    tokens = re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE)
    return "_".join(tokens[:3])[:48]


def _label_context(model: WorkbookModel, key: CellKey) -> str:
    anchor = parse_address(key[1])
    candidates: list[tuple[int, str, str]] = []
    for other, text in model.visible_text_cells.items():
        if other[0] != key[0]:
            continue
        address = parse_address(other[1])
        distance = abs(anchor.row - address.row) + abs(anchor.col - address.col)
        if distance <= 3:
            candidates.append((distance, other[1], _normal_label(text)))
    return min(candidates)[2] if candidates else ""


def _outer_class(formula: str) -> str:
    try:
        node = parse_formula(formula)
    except Exception:
        return "unsupported"
    if isinstance(node, Func) and node.name in {"SUM", "AVERAGE", "MIN", "MAX", "COUNT"}:
        return "aggregate"
    if isinstance(node, Func):
        return "function"
    if isinstance(node, Binary):
        def operand_kind(value: object) -> str:
            if isinstance(value, Ref):
                return "ref"
            if isinstance(value, Range):
                return "range"
            if isinstance(value, Func):
                return "func"
            if isinstance(value, Binary):
                return "binary"
            return type(value).__name__.lower()

        return f"binary:{operand_kind(node.left)}:{operand_kind(node.right)}"
    return type(node).__name__.lower()


def _band(value: int) -> int:
    if value <= 0:
        return 0
    if value == 1:
        return 1
    if value <= 3:
        return 2
    if value <= 8:
        return 3
    return 4


def _orientation(model: WorkbookModel, key: CellKey) -> str:
    address = parse_address(key[1])
    formulas = set(model.formula_cells)
    horizontal = sum(
        (key[0], f"{num_to_col(address.col + delta)}{address.row}") in formulas
        for delta in (-1, 1)
        if address.col + delta >= 1
    )
    vertical = sum(
        (key[0], f"{key[1].rstrip('0123456789')}{address.row + delta}") in formulas
        for delta in (-1, 1)
        if address.row + delta >= 1
    )
    if horizontal and vertical:
        return "two_dimensional"
    if horizontal:
        return "row"
    if vertical:
        return "column"
    return "isolated"


def _formula_roles(model: WorkbookModel, graph: DependencyGraph) -> dict[CellKey, FormulaRole]:
    roles: dict[CellKey, FormulaRole] = {}
    by_sheet: dict[str, list[CellKey]] = defaultdict(list)
    for key in model.formula_cells:
        by_sheet[key[0]].append(key)
    for key in model.formula_cells:
        address = parse_address(key[1])
        sheet_cells = by_sheet[key[0]]
        rows = [parse_address(item[1]).row for item in sheet_cells]
        cols = [parse_address(item[1]).col for item in sheet_cells]
        boundary = "edge" if address.row in {min(rows), max(rows)} or address.col in {min(cols), max(cols)} else "interior"
        roles[key] = FormulaRole(
            outer_class=_outer_class(model.formulas[key]),
            indegree_band=_band(len(graph.precedents.get(key, ()))),
            outdegree_band=_band(len(graph.dependents.get(key, ()))),
            descendant_band=_band(len(graph.descendants(key))),
            orientation=_orientation(model, key),
            boundary=boundary,
            label_token=_label_context(model, key),
            number_format=_format_class(model.number_format(key)),
        )
    return roles


def _role_similarity(left: FormulaRole, right: FormulaRole) -> float:
    score = 0.0
    score += 2.0 if left.outer_class == right.outer_class else 0.0
    score += 1.0 if left.indegree_band == right.indegree_band else 0.0
    score += 1.0 if left.outdegree_band == right.outdegree_band else 0.0
    score += 1.0 if left.descendant_band == right.descendant_band else 0.0
    score += 1.0 if left.orientation == right.orientation else 0.0
    score += 0.5 if left.boundary == right.boundary else 0.0
    score += 0.5 if left.number_format == right.number_format else 0.0
    if left.label_token and left.label_token == right.label_token:
        score += 1.0
    return score


def _distance(left: CellKey, right: CellKey) -> int:
    if left[0] != right[0]:
        return 10_000
    a = parse_address(left[1])
    b = parse_address(right[1])
    return abs(a.row - b.row) + abs(a.col - b.col)


def _matched_formula_peers(
    model: WorkbookModel,
    roles: Mapping[CellKey, FormulaRole],
    key: CellKey,
    limit: int,
) -> tuple[CellKey, ...]:
    scored = []
    for other in model.formula_cells:
        if other == key or not model.is_visible(other):
            continue
        similarity = _role_similarity(roles[key], roles[other])
        if similarity < 4.0:
            continue
        scored.append((-similarity, _distance(key, other), other[0], other[1], other))
    scored.sort()
    return tuple(item[-1] for item in scored[:limit])


def _unconditioned_formula_peers(
    model: WorkbookModel,
    key: CellKey,
    limit: int,
) -> tuple[CellKey, ...]:
    peers = [
        other for other in model.formula_cells
        if other != key and model.is_visible(other)
    ]
    peers.sort(key=lambda other: (_distance(key, other), other[0], other[1]))
    return tuple(peers[:limit])


def _input_role(
    model: WorkbookModel,
    graph: DependencyGraph,
    formula_roles: Mapping[CellKey, FormulaRole],
    key: CellKey,
) -> str:
    dependents = sorted(graph.dependents.get(key, ()))
    role_tokens = sorted({
        f"{formula_roles[item].outer_class}:{formula_roles[item].orientation}:{formula_roles[item].indegree_band}"
        for item in dependents
        if item in formula_roles
    })
    payload = (
        _format_class(model.number_format(key)),
        _label_context(model, key),
        tuple(role_tokens),
        _band(len(dependents)),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()[:20]


def _structure_hash(model: WorkbookModel) -> str:
    digest = hashlib.sha256()
    for key in model.formula_cells:
        digest.update(f"{key[0]}!{key[1]}={model.formulas[key]}\n".encode("utf-8"))
    for key, text in sorted(model.visible_text_cells.items()):
        digest.update(f"label:{key[0]}!{key[1]}={text}\n".encode("utf-8"))
    return digest.hexdigest()


def build_perturbation_scenarios(
    model: WorkbookModel,
    *,
    config: PSLConfig | None = None,
    graph: DependencyGraph | None = None,
    formula_roles: Mapping[CellKey, FormulaRole] | None = None,
) -> tuple[list[PerturbationScenario], dict[str, tuple[CellKey, ...]]]:
    config = config or PSLConfig()
    graph = graph or model.dependency_graph()
    formula_roles = formula_roles or _formula_roles(model, graph)
    grouped: dict[str, list[CellKey]] = defaultdict(list)
    for key, raw in model.cells.items():
        value = _numeric(raw)
        if value is None or key in model.formulas or not model.is_visible(key):
            continue
        if not graph.dependents.get(key) or _format_class(model.number_format(key)) == "date_time":
            continue
        grouped[_input_role(model, graph, formula_roles, key)].append(key)
    role_groups = {role: tuple(sorted(cells)) for role, cells in grouped.items()}
    structure_hash = _structure_hash(model)
    scenarios: list[PerturbationScenario] = []
    pair_count = config.scenario_count // 2
    for pair_index in range(pair_count):
        magnitude = config.perturbation_magnitudes[pair_index % len(config.perturbation_magnitudes)]
        for inverse in (False, True):
            overrides: dict[CellKey, float | int] = {}
            for role, cells in sorted(role_groups.items()):
                role_values = [abs(_numeric(model.cells[cell]) or 0.0) for cell in cells]
                role_scale = statistics.median([value for value in role_values if value > 0]) if any(role_values) else 1.0
                token = f"{config.random_seed}:{structure_hash}:{pair_index}:{role}".encode("utf-8")
                sign = 1 if hashlib.sha256(token).digest()[0] % 2 else -1
                if inverse:
                    sign *= -1
                nonnegative = all((_numeric(model.cells[cell]) or 0.0) >= 0 for cell in cells)
                for cell in cells:
                    original = _numeric(model.cells[cell])
                    if original is None:
                        continue
                    delta = magnitude * max(abs(original), role_scale, 1e-6)
                    changed = original + sign * delta
                    if original > 0:
                        changed = max(changed, max(1e-12, original * 0.01))
                    elif original < 0:
                        changed = min(changed, min(-1e-12, original * 0.01))
                    if nonnegative:
                        changed = max(0.0, changed)
                    if isinstance(model.cells[cell], int) and not isinstance(model.cells[cell], bool):
                        changed = int(round(changed))
                        if changed == model.cells[cell]:
                            changed = int(model.cells[cell]) + sign
                            if nonnegative:
                                changed = max(0, changed)
                    overrides[cell] = changed
            scenario_index = len(scenarios) + 1
            scenarios.append(PerturbationScenario(
                scenario_id=f"p{scenario_index:02d}",
                magnitude=magnitude,
                value_overrides=overrides,
            ))
    return scenarios, role_groups


def _evaluate_scenarios(
    model: WorkbookModel,
    scenarios: Sequence[PerturbationScenario],
    formula_override: Mapping[CellKey, str] | None = None,
) -> list[ScenarioEvaluation]:
    evaluations = []
    for scenario in scenarios:
        values, errors = model.evaluate(formula_override, value_overrides=scenario.value_overrides)
        evaluations.append(ScenarioEvaluation(values, errors))
    return evaluations


def _response_fingerprints(
    model: WorkbookModel,
    base_values: Mapping[CellKey, object],
    base_errors: Mapping[CellKey, str],
    evaluations: Sequence[ScenarioEvaluation],
    scenarios: Sequence[PerturbationScenario],
    graph: DependencyGraph,
) -> dict[CellKey, tuple[float | None, ...]]:
    result: dict[CellKey, tuple[float | None, ...]] = {}
    for key in model.formula_cells:
        base = _numeric(base_values.get(key))
        if base is None or key in base_errors:
            result[key] = tuple(None for _ in evaluations)
            continue
        values: list[float | None] = []
        input_cells = graph.ancestors(key) - set(model.formulas)
        for row, scenario in zip(evaluations, scenarios):
            current = _numeric(row.values.get(key))
            input_change = sum(
                abs(float(changed) - float(model.cells[cell]))
                for cell, changed in scenario.value_overrides.items()
                if cell in input_cells and cell in model.cells and _numeric(model.cells[cell]) is not None
            )
            values.append(
                None
                if current is None or key in row.errors or input_change <= 1e-12
                else (current - base) / input_change
            )
        result[key] = tuple(values)
    return result


def _vector_median(vectors: Sequence[Sequence[float | None]]) -> tuple[float | None, ...]:
    if not vectors:
        return ()
    result: list[float | None] = []
    for index in range(len(vectors[0])):
        values = [float(row[index]) for row in vectors if row[index] is not None]
        result.append(statistics.median(values) if values else None)
    return tuple(result)


def _response_distance(left: Sequence[float | None], right: Sequence[float | None]) -> float:
    values = [abs(float(a) - float(b)) for a, b in zip(left, right) if a is not None and b is not None]
    return statistics.median(values) if values else 0.0


def _directed_response_recovery(
    before: Mapping[CellKey, Sequence[float | None]],
    after: Mapping[CellKey, Sequence[float | None]],
    targets: Sequence[CellKey],
    reference_peers: Mapping[CellKey, Sequence[CellKey]],
) -> tuple[float, float, tuple[CellKey, ...]]:
    """Measure movement toward each target's matched-role response reference."""
    cell_gains: list[float] = []
    scenario_gains: list[float] = []
    supported: list[CellKey] = []
    target_set = set(targets)
    for target in targets:
        original = before.get(target, ())
        changed = after.get(target, ())
        peer_vectors = [
            before[peer]
            for peer in reference_peers.get(target, ())
            if peer not in target_set and peer in before
        ]
        if not original or not changed or len(peer_vectors) < 2:
            continue
        reference = _vector_median(peer_vectors)
        comparable = [
            (float(old), float(new), float(expected))
            for old, new, expected in zip(original, changed, reference)
            if old is not None and new is not None and expected is not None
        ]
        if not comparable:
            continue
        before_distance = statistics.median(
            abs(old - expected) for old, _new, expected in comparable
        )
        after_distance = statistics.median(
            abs(new - expected) for _old, new, expected in comparable
        )
        cell_gains.append(_clamp(
            (before_distance - after_distance) / max(before_distance, 0.05)
        ))
        scenario_gains.extend(
            (abs(old - expected) - abs(new - expected))
            / max(abs(old - expected), 0.05)
            for old, new, expected in comparable
        )
        supported.append(target)
    effect = statistics.fmean(cell_gains) if cell_gains else 0.0
    stability = (
        sum(value > 0 for value in scenario_gains) / len(scenario_gains)
        if scenario_gains else 0.0
    )
    return _clamp(effect), stability, tuple(supported)


def _scenario_stability(vector: Sequence[float | None], reference: Sequence[float | None]) -> float:
    differences = [abs(float(a) - float(b)) for a, b in zip(vector, reference) if a is not None and b is not None]
    if not differences:
        return 0.0
    median = statistics.median(differences)
    threshold = max(0.01, median * 0.50)
    return sum(value >= threshold for value in differences) / len(differences)


def _family_strength(
    *,
    tail: float,
    effect: float,
    stability: float,
    controls: int,
    config: PSLConfig,
    minimum_weak_controls: int = 0,
) -> str:
    tail = _stable_metric(tail)
    effect = _stable_metric(effect)
    stability = _stable_metric(stability)
    if (
        controls >= max(8, minimum_weak_controls)
        and tail <= config.strong_tail
        and effect >= config.strong_effect
        and stability >= config.strong_stability
    ):
        return "strong"
    if (
        controls >= minimum_weak_controls
        and tail <= config.weak_tail
        and effect >= config.weak_effect
        and stability >= config.weak_stability
    ):
        return "weak"
    return "none"


def _response_family(
    name: str,
    key: CellKey,
    peers: Sequence[CellKey],
    fingerprints: Mapping[CellKey, Sequence[float | None]],
    config: PSLConfig,
    *,
    detail: str,
) -> EvidenceFamily:
    peer_vectors = [fingerprints[peer] for peer in peers if peer in fingerprints]
    if len(peer_vectors) < 2:
        return EvidenceFamily(name, 0.0, 1.0, 0.0, "none", tuple(peers), detail)
    reference = _vector_median(peer_vectors)
    observed = _response_distance(fingerprints[key], reference)
    null_distances = []
    for index, peer in enumerate(peers):
        remaining = [fingerprints[item] for offset, item in enumerate(peers) if offset != index and item in fingerprints]
        if not remaining:
            continue
        null_distances.append(_response_distance(fingerprints[peer], _vector_median(remaining)))
    null_center = statistics.median(null_distances) if null_distances else 0.0
    effect = _clamp((observed - null_center) / max(observed, 0.05))
    tail = (1 + sum(value >= observed for value in null_distances)) / (1 + len(null_distances))
    stability = _scenario_stability(fingerprints[key], reference)
    strength = _family_strength(
        tail=tail, effect=effect, stability=stability,
        controls=len(null_distances), config=config,
    )
    return EvidenceFamily(name, effect, tail, stability, strength, tuple(peers), detail)


def _check_cells(model: WorkbookModel) -> set[CellKey]:
    checks: set[CellKey] = set()
    for key in model.formula_cells:
        if not model.is_visible(key):
            continue
        try:
            node = parse_formula(model.formulas[key])
        except Exception:
            continue
        if isinstance(node, Binary) and node.op == "-" and isinstance(node.left, Ref) and isinstance(node.right, Ref):
            checks.add(key)
    return checks


def _normalized_value(values: Mapping[CellKey, object], key: CellKey) -> float | None:
    value = _numeric(values.get(key))
    if value is None:
        return None
    return abs(value) / max(1.0, abs(value))


def _check_family(
    key: CellKey,
    graph: DependencyGraph,
    checks: set[CellKey],
    base: ScenarioEvaluation,
    scenarios: Sequence[ScenarioEvaluation],
    config: PSLConfig,
) -> EvidenceFamily:
    relevant = sorted(graph.descendants(key) & checks)
    if not relevant:
        return EvidenceFamily("internal_check", 0.0, 1.0, 0.0, "none", (), "no_visible_descendant_check")
    observed_values = []
    for row in (base, *scenarios):
        values = [_normalized_value(row.values, item) for item in relevant if item not in row.errors]
        numeric = [value for value in values if value is not None]
        if numeric:
            observed_values.append(statistics.fmean(numeric))
    other_checks = sorted(checks - set(relevant))
    null_values = []
    for item in other_checks:
        values = [_normalized_value(row.values, item) for row in (base, *scenarios) if item not in row.errors]
        numeric = [value for value in values if value is not None]
        if numeric:
            null_values.append(statistics.fmean(numeric))
    observed = statistics.fmean(observed_values) if observed_values else 0.0
    null_center = statistics.median(null_values) if null_values else 0.0
    effect = _clamp((observed - null_center) / max(observed, 0.05))
    tail = (1 + sum(value >= observed for value in null_values)) / (1 + len(null_values))
    stability = sum(value > max(0.01, null_center) for value in observed_values) / max(1, len(observed_values))
    strength = _family_strength(
        tail=tail, effect=effect, stability=stability,
        controls=len(null_values), config=config,
    )
    return EvidenceFamily("internal_check", effect, tail, stability, strength, tuple(relevant), "visible_subtraction_checks")


def _propagation_family(
    key: CellKey,
    graph: DependencyGraph,
    peers: Sequence[CellKey],
    local_effects: Mapping[CellKey, float],
    checks: set[CellKey],
    config: PSLConfig,
) -> EvidenceFamily:
    excluded = checks | set(peers)
    descendants = sorted((graph.descendants(key) - excluded) & set(local_effects))
    if not descendants:
        return EvidenceFamily("downstream_response", 0.0, 1.0, 0.0, "none", (), "no_supported_descendants")

    def score(source: CellKey) -> float:
        rows = graph.descendants(source) - excluded
        weighted = []
        for cell in rows:
            if cell not in local_effects:
                continue
            depth = graph.shortest_path_length(source, cell) or 1
            weighted.append(local_effects[cell] * (0.70 ** max(0, depth - 1)))
        return statistics.fmean(weighted) if weighted else 0.0

    observed = score(key)
    null_values = [score(peer) for peer in peers]
    null_center = statistics.median(null_values) if null_values else 0.0
    effect = _clamp((observed - null_center) / max(observed, 0.05))
    tail = (1 + sum(value >= observed for value in null_values)) / (1 + len(null_values))
    active = [local_effects[cell] for cell in descendants]
    stability = sum(value >= config.weak_effect for value in active) / max(1, len(active))
    strength = _family_strength(
        tail=tail, effect=effect, stability=stability,
        controls=len(null_values), config=config,
    )
    return EvidenceFamily("downstream_response", effect, tail, stability, strength, tuple(descendants), "directed_descendant_response")


def _candidate_probe(
    model: WorkbookModel,
    key: CellKey,
    peers: Sequence[CellKey],
    graph: DependencyGraph,
    checks: set[CellKey],
    scenarios: Sequence[PerturbationScenario],
    base_values: Mapping[CellKey, object],
    base_errors: Mapping[CellKey, str],
    fingerprints: Mapping[CellKey, Sequence[float | None]],
    reference_peers: Mapping[CellKey, Sequence[CellKey]],
    config: PSLConfig,
    evaluate_bundle: Callable[
        [Mapping[CellKey, str] | None],
        tuple[ScenarioEvaluation, list[ScenarioEvaluation]],
    ],
) -> tuple[str | None, dict[str, object], EvidenceFamily | None]:
    try:
        portfolio = build_candidate_portfolio(model, key, candidate_limit=max(6, config.candidate_formulas))
    except Exception as exc:
        return None, {"status": "candidate_generation_failed", "error": type(exc).__name__}, None
    if not portfolio:
        return None, {"status": "candidate_absent"}, None
    reference = _vector_median([fingerprints[peer] for peer in peers if peer in fingerprints])
    original_distance = _response_distance(fingerprints[key], reference) if reference else 0.0
    descendants = sorted(
        (graph.descendants(key) - checks - set(peers)) & set(model.formula_cells)
    )
    best: tuple[
        tuple[float, float, float, float], str, dict[str, object], EvidenceFamily,
    ] | None = None
    for item in portfolio[: config.candidate_formulas]:
        candidate = item.candidate.formula
        try:
            changed_base_evaluation, evaluations = evaluate_bundle({key: candidate})
        except Exception:
            continue
        changed_base = changed_base_evaluation.values
        changed_errors = changed_base_evaluation.errors
        changed_graph = model.dependency_graph({key: candidate})
        changed_fingerprints = _response_fingerprints(
            model, changed_base, changed_errors, evaluations, scenarios, changed_graph,
        )
        repaired_distance = _response_distance(changed_fingerprints[key], reference) if reference else original_distance
        local_gain = _clamp((original_distance - repaired_distance) / max(original_distance, 0.05))
        scenario_gains = []
        for original, repaired, target in zip(fingerprints[key], changed_fingerprints[key], reference):
            if original is None or repaired is None or target is None:
                continue
            scenario_gains.append(abs(original - target) - abs(repaired - target))
        local_stability = sum(value > 0 for value in scenario_gains) / max(1, len(scenario_gains))
        downstream_gain, downstream_stability, supported_descendants = (
            _directed_response_recovery(
                fingerprints, changed_fingerprints, descendants, reference_peers,
            )
        )

        placebo_gains = []
        for control in peers[: config.placebo_controls]:
            try:
                translated = translate_formula(candidate, key[1], control[1])
                parse_formula(translated)
                control_base_evaluation, control_evaluations = evaluate_bundle({control: translated})
                control_base = control_base_evaluation.values
                control_errors = control_base_evaluation.errors
                control_graph = model.dependency_graph({control: translated})
                control_fingerprints = _response_fingerprints(
                    model, control_base, control_errors, control_evaluations,
                    scenarios, control_graph,
                )
                control_reference = _vector_median([
                    fingerprints[peer]
                    for peer in reference_peers.get(control, ())
                    if peer in fingerprints
                ])
                control_before = _response_distance(
                    fingerprints[control], control_reference,
                )
                control_after = _response_distance(
                    control_fingerprints[control], control_reference,
                )
                control_local_gain = _clamp(
                    (control_before - control_after) / max(control_before, 0.05)
                )
                control_descendants = sorted(
                    (graph.descendants(control) - checks - set(reference_peers.get(control, ())))
                    & set(model.formula_cells)
                )
                control_downstream_gain, _control_stability, _control_cells = (
                    _directed_response_recovery(
                        fingerprints,
                        control_fingerprints,
                        control_descendants,
                        reference_peers,
                    )
                )
                placebo_gains.append(math.sqrt(
                    control_local_gain * control_downstream_gain
                ))
            except Exception:
                continue
        effect = math.sqrt(local_gain * downstream_gain)
        stability = min(local_stability, downstream_stability)
        tail = (1 + sum(value >= effect for value in placebo_gains)) / (1 + len(placebo_gains))
        strength = _family_strength(
            tail=tail, effect=effect, stability=stability,
            controls=len(placebo_gains), config=config,
            minimum_weak_controls=config.minimum_placebo_controls,
        )
        family = EvidenceFamily(
            "repair_specificity", effect, tail, stability, strength,
            supported_descendants, "directed_recovery_vs_matched_formula_edits",
        )
        detail = {
            "status": "evaluated",
            "formula": candidate,
            "quality": item.candidate.quality,
            "sources": list(item.candidate.sources),
            "local_response_gain": local_gain,
            "downstream_response_gain": downstream_gain,
            "joint_response_recovery": effect,
            "placebo_controls": len(placebo_gains),
            "placebo_tail": tail,
            "local_stability": local_stability,
            "downstream_stability": downstream_stability,
            "joint_stability": stability,
            "supported_descendants": len(supported_descendants),
        }
        strength_rank = {"none": 0.0, "weak": 1.0, "strong": 2.0}
        ordering = (
            strength_rank[strength],
            _stable_metric(effect),
            -_stable_metric(tail),
            _stable_metric(item.candidate.quality),
        )
        if best is None or ordering > best[0]:
            best = (ordering, candidate, detail, family)
    if best is None:
        return None, {"status": "candidate_unevaluable"}, None
    return best[1], best[2], best[3]


def _fallback_static_scores(model: WorkbookModel) -> dict[CellKey, float]:
    try:
        formula = formula_anomaly_scores(model)
    except Exception:
        formula = {key: 0.0 for key in model.formula_cells}
    try:
        graph = graph_anomaly_scores(model)
    except Exception:
        graph = {key: 0.0 for key in model.formula_cells}
    return {
        key: 0.60 * float(formula.get(key, 0.0)) + 0.40 * float(graph.get(key, 0.0))
        for key in model.formula_cells
    }


def _no_perturbation_diagnosis(
    model: WorkbookModel,
    config: PSLConfig,
    input_roles: Mapping[str, tuple[CellKey, ...]],
    started: float,
) -> SelectiveDiagnosis:
    _values, errors = model.evaluate()
    formula_set = set(model.formula_cells)
    unsupported = tuple(sorted(set(errors) & formula_set))
    coverage = 1.0 - len(unsupported) / max(1, len(formula_set))
    static_scores = _fallback_static_scores(model)
    ordered = sorted(
        model.formula_cells,
        key=lambda key: (-_stable_metric(static_scores.get(key, 0.0)), key),
    )
    ranking = tuple(
        LocalizationResult(
            cell=key,
            score=1.0 - (rank - 1) / max(1, len(ordered)),
            evidence={
                "model_version": MODEL_VERSION,
                "ablation": "no_perturbation",
                "ranking_basis": "static_formula_graph_anchor",
                "static_fallback_score": static_scores.get(key, 0.0),
                "strong_evidence_families": 0,
                "weak_evidence_families": 0,
                "repair_verified": False,
                "repair_strength": "none",
                "families": [],
            },
        )
        for rank, key in enumerate(ordered, 1)
    )
    reasons = []
    if not ordered:
        reasons.append("no_formula_cells")
    if coverage < config.minimum_formula_coverage:
        reasons.append("insufficient_formula_evaluation_coverage")
    state = DiagnosticState.UNSUPPORTED if reasons else DiagnosticState.REVIEW
    review_cells = tuple(ordered[:5]) if state == DiagnosticState.REVIEW else ()
    support = SupportReport(
        engine="static_ablation",
        engine_version="formulaguard-static-v1",
        numeric_leaf_cells=sum(len(cells) for cells in input_roles.values()),
        input_roles=len(input_roles),
        requested_scenarios=0,
        valid_scenarios=0,
        formula_coverage=coverage,
        unsupported_formula_cells=unsupported,
        reasons=tuple(reasons),
    )
    return SelectiveDiagnosis(
        model_version=MODEL_VERSION,
        state=state,
        ranking=ranking,
        review_cells=review_cells,
        evidence_families=(),
        support=support,
        reason_codes=tuple(reasons or ["ablation_fixed_top5_without_perturbation"]),
        provenance={
            "structure_sha256": _structure_hash(model),
            "parameters": asdict(config),
            "ablation": "no_perturbation",
            "labels_read": [],
            "filename_used_as_feature": False,
            "hidden_labels_used": False,
            "elapsed_seconds": time.perf_counter() - started,
        },
    )


def diagnose_v5_psl(
    model: WorkbookModel,
    *,
    config: Mapping[str, object] | PSLConfig | None = None,
    ablation: str | None = None,
) -> SelectiveDiagnosis:
    started = time.perf_counter()
    resolved = config if isinstance(config, PSLConfig) else PSLConfig.from_mapping(config)
    if ablation is not None and ablation not in ABLATIONS:
        raise ValueError(f"Unknown V5-PSL ablation: {ablation}")
    graph = model.dependency_graph()
    roles = _formula_roles(model, graph)
    scenarios, input_roles = build_perturbation_scenarios(
        model, config=resolved, graph=graph, formula_roles=roles,
    )
    if ablation == "no_perturbation":
        return _no_perturbation_diagnosis(model, resolved, input_roles, started)
    formula_set = set(model.formula_cells)

    def internal_bundle(
        formula_overrides: Mapping[CellKey, str] | None,
    ) -> tuple[ScenarioEvaluation, list[ScenarioEvaluation]]:
        values, errors = model.evaluate(formula_overrides)
        return ScenarioEvaluation(values, errors), _evaluate_scenarios(model, scenarios, formula_overrides)

    base_evaluation, evaluations = internal_bundle(None)
    base_values, base_errors = base_evaluation.values, base_evaluation.errors

    def scenario_coverage(rows: Sequence[ScenarioEvaluation]) -> tuple[int, float]:
        coverages = [
            1.0 - len(set(row.errors) & formula_set) / max(1, len(formula_set))
            for row in rows
        ]
        valid = sum(value >= resolved.minimum_formula_coverage for value in coverages)
        return valid, statistics.fmean(coverages) if coverages else 0.0

    valid_scenarios, formula_coverage = scenario_coverage(evaluations)
    evaluate_bundle = internal_bundle
    engine_name = "internal"
    engine_version = "formulaguard-evaluator-v1"
    office_backend = None
    fallback_error = ""
    needs_fallback = (
        valid_scenarios < resolved.minimum_valid_scenarios
        or formula_coverage < resolved.minimum_formula_coverage
    )
    if needs_fallback and resolved.allow_libreoffice_fallback:
        try:
            from .libreoffice import LibreOfficeEvaluator

            office_backend = LibreOfficeEvaluator(
                model, timeout_seconds=resolved.libreoffice_timeout_seconds,
            )

            def office_bundle(
                formula_overrides: Mapping[CellKey, str] | None,
            ) -> tuple[ScenarioEvaluation, list[ScenarioEvaluation]]:
                base, rows = office_backend.evaluate(model, scenarios, formula_overrides)
                return (
                    ScenarioEvaluation(base.values, base.errors),
                    [ScenarioEvaluation(row.values, row.errors) for row in rows],
                )

            office_base, office_rows = office_bundle(None)
            office_valid, office_coverage = scenario_coverage(office_rows)
            if (office_valid, office_coverage) > (valid_scenarios, formula_coverage):
                base_evaluation, evaluations = office_base, office_rows
                base_values, base_errors = base_evaluation.values, base_evaluation.errors
                valid_scenarios, formula_coverage = office_valid, office_coverage
                evaluate_bundle = office_bundle
                engine_name = "libreoffice"
                engine_version = office_backend.engine_version
            else:
                office_backend.close()
                office_backend = None
        except Exception as exc:
            fallback_error = f"{type(exc).__name__}:{exc}"
            if office_backend is not None:
                office_backend.close()
                office_backend = None

    fingerprints = _response_fingerprints(
        model, base_values, base_errors, evaluations, scenarios, graph,
    )
    unsupported = tuple(sorted({key for row in evaluations for key in row.errors if key in formula_set} | (set(base_errors) & formula_set)))
    static_scores = _fallback_static_scores(model)
    checks = _check_cells(model)
    if ablation == "no_role_conditioning":
        peers_by_cell = {
            key: tuple(
                peer for peer in _unconditioned_formula_peers(
                    model, key, resolved.matched_controls,
                )
                if peer not in checks
            )
            for key in model.formula_cells
        }
    else:
        peers_by_cell = {
            key: tuple(
                peer for peer in _matched_formula_peers(
                    model, roles, key, resolved.matched_controls,
                )
                if peer not in checks
            )
            for key in model.formula_cells
        }

    local_families: dict[CellKey, EvidenceFamily] = {}
    block_families: dict[CellKey, EvidenceFamily] = {}
    for key in model.formula_cells:
        peers = peers_by_cell[key]
        local = tuple(peer for peer in peers if _distance(key, peer) <= 5)
        if len(local) < 2:
            local = peers[: min(len(peers), 8)]
        far = tuple(peer for peer in peers if peer not in local and _distance(key, peer) > 5)
        local_families[key] = _response_family(
            "local_role_response", key, local, fingerprints, resolved,
            detail="matched_local_formula_roles",
        )
        block_families[key] = _response_family(
            "independent_block_replication", key, far, fingerprints, resolved,
            detail="distant_or_cross_sheet_formula_roles",
        )
    local_effects = {key: row.effect for key, row in local_families.items()}

    assessments: dict[CellKey, CellAssessment] = {}
    base_evaluation = ScenarioEvaluation(base_values, base_errors)
    for key in model.formula_cells:
        check_family = _check_family(key, graph, checks, base_evaluation, evaluations, resolved)
        propagation = _propagation_family(
            key, graph, peers_by_cell[key], local_effects, checks, resolved,
        )
        families = [local_families[key], block_families[key], check_family, propagation]
        assessments[key] = CellAssessment(
            cell=key,
            families=families,
            static_score=static_scores.get(key, 0.0),
            propagation_score=propagation.effect,
            matched_peers=peers_by_cell[key],
        )

    ordered = sorted(assessments.values(), key=lambda row: (
        -_stable_metric(row.static_score),
        row.cell,
    ))
    for assessment in ordered[: resolved.explanatory_cells]:
        if ablation == "no_downstream_placebo":
            assessment.candidate_detail = {"status": "ablation_no_downstream_placebo"}
            continue
        candidate, detail, family = _candidate_probe(
            model, assessment.cell, assessment.matched_peers, graph, checks,
            scenarios, base_values, base_errors, fingerprints, peers_by_cell, resolved,
            evaluate_bundle,
        )
        assessment.candidate_formula = candidate
        assessment.candidate_detail = detail
        if family is not None:
            assessment.families.append(family)

    def repair_family(assessment: CellAssessment) -> EvidenceFamily | None:
        return next(
            (family for family in assessment.families if family.name == "repair_specificity"),
            None,
        )

    ranking: list[LocalizationResult] = []
    total = max(1, len(ordered))
    for rank, assessment in enumerate(ordered, 1):
        score = 1.0 - (rank - 1) / total
        repair = repair_family(assessment)
        ranking.append(LocalizationResult(
            cell=assessment.cell,
            score=score,
            candidate_formula=assessment.candidate_formula,
            evidence={
                "model_version": MODEL_VERSION,
                "base_ranking_is_candidate_independent": True,
                "ranking_basis": "static_formula_graph_anchor",
                "strong_evidence_families": assessment.strong_count,
                "weak_evidence_families": assessment.weak_count,
                "median_effect": assessment.median_effect,
                "identifiability_index": assessment.identifiability_index,
                "static_fallback_score": assessment.static_score,
                "propagation_response": assessment.propagation_score,
                "matched_role_controls": len(assessment.matched_peers),
                "repair_verified": bool(
                    repair is not None and repair.strength in {"weak", "strong"}
                ),
                "repair_strength": repair.strength if repair is not None else "none",
                "families": [row.as_dict() for row in assessment.families],
                "candidate_probe": assessment.candidate_detail,
            },
        ))

    support_reasons = []
    if len(input_roles) < resolved.minimum_input_roles:
        support_reasons.append("insufficient_perturbable_input_roles")
    if valid_scenarios < resolved.minimum_valid_scenarios:
        support_reasons.append("insufficient_valid_perturbation_scenarios")
    if formula_coverage < resolved.minimum_formula_coverage:
        support_reasons.append("insufficient_formula_evaluation_coverage")
    if fallback_error:
        support_reasons.append("libreoffice_fallback_failed")
    support = SupportReport(
        engine=engine_name,
        engine_version=engine_version,
        numeric_leaf_cells=sum(len(cells) for cells in input_roles.values()),
        input_roles=len(input_roles),
        requested_scenarios=len(scenarios),
        valid_scenarios=valid_scenarios,
        formula_coverage=formula_coverage,
        unsupported_formula_cells=unsupported,
        reasons=tuple(support_reasons),
    )

    if office_backend is not None:
        office_backend.close()

    top = ordered[0] if ordered else None
    second = ordered[1] if len(ordered) > 1 else None
    margin = 1.0 if top and second is None else _stable_metric(
        top.static_score - second.static_score if top and second else 0.0
    )
    verified = [
        (assessment, family)
        for assessment in ordered[: resolved.explanatory_cells]
        if (family := repair_family(assessment)) is not None
        and family.strength in {"weak", "strong"}
    ]
    if support_reasons or top is None:
        state = DiagnosticState.UNSUPPORTED
        reason_codes = tuple(support_reasons or ["no_formula_cells"])
        review_cells: tuple[CellKey, ...] = ()
    elif ablation == "no_identifiability_gate":
        state = DiagnosticState.REVIEW
        reason_codes = ("ablation_fixed_top5_without_identifiability_gate",)
        review_cells = tuple(row.cell for row in ordered[:5])
    elif (
        len(verified) == 1
        and verified[0][0].cell == top.cell
        and (
            verified[0][1].strength == "strong"
            or margin >= resolved.localization_margin
        )
    ):
        state = DiagnosticState.LOCALIZED
        reason_codes = (
            "unique_verified_static_leader",
            "strong_repair_specificity"
            if verified[0][1].strength == "strong"
            else "weak_repair_with_static_margin",
        )
        review_cells = (top.cell,)
    elif verified:
        state = DiagnosticState.REVIEW
        reason_codes = ("verified_repair_requires_bounded_review",)
        review_cells = tuple(row.cell for row in ordered[:5])
    else:
        state = DiagnosticState.ABSTAIN_UNIDENTIFIABLE
        reason_codes = ("no_verified_repair_in_static_top5",)
        review_cells = ()

    return SelectiveDiagnosis(
        model_version=MODEL_VERSION,
        state=state,
        ranking=tuple(ranking),
        review_cells=review_cells,
        evidence_families=tuple(top.families if top else ()),
        support=support,
        reason_codes=reason_codes,
        provenance={
            "structure_sha256": _structure_hash(model),
            "parameters": asdict(resolved),
            "ablation": ablation,
            "labels_read": [],
            "filename_used_as_feature": False,
            "hidden_labels_used": False,
            "elapsed_seconds": time.perf_counter() - started,
        },
    )


def v5_psl_scores(
    model: WorkbookModel,
    *,
    config: Mapping[str, object] | PSLConfig | None = None,
    ablation: str | None = None,
) -> list[LocalizationResult]:
    return list(diagnose_v5_psl(model, config=config, ablation=ablation).ranking)


__all__ = [
    "ABLATIONS",
    "DiagnosticState",
    "EvidenceFamily",
    "PSLConfig",
    "SelectiveDiagnosis",
    "SupportReport",
    "build_perturbation_scenarios",
    "diagnose_v5_psl",
    "v5_psl_default_parameters",
    "v5_psl_scores",
]
