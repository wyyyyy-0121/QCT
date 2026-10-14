"""Label-free repair hypotheses from independent AST and peer sources.

The pool is deliberately not an error detector.  Its entries are possible
replacement formulas and auditable provenance only; candidate availability
must never be interpreted as evidence that the observed formula is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from .a1 import num_to_col, parse_address
from .counterfactual_candidates import (
    CounterfactualCandidate,
    EditWitness,
    generate_counterfactual_candidates,
)
from .formula import (
    FormulaSyntaxError,
    Node,
    Range,
    Ref,
    iter_refs,
    parse_formula,
    render,
    translate_formula,
)
from .workbook import CellKey, DependencyGraph, WorkbookModel

DEFAULT_AST_BUDGET = 24
DEFAULT_PEER_BUDGET = 8
DEFAULT_PEER_RADIUS = 8
MINIMUM_PEER_VOTES = 2
MAX_EXCEL_ROW = 1_048_576
MAX_EXCEL_COLUMN = 16_384

AST_SOURCE = "ast_edit"
PEER_SOURCE = "peer_translation"


@dataclass(frozen=True)
class CandidatePoolConfig:
    """Independent source quotas and a bounded observed peer neighborhood."""

    ast_budget: int = DEFAULT_AST_BUDGET
    peer_budget: int = DEFAULT_PEER_BUDGET
    peer_radius: int = DEFAULT_PEER_RADIUS
    minimum_peer_votes: int = MINIMUM_PEER_VOTES

    def validate(self) -> None:
        for name in ("ast_budget", "peer_budget"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if isinstance(self.peer_radius, bool) or not isinstance(self.peer_radius, int):
            raise TypeError("peer_radius must be an integer")
        if self.peer_radius < 1:
            raise ValueError("peer_radius must be positive")
        if (
            isinstance(self.minimum_peer_votes, bool)
            or not isinstance(self.minimum_peer_votes, int)
        ):
            raise TypeError("minimum_peer_votes must be an integer")
        if self.minimum_peer_votes < MINIMUM_PEER_VOTES:
            raise ValueError("minimum_peer_votes must be at least two")


@dataclass(frozen=True)
class AstCandidateProvenance:
    """The exact bounded AST edit that produced a pool entry."""

    generated_formula: str
    edit_kind: str
    witness: EditWitness


@dataclass(frozen=True)
class PeerTranslationVote:
    """One dependency-independent peer vote before consensus aggregation."""

    peer: CellKey
    axis: str
    direction: str
    distance: int
    source_formula: str
    translated_formula: str


@dataclass(frozen=True)
class PeerTranslationCandidate:
    formula: str
    canonical_key: str
    votes: tuple[PeerTranslationVote, ...]


@dataclass(frozen=True)
class CandidatePoolEntry:
    """One hypothesis with source-separated provenance and no error score."""

    formula: str
    canonical_key: str
    ast_provenance: tuple[AstCandidateProvenance, ...] = ()
    peer_votes: tuple[PeerTranslationVote, ...] = ()

    @property
    def sources(self) -> tuple[str, ...]:
        sources: list[str] = []
        if self.ast_provenance:
            sources.append(AST_SOURCE)
        if self.peer_votes:
            sources.append(PEER_SOURCE)
        return tuple(sources)


@dataclass(frozen=True)
class CandidatePoolAudit:
    """Selection facts needed to reproduce source eligibility and quotas."""

    source_budgets: tuple[tuple[str, int], ...]
    peer_radius: int
    minimum_peer_votes: int
    ast_selected: int
    peer_consensus_available: int
    peer_selected: int
    dependency_excluded_peers: tuple[CellKey, ...]


@dataclass(frozen=True)
class CandidatePool:
    target: CellKey
    observed_formula_key: str
    candidates: tuple[CandidatePoolEntry, ...]
    audit: CandidatePoolAudit


@dataclass(frozen=True)
class _PeerGeneration:
    candidates: tuple[PeerTranslationCandidate, ...]
    dependency_excluded_peers: tuple[CellKey, ...]


@dataclass
class _MergedCandidate:
    formula: str
    ast_provenance: list[AstCandidateProvenance]
    peer_votes: list[PeerTranslationVote]


def _canonical_formula(formula: str) -> tuple[str, str]:
    """Return the parser-rendered formula and its AST-derived canonical key."""

    node = parse_formula(formula)
    rendered = "=" + render(node)
    # ``render`` removes insignificant formula whitespace and emits one stable
    # spelling for parentheses and sheet quoting.  Do not call
    # ``normalized_formula`` here: its global whitespace removal would also
    # erase meaningful spaces inside quoted worksheet names.
    return rendered, rendered.upper()


def canonical_formula_key(formula: str) -> str:
    """Canonical key that removes redundant textual parentheses via the AST."""

    return _canonical_formula(formula)[1]


def _known_sheets(model: WorkbookModel) -> set[str]:
    return (
        set(model.sheet_visibility)
        | {cell[0] for cell in model.cells}
        | {cell[0] for cell in model.formulas}
    )


def _address_in_grid(ref: Ref) -> bool:
    return (
        1 <= ref.address.row <= MAX_EXCEL_ROW
        and 1 <= ref.address.col <= MAX_EXCEL_COLUMN
    )


def _translation_stays_in_grid(
    node: Node,
    source_address: str,
    target_address: str,
) -> bool:
    source = parse_address(source_address)
    target = parse_address(target_address)
    row_delta = target.row - source.row
    column_delta = target.col - source.col

    def valid(ref: Ref) -> bool:
        if not _address_in_grid(ref):
            return False
        row = ref.address.row if ref.address.row_abs else ref.address.row + row_delta
        col = ref.address.col if ref.address.col_abs else ref.address.col + column_delta
        return 1 <= row <= MAX_EXCEL_ROW and 1 <= col <= MAX_EXCEL_COLUMN

    for item in iter_refs(node):
        if isinstance(item, Ref):
            if not valid(item):
                return False
        elif not valid(item.start) or not valid(item.end):
            return False
    return True


def _range_sheet(item: Range, current_sheet: str) -> str | None:
    start_sheet = item.start.sheet
    end_sheet = item.end.sheet
    if start_sheet is not None and end_sheet is not None and start_sheet != end_sheet:
        return None
    return start_sheet or end_sheet or current_sheet


def _range_contains(item: Range, sheet: str, key: CellKey) -> bool:
    if key[0] != sheet:
        return False
    address = parse_address(key[1])
    min_row, max_row = sorted((item.start.address.row, item.end.address.row))
    min_col, max_col = sorted((item.start.address.col, item.end.address.col))
    return min_row <= address.row <= max_row and min_col <= address.col <= max_col


def _references_are_valid(
    node: Node,
    current_sheet: str,
    known_sheets: set[str],
    cycle_forbidden: set[CellKey],
) -> bool:
    for item in iter_refs(node):
        if isinstance(item, Ref):
            if not _address_in_grid(item):
                return False
            sheet = item.sheet or current_sheet
            if sheet not in known_sheets:
                return False
            key = (sheet, item.address.a1.replace("$", ""))
            if key in cycle_forbidden:
                return False
            continue

        if not _address_in_grid(item.start) or not _address_in_grid(item.end):
            return False
        sheet = _range_sheet(item, current_sheet)
        if sheet is None or sheet not in known_sheets:
            return False
        if any(_range_contains(item, sheet, key) for key in cycle_forbidden):
            return False
    return True


def _cell_sort(key: CellKey) -> tuple[str, int, int, str]:
    address = parse_address(key[1])
    return key[0], address.row, address.col, key[1]


def _vote_sort(vote: PeerTranslationVote) -> tuple[object, ...]:
    axis_order = {"row": 0, "column": 1}
    direction_order = {"left": 0, "right": 1, "up": 0, "down": 1}
    return (
        vote.distance,
        axis_order[vote.axis],
        direction_order[vote.direction],
        _cell_sort(vote.peer),
        vote.translated_formula,
    )


def _contiguous_peer_cells(
    model: WorkbookModel,
    target: CellKey,
    radius: int,
) -> tuple[tuple[CellKey, str, str, int], ...]:
    target_address = parse_address(target[1])
    formula_cells = set(model.formula_cells)
    peers: list[tuple[CellKey, str, str, int]] = []
    directions = (
        ("row", "left", 0, -1),
        ("row", "right", 0, 1),
        ("column", "up", -1, 0),
        ("column", "down", 1, 0),
    )
    for axis, direction, row_step, col_step in directions:
        for distance in range(1, radius + 1):
            row = target_address.row + row_step * distance
            col = target_address.col + col_step * distance
            if row < 1 or row > MAX_EXCEL_ROW or col < 1 or col > MAX_EXCEL_COLUMN:
                break
            peer = (target[0], f"{num_to_col(col)}{row}")
            if peer not in formula_cells:
                break
            peers.append((peer, axis, direction, distance))
    return tuple(peers)


def _generate_peer_translation_candidates(
    model: WorkbookModel,
    target: CellKey,
    config: CandidatePoolConfig,
    graph: DependencyGraph,
) -> _PeerGeneration:
    observed = canonical_formula_key(model.formulas[target])
    known_sheets = _known_sheets(model)
    related = graph.ancestors(target) | graph.descendants(target)
    cycle_forbidden = {target, *graph.descendants(target)}
    excluded: set[CellKey] = set()
    votes_by_key: dict[str, list[PeerTranslationVote]] = {}
    formula_by_key: dict[str, str] = {}

    for peer, axis, direction, distance in _contiguous_peer_cells(
        model, target, config.peer_radius
    ):
        if peer in related:
            excluded.add(peer)
            continue
        source_formula = model.formulas[peer]
        try:
            source_node = parse_formula(source_formula)
            if not _translation_stays_in_grid(source_node, peer[1], target[1]):
                continue
            translated = translate_formula(source_formula, peer[1], target[1])
            rendered, key = _canonical_formula(translated)
            node = parse_formula(rendered)
        except (FormulaSyntaxError, ValueError, OverflowError):
            continue
        if key == observed or not _references_are_valid(
            node,
            target[0],
            known_sheets,
            cycle_forbidden,
        ):
            continue
        formula_by_key[key] = min(formula_by_key.get(key, rendered), rendered)
        votes_by_key.setdefault(key, []).append(
            PeerTranslationVote(
                peer=peer,
                axis=axis,
                direction=direction,
                distance=distance,
                source_formula=source_formula,
                translated_formula=translated,
            )
        )

    candidates = [
        PeerTranslationCandidate(
            formula=formula_by_key[key],
            canonical_key=key,
            votes=tuple(sorted(votes, key=_vote_sort)),
        )
        for key, votes in votes_by_key.items()
        if len({vote.peer for vote in votes}) >= config.minimum_peer_votes
    ]
    candidates.sort(
        key=lambda item: (
            -len(item.votes),
            min(vote.distance for vote in item.votes),
            item.canonical_key,
        )
    )
    return _PeerGeneration(
        candidates=tuple(candidates),
        dependency_excluded_peers=tuple(sorted(excluded, key=_cell_sort)),
    )


def generate_peer_translation_candidates(
    model: WorkbookModel,
    target: CellKey,
    *,
    config: CandidatePoolConfig | None = None,
) -> tuple[PeerTranslationCandidate, ...]:
    """Return bounded, two-vote peer hypotheses from the observed graph."""

    resolved = config or CandidatePoolConfig()
    resolved.validate()
    if target not in model.formulas:
        raise KeyError(f"Formula cell not found: {target[0]}!{target[1]}")
    if resolved.peer_budget == 0:
        return ()
    generated = _generate_peer_translation_candidates(
        model,
        target,
        resolved,
        model.dependency_graph(),
    )
    return generated.candidates[: resolved.peer_budget]


def _ast_provenance(candidate: CounterfactualCandidate) -> AstCandidateProvenance:
    return AstCandidateProvenance(
        generated_formula=candidate.formula,
        edit_kind=candidate.edit_kind,
        witness=candidate.witness,
    )


def _source_stratified_order(
    ast_keys: list[str],
    peer_keys: list[str],
) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for index in range(max(len(ast_keys), len(peer_keys), 0)):
        for keys in (ast_keys, peer_keys):
            if index >= len(keys) or keys[index] in seen:
                continue
            seen.add(keys[index])
            ordered.append(keys[index])
    return tuple(ordered)


def build_candidate_pool(
    model: WorkbookModel,
    target: CellKey,
    *,
    config: CandidatePoolConfig | None = None,
) -> CandidatePool:
    """Build source-stratified repair hypotheses without labels or error claims."""

    resolved = config or CandidatePoolConfig()
    resolved.validate()
    if target not in model.formulas:
        raise KeyError(f"Formula cell not found: {target[0]}!{target[1]}")

    graph = model.dependency_graph()
    ast_candidates = generate_counterfactual_candidates(
        model,
        target,
        budget=resolved.ast_budget,
    )
    peer_generation = _generate_peer_translation_candidates(
        model,
        target,
        resolved,
        graph,
    )
    peer_candidates = peer_generation.candidates[: resolved.peer_budget]

    merged: dict[str, _MergedCandidate] = {}
    ast_keys: list[str] = []
    for candidate in ast_candidates:
        formula, key = _canonical_formula(candidate.formula)
        entry = merged.setdefault(key, _MergedCandidate(formula, [], []))
        entry.ast_provenance.append(_ast_provenance(candidate))
        if key not in ast_keys:
            ast_keys.append(key)

    peer_keys: list[str] = []
    for candidate in peer_candidates:
        entry = merged.setdefault(
            candidate.canonical_key,
            _MergedCandidate(candidate.formula, [], []),
        )
        entry.formula = min(entry.formula, candidate.formula)
        entry.peer_votes.extend(candidate.votes)
        if candidate.canonical_key not in peer_keys:
            peer_keys.append(candidate.canonical_key)

    entries = tuple(
        CandidatePoolEntry(
            formula=merged[key].formula,
            canonical_key=key,
            ast_provenance=tuple(merged[key].ast_provenance),
            peer_votes=tuple(sorted(merged[key].peer_votes, key=_vote_sort)),
        )
        for key in _source_stratified_order(ast_keys, peer_keys)
    )
    return CandidatePool(
        target=target,
        observed_formula_key=canonical_formula_key(model.formulas[target]),
        candidates=entries,
        audit=CandidatePoolAudit(
            source_budgets=(
                (AST_SOURCE, resolved.ast_budget),
                (PEER_SOURCE, resolved.peer_budget),
            ),
            peer_radius=resolved.peer_radius,
            minimum_peer_votes=resolved.minimum_peer_votes,
            ast_selected=len(ast_candidates),
            peer_consensus_available=len(peer_generation.candidates),
            peer_selected=len(peer_candidates),
            dependency_excluded_peers=peer_generation.dependency_excluded_peers,
        ),
    )


__all__ = [
    "AST_SOURCE",
    "DEFAULT_AST_BUDGET",
    "DEFAULT_PEER_BUDGET",
    "DEFAULT_PEER_RADIUS",
    "MINIMUM_PEER_VOTES",
    "PEER_SOURCE",
    "AstCandidateProvenance",
    "CandidatePool",
    "CandidatePoolAudit",
    "CandidatePoolConfig",
    "CandidatePoolEntry",
    "PeerTranslationCandidate",
    "PeerTranslationVote",
    "build_candidate_pool",
    "canonical_formula_key",
    "generate_peer_translation_candidates",
]
