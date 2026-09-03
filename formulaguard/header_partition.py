"""Target-masked candidates from header-grounded aggregate partitions.

The certificate implemented here identifies a formula permitted by a narrow,
observable workbook schema.  It does not establish that the observed formula is
wrong or that the candidate is the author's intended formula.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .a1 import Address, num_to_col, parse_address
from .formula import FormulaSyntaxError, Func, Range, Ref, parse_formula, render
from .workbook import CellKey, WorkbookModel

PROTOCOL = "formulaguard_header_partition_certificate_v1"
STANDARD_FORMULA_KINDS = frozenset({"normal", "shared"})
STRUCTURAL_OUTPUT_TOKENS = frozenset({"grand", "sum", "total"})
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, order=True)
class ColumnInterval:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 1 or self.end < self.start:
            raise ValueError("column intervals must be positive and forward")

    @property
    def columns(self) -> tuple[int, ...]:
        return tuple(range(self.start, self.end + 1))


@dataclass(frozen=True)
class HeaderPartitionConfig:
    min_components: int = 3
    max_components: int = 6
    min_grand_width: int = 8
    output_header_lookback: int = 5
    source_header_lookback: int = 12
    min_repeat_rows: int = 3

    def validate(self) -> None:
        integer_fields = (
            "min_components",
            "max_components",
            "min_grand_width",
            "output_header_lookback",
            "source_header_lookback",
            "min_repeat_rows",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.min_components < 3:
            raise ValueError("at least three components are required")
        if self.max_components > 6:
            raise ValueError("max_components cannot exceed the frozen bound of six")
        if self.max_components < self.min_components:
            raise ValueError("max_components must not be smaller than min_components")
        if self.min_grand_width < 8:
            raise ValueError("min_grand_width cannot relax the frozen bound of eight")
        if self.output_header_lookback > 5:
            raise ValueError("output_header_lookback cannot exceed the frozen bound of five")
        if self.source_header_lookback > 12:
            raise ValueError("source_header_lookback cannot exceed the frozen bound of twelve")
        if self.min_repeat_rows < 3:
            raise ValueError("at least three repeated rows are required")


@dataclass(frozen=True)
class HeaderRoleWitness:
    output_column: int
    output_header_cell: CellKey
    output_header: str
    role_tokens: tuple[str, ...]
    source_intervals: tuple[ColumnInterval, ...]
    formula_cell: CellKey


@dataclass(frozen=True)
class HeaderPartitionCertificate:
    protocol: str
    sheet: str
    grand_formula_cell: CellKey
    target_formula_cell: CellKey
    output_header_row: int
    source_header_row: int
    row_start: int
    row_end: int
    grand_interval: ColumnInterval
    component_columns: tuple[int, ...]
    shared_output_tokens: tuple[str, ...]
    target_output_header: str
    target_role_tokens: tuple[str, ...]
    target_intervals: tuple[ColumnInterval, ...]
    sibling_witnesses: tuple[HeaderRoleWitness, ...]
    unmapped_columns: tuple[int, ...]
    excluded_target_cells: tuple[CellKey, ...]
    target_input_domain_has_observed_values: bool
    interpretation: str = "header_grounded_partition_candidate"
    candidate_scope: str = "repeated_formula_block"
    candidate_identified: bool = True
    candidate_derived_without_observed_target: bool = True
    observed_target_used_for_comparison: bool = False
    target_excluded: bool = True
    can_identify_formula_error: bool = False
    formula_role_provenance_disjoint: bool = True
    repeated_rows_are_independent_author_witnesses: bool = False
    within_block_ranking_supported: bool = False

    @property
    def repeat_rows(self) -> int:
        return self.row_end - self.row_start + 1


@dataclass(frozen=True)
class HeaderPartitionCellComparison:
    target: CellKey
    observed_formula: str
    candidate_formula: str
    observed_intervals: tuple[ColumnInterval, ...]
    candidate_intervals: tuple[ColumnInterval, ...]
    missing_columns: tuple[int, ...]
    extra_columns: tuple[int, ...]
    edit_kind: str
    interpretation: str
    observed_disagrees: bool | None
    comparison_supported: bool
    actionable_schema_disagreement: bool
    candidate_identified: bool = True
    candidate_derived_without_observed_target: bool = True
    observed_target_used_for_comparison: bool = True
    target_excluded: bool = False
    can_identify_formula_error: bool = False


@dataclass(frozen=True)
class HeaderPartitionObservation:
    certificate: HeaderPartitionCertificate
    cells: tuple[HeaderPartitionCellComparison, ...]


@dataclass(frozen=True)
class HeaderPartitionBlock:
    certificate: HeaderPartitionCertificate
    cells: tuple[HeaderPartitionCellComparison, ...]
    selection_basis: str = "coordinate_canonicalization_only"
    within_block_ranking_supported: bool = False

    @property
    def deterministic_representative(self) -> HeaderPartitionCellComparison:
        return self.disagreement_cells[0]

    @property
    def disagreement_cells(self) -> tuple[HeaderPartitionCellComparison, ...]:
        return tuple(
            cell for cell in self.cells if cell.observed_disagrees is True
        )

    @property
    def incomparable_cells(self) -> tuple[HeaderPartitionCellComparison, ...]:
        return tuple(
            cell for cell in self.cells if not cell.comparison_supported
        )

    @property
    def reviewed_formula_cells(self) -> tuple[CellKey, ...]:
        return tuple(cell.target for cell in self.cells)

    @property
    def tied_candidate_cells(self) -> tuple[CellKey, ...]:
        return tuple(cell.target for cell in self.disagreement_cells)

    @property
    def formula_cell_review_cost(self) -> int:
        return len(self.cells)

    @property
    def incomparable_formula_cell_review_cost(self) -> int:
        return len(self.incomparable_cells)

    @property
    def schema_block_review_cost(self) -> int:
        return 1


@dataclass(frozen=True)
class HeaderPartitionResult:
    protocol: str
    certificates: tuple[HeaderPartitionCertificate, ...]
    observations: tuple[HeaderPartitionObservation, ...]
    qualified_blocks: tuple[HeaderPartitionBlock, ...]
    deterministic_representative: HeaderPartitionCellComparison | None
    abstain_reason: str | None


@dataclass(frozen=True)
class _ParsedRowSum:
    intervals: tuple[ColumnInterval, ...]
    columns: frozenset[int]


@dataclass(frozen=True)
class _OutputHeaders:
    row: int
    texts: tuple[str, ...]
    shared_tokens: tuple[str, ...]
    roles: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class _SourceHeader:
    row: int
    intervals_by_role: tuple[tuple[ColumnInterval, ...], ...]
    unmapped_columns: tuple[int, ...]


def _cell(sheet: str, row: int, column: int) -> CellKey:
    return sheet, f"{num_to_col(column)}{row}"


def _nonblank(value: object) -> bool:
    return value is not None and (
        not isinstance(value, str) or bool(value.strip())
    )


def _normalize_token(token: str) -> str:
    return token.casefold()


def normalize_header(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or value.startswith("="):
        return ()
    return tuple(_normalize_token(token) for token in TOKEN_RE.findall(value))


def _visible_plain_text(model: WorkbookModel, key: CellKey) -> str | None:
    if model.is_formula_derived(key) or not model.is_visible(key) or model.is_merged(key):
        return None
    value = model.cells.get(key)
    if not isinstance(value, str) or not value.strip() or value.startswith("="):
        return None
    return value.strip()


def _columns_to_intervals(columns: Iterable[int]) -> tuple[ColumnInterval, ...]:
    ordered = sorted(set(columns))
    if not ordered:
        return ()
    intervals: list[ColumnInterval] = []
    start = previous = ordered[0]
    for column in ordered[1:]:
        if column == previous + 1:
            previous = column
            continue
        intervals.append(ColumnInterval(start, previous))
        start = previous = column
    intervals.append(ColumnInterval(start, previous))
    return tuple(intervals)


def _interval_columns(intervals: Iterable[ColumnInterval]) -> frozenset[int]:
    return frozenset(
        column for interval in intervals for column in interval.columns
    )


def _parse_row_sum(
    model: WorkbookModel,
    key: CellKey,
    *,
    expected_row: int,
) -> _ParsedRowSum | None:
    if key not in model.formulas:
        return None
    if not model.is_visible(key) or model.is_merged(key):
        return None
    if model.formula_kind(key) not in STANDARD_FORMULA_KINDS:
        return None
    try:
        node = parse_formula(model.formulas[key])
    except (FormulaSyntaxError, TypeError, ValueError):
        return None
    if not isinstance(node, Func) or node.name != "SUM" or not node.args:
        return None

    intervals: list[ColumnInterval] = []
    for argument in node.args:
        if isinstance(argument, Ref):
            if argument.sheet is not None:
                return None
            address = argument.address
            if address.row != expected_row or address.row_abs or address.col_abs:
                return None
            intervals.append(ColumnInterval(address.col, address.col))
            continue
        if not isinstance(argument, Range):
            return None
        start, end = argument.start, argument.end
        if start.sheet is not None or end.sheet is not None:
            return None
        if (
            start.address.row != expected_row
            or end.address.row != expected_row
            or start.address.row_abs
            or end.address.row_abs
            or start.address.col_abs
            or end.address.col_abs
            or start.address.row > end.address.row
            or start.address.col > end.address.col
        ):
            return None
        intervals.append(ColumnInterval(start.address.col, end.address.col))

    if intervals != sorted(intervals):
        return None
    columns: set[int] = set()
    for interval in intervals:
        current = set(interval.columns)
        if columns & current:
            return None
        columns.update(current)
    return _ParsedRowSum(tuple(intervals), frozenset(columns))


def _output_header_candidates(
    model: WorkbookModel,
    *,
    sheet: str,
    formula_row: int,
    output_columns: tuple[int, ...],
    config: HeaderPartitionConfig,
) -> tuple[_OutputHeaders, ...]:
    candidates: list[_OutputHeaders] = []
    lower = max(1, formula_row - config.output_header_lookback)
    for row in range(formula_row - 1, lower - 1, -1):
        keys = tuple(_cell(sheet, row, column) for column in output_columns)
        texts = tuple(_visible_plain_text(model, key) for key in keys)
        if any(text is None for text in texts):
            continue
        resolved_texts = tuple(str(text) for text in texts)
        token_rows = tuple(normalize_header(text) for text in resolved_texts)
        if any(not tokens for tokens in token_rows):
            continue
        grand_tokens = set(token_rows[0])
        if "total" not in grand_tokens:
            continue
        shared = set(token_rows[1])
        for tokens in token_rows[2:]:
            shared.intersection_update(tokens)
        shared.difference_update(STRUCTURAL_OUTPUT_TOKENS)
        grand_shared_tokens = tuple(
            sorted(
                token
                for token in token_rows[0]
                if token not in STRUCTURAL_OUTPUT_TOKENS
            )
        )
        if not shared or grand_shared_tokens != tuple(sorted(shared)):
            continue
        roles = tuple(
            tuple(token for token in tokens if token not in shared)
            for tokens in token_rows[1:]
        )
        if any(not role for role in roles) or len(set(roles)) != len(roles):
            continue
        candidates.append(
            _OutputHeaders(
                row=row,
                texts=resolved_texts,
                shared_tokens=tuple(sorted(shared)),
                roles=roles,
            )
        )
    return tuple(candidates)


def _source_header_candidates(
    model: WorkbookModel,
    *,
    sheet: str,
    output_header_row: int,
    grand_interval: ColumnInterval,
    roles: tuple[tuple[str, ...], ...],
    sibling_sums: dict[int, _ParsedRowSum],
    target_index: int,
    config: HeaderPartitionConfig,
) -> tuple[_SourceHeader, ...]:
    candidates: list[_SourceHeader] = []
    lower = max(1, output_header_row - config.source_header_lookback)
    for row in range(output_header_row - 1, lower - 1, -1):
        domains: list[list[int]] = [[] for _ in roles]
        unmapped: list[int] = []
        valid = True
        for column in grand_interval.columns:
            key = _cell(sheet, row, column)
            if (
                model.is_merged(key)
                or not model.is_visible(key)
                or model.is_formula_derived(key)
            ):
                valid = False
                break
            value = model.cells.get(key)
            if not _nonblank(value):
                unmapped.append(column)
                continue
            tokens = normalize_header(value)
            matches = [index for index, role in enumerate(roles) if tokens == role]
            if len(matches) != 1:
                valid = False
                break
            domains[matches[0]].append(column)
        if not valid or any(not domain for domain in domains):
            continue
        intervals_by_role = tuple(_columns_to_intervals(domain) for domain in domains)
        if any(
            sibling_sums[index].columns
            != _interval_columns(intervals_by_role[index])
            for index in sibling_sums
        ):
            continue
        candidates.append(
            _SourceHeader(
                row=row,
                intervals_by_role=intervals_by_role,
                unmapped_columns=tuple(unmapped),
            )
        )
    return tuple(candidates)


def _row_matches_masked_group(
    model: WorkbookModel,
    *,
    visible_formula_occupancy: frozenset[CellKey],
    sheet: str,
    row: int,
    grand_column: int,
    component_columns: tuple[int, ...],
    target_index: int,
    grand_columns: frozenset[int],
    sibling_columns: dict[int, frozenset[int]],
) -> bool:
    target_key = _cell(sheet, row, component_columns[target_index])
    if target_key not in visible_formula_occupancy:
        return False
    grand_key = _cell(sheet, row, grand_column)
    sibling_keys = tuple(
        _cell(sheet, row, component_columns[index]) for index in sibling_columns
    )
    if not _formula_evidence_is_independent(
        model,
        target_key=target_key,
        witness_keys=(grand_key, *sibling_keys),
    ):
        return False
    if not model.is_visible(grand_key):
        return False
    grand = _parse_row_sum(
        model, grand_key, expected_row=row
    )
    if grand is None or grand.columns != grand_columns:
        return False
    for index, columns in sibling_columns.items():
        sibling_key = _cell(sheet, row, component_columns[index])
        if not model.is_visible(sibling_key):
            return False
        sibling = _parse_row_sum(
            model, sibling_key, expected_row=row
        )
        if sibling is None or sibling.columns != columns:
            return False
    return True


def _repeat_bounds(
    model: WorkbookModel,
    *,
    visible_formula_occupancy: frozenset[CellKey],
    sheet: str,
    seed_row: int,
    grand_column: int,
    component_columns: tuple[int, ...],
    target_index: int,
    grand_columns: frozenset[int],
    sibling_columns: dict[int, frozenset[int]],
) -> tuple[int, int]:
    def matches(row: int) -> bool:
        return row >= 1 and _row_matches_masked_group(
            model,
            visible_formula_occupancy=visible_formula_occupancy,
            sheet=sheet,
            row=row,
            grand_column=grand_column,
            component_columns=component_columns,
            target_index=target_index,
            grand_columns=grand_columns,
            sibling_columns=sibling_columns,
        )

    row_start = seed_row
    while matches(row_start - 1):
        row_start -= 1
    row_end = seed_row
    while matches(row_end + 1):
        row_end += 1
    return row_start, row_end


def _source_domain_is_plain_values(
    model: WorkbookModel,
    *,
    sheet: str,
    rows: range,
    columns: Iterable[int],
) -> bool:
    return all(
        not model.is_formula_derived(key)
        and model.is_visible(key)
        and not model.is_merged(key)
        for column in columns
        for row in rows
        for key in (_cell(sheet, row, column),)
    )


def _unmapped_columns_are_blank(
    model: WorkbookModel,
    *,
    sheet: str,
    rows: range,
    columns: Iterable[int],
) -> bool:
    return all(
        not model.is_formula_derived(key)
        and model.is_visible(key)
        and not model.is_merged(key)
        and not _nonblank(model.cells.get(key))
        for row in rows
        for column in columns
        for key in (_cell(sheet, row, column),)
    )


def _domain_has_observed_values(
    model: WorkbookModel,
    *,
    sheet: str,
    rows: range,
    columns: Iterable[int],
) -> bool:
    # A repeated block is active only when every row has observed input in the
    # candidate domain. A single empty row must conservatively inactivate the
    # whole block so it cannot inherit another row's actionable status.
    domain_rows = tuple(rows)
    domain_columns = tuple(columns)
    return bool(domain_rows) and bool(domain_columns) and all(
        any(
            _nonblank(model.cells.get(_cell(sheet, row, column)))
            for column in domain_columns
        )
        for row in domain_rows
    )


def _certificate_key(certificate: HeaderPartitionCertificate) -> tuple[object, ...]:
    return (
        certificate.sheet,
        certificate.row_start,
        certificate.row_end,
        certificate.grand_formula_cell,
        certificate.target_formula_cell,
        certificate.output_header_row,
        certificate.source_header_row,
        certificate.component_columns,
        certificate.target_intervals,
    )


def _formula_provenance_unit(
    model: WorkbookModel,
    key: CellKey,
    *,
    allow_opaque_target: bool,
) -> tuple[str, str, str] | None:
    kind = model.formula_kind(key)
    group = model.shared_formula_group(key)
    if kind == "shared":
        if group is None:
            return None
        return "shared", key[0], group
    if kind == "normal":
        return "cell", key[0], key[1]
    if allow_opaque_target:
        if group is not None:
            return "shared", key[0], group
        return "opaque-target", key[0], key[1]
    return None


def _formula_evidence_is_independent(
    model: WorkbookModel,
    *,
    target_key: CellKey,
    witness_keys: Iterable[CellKey],
) -> bool:
    target_unit = _formula_provenance_unit(
        model,
        target_key,
        allow_opaque_target=True,
    )
    if target_unit is None:
        return False
    witness_units: list[tuple[str, str, str]] = []
    for key in witness_keys:
        unit = _formula_provenance_unit(
            model,
            key,
            allow_opaque_target=False,
        )
        if unit is None:
            return False
        witness_units.append(unit)
    return (
        len(witness_units) == len(set(witness_units))
        and target_unit not in witness_units
    )


def _block_formula_role_provenance_is_disjoint(
    model: WorkbookModel,
    *,
    sheet: str,
    rows: range,
    grand_column: int,
    component_columns: tuple[int, ...],
    target_index: int,
    sibling_indices: Iterable[int],
) -> bool:
    role_keys: list[tuple[tuple[CellKey, ...], bool]] = [
        (
            tuple(
                _cell(sheet, row, component_columns[target_index]) for row in rows
            ),
            True,
        ),
        (tuple(_cell(sheet, row, grand_column) for row in rows), False),
    ]
    role_keys.extend(
        (
            tuple(_cell(sheet, row, component_columns[index]) for row in rows),
            False,
        )
        for index in sorted(sibling_indices)
    )

    seen: set[tuple[str, str, str]] = set()
    for keys, allow_opaque_target in role_keys:
        units: set[tuple[str, str, str]] = set()
        for key in keys:
            unit = _formula_provenance_unit(
                model,
                key,
                allow_opaque_target=allow_opaque_target,
            )
            if unit is None:
                return False
            units.add(unit)
        if seen & units:
            return False
        seen.update(units)
    return True


def _mask_target_formula_cells(
    model: WorkbookModel,
    *,
    excluded: Iterable[CellKey],
) -> WorkbookModel:
    excluded = frozenset(excluded)
    if not excluded <= set(model.formulas):
        raise ValueError("masked target cells must belong to the formula inventory")
    masked = WorkbookModel(
        {key: value for key, value in model.cells.items() if key not in excluded},
        {key: value for key, value in model.formulas.items() if key not in excluded},
        source=model.source,
        cell_visibility=model.cell_visibility,
        number_formats=model.number_formats,
        sheet_visibility=model.sheet_visibility,
        merged_ranges=model.merged_ranges,
        formula_kinds=model.formula_kinds,
        formula_regions=model.formula_regions,
        shared_formula_groups=model.shared_formula_groups,
        hidden_rows=model.hidden_rows,
        hidden_columns=model.hidden_columns,
        header_partition_metadata_complete=model.header_partition_metadata_complete,
    )
    return masked


def _seed_sibling_sums(
    model: WorkbookModel,
    *,
    sheet: str,
    row: int,
    component_columns: tuple[int, ...],
    target_index: int,
    grand_columns: frozenset[int],
    grand_key: CellKey,
) -> dict[int, _ParsedRowSum] | None:
    target_key = _cell(sheet, row, component_columns[target_index])
    sibling_keys = tuple(
        _cell(sheet, row, column)
        for index, column in enumerate(component_columns)
        if index != target_index
    )
    if not _formula_evidence_is_independent(
        model,
        target_key=target_key,
        witness_keys=(grand_key, *sibling_keys),
    ):
        return None
    siblings: dict[int, _ParsedRowSum] = {}
    union: set[int] = set()
    for index, column in enumerate(component_columns):
        if index == target_index:
            continue
        sibling = _parse_row_sum(
            model, _cell(sheet, row, column), expected_row=row
        )
        if (
            sibling is None
            or not sibling.columns
            or not sibling.columns < grand_columns
            or union & set(sibling.columns)
        ):
            return None
        siblings[index] = sibling
        union.update(sibling.columns)
    return siblings if len(siblings) >= 2 else None


def discover_header_partition_certificates(
    model: WorkbookModel,
    *,
    config: HeaderPartitionConfig | None = None,
) -> tuple[HeaderPartitionCertificate, ...]:
    """Construct candidates while treating each prospective target as opaque."""

    resolved = config or HeaderPartitionConfig()
    resolved.validate()
    if not model.header_partition_metadata_complete:
        return ()
    formula_cells = set(model.formulas)
    visible_formula_occupancy = frozenset(
        key
        for key in formula_cells
        if model.is_visible(key) and not model.is_merged(key)
    )
    certificates: dict[tuple[object, ...], HeaderPartitionCertificate] = {}

    for grand_key in sorted(model.formula_cells):
        if not model.is_visible(grand_key):
            continue
        sheet, address_text = grand_key
        address = parse_address(address_text)
        grand = _parse_row_sum(model, grand_key, expected_row=address.row)
        if (
            grand is None
            or len(grand.intervals) != 1
            or len(grand.columns) < resolved.min_grand_width
            or address.col <= grand.intervals[0].end
        ):
            continue

        contiguous: list[int] = []
        for column in range(address.col + 1, address.col + resolved.max_components + 1):
            key = _cell(sheet, address.row, column)
            if key not in visible_formula_occupancy:
                break
            contiguous.append(column)
        if (
            len(contiguous) == resolved.max_components
            and _cell(sheet, address.row, contiguous[-1] + 1) in formula_cells
        ):
            continue

        for count in range(resolved.min_components, len(contiguous) + 1):
            component_columns = tuple(contiguous[:count])
            output_columns = (address.col, *component_columns)

            for target_index, target_column in enumerate(component_columns):
                seed_target = _cell(sheet, address.row, target_column)
                preliminary_model = _mask_target_formula_cells(
                    model,
                    excluded=(seed_target,),
                )
                preliminary_siblings = _seed_sibling_sums(
                    preliminary_model,
                    sheet=sheet,
                    row=address.row,
                    component_columns=component_columns,
                    target_index=target_index,
                    grand_columns=grand.columns,
                    grand_key=grand_key,
                )
                if preliminary_siblings is None:
                    continue
                row_start, row_end = _repeat_bounds(
                    preliminary_model,
                    visible_formula_occupancy=visible_formula_occupancy,
                    sheet=sheet,
                    seed_row=address.row,
                    grand_column=address.col,
                    component_columns=component_columns,
                    target_index=target_index,
                    grand_columns=grand.columns,
                    sibling_columns={
                        index: item.columns
                        for index, item in preliminary_siblings.items()
                    },
                )
                repeat_count = row_end - row_start + 1
                if repeat_count < resolved.min_repeat_rows:
                    continue
                excluded_target_cells = tuple(
                    _cell(sheet, row, target_column)
                    for row in range(row_start, row_end + 1)
                )
                masked_model = _mask_target_formula_cells(
                    model,
                    excluded=excluded_target_cells,
                )
                output_headers = _output_header_candidates(
                    masked_model,
                    sheet=sheet,
                    formula_row=address.row,
                    output_columns=output_columns,
                    config=resolved,
                )
                if len(output_headers) != 1:
                    continue
                output_header = output_headers[0]
                sibling_sums = _seed_sibling_sums(
                    masked_model,
                    sheet=sheet,
                    row=address.row,
                    component_columns=component_columns,
                    target_index=target_index,
                    grand_columns=grand.columns,
                    grand_key=grand_key,
                )
                if sibling_sums is None:
                    continue
                sibling_union = set().union(
                    *(set(item.columns) for item in sibling_sums.values())
                )
                if _repeat_bounds(
                    masked_model,
                    visible_formula_occupancy=visible_formula_occupancy,
                    sheet=sheet,
                    seed_row=address.row,
                    grand_column=address.col,
                    component_columns=component_columns,
                    target_index=target_index,
                    grand_columns=grand.columns,
                    sibling_columns={
                        index: item.columns for index, item in sibling_sums.items()
                    },
                ) != (row_start, row_end):
                    continue

                source_headers = _source_header_candidates(
                    masked_model,
                    sheet=sheet,
                    output_header_row=output_header.row,
                    grand_interval=grand.intervals[0],
                    roles=output_header.roles,
                    sibling_sums=sibling_sums,
                    target_index=target_index,
                    config=resolved,
                )
                if len(source_headers) != 1:
                    continue
                source_header = source_headers[0]
                target_columns = _interval_columns(
                    source_header.intervals_by_role[target_index]
                )
                if target_columns & sibling_union:
                    continue
                labeled_columns = target_columns | frozenset(sibling_union)
                if labeled_columns | frozenset(source_header.unmapped_columns) != grand.columns:
                    continue
                first_columns = tuple(
                    intervals[0].start
                    for intervals in source_header.intervals_by_role
                )
                if first_columns != tuple(sorted(first_columns)):
                    continue

                rows = range(row_start, row_end + 1)
                if not _source_domain_is_plain_values(
                    masked_model,
                    sheet=sheet,
                    rows=rows,
                    columns=grand.columns,
                ):
                    continue
                if not _unmapped_columns_are_blank(
                    masked_model,
                    sheet=sheet,
                    rows=rows,
                    columns=source_header.unmapped_columns,
                ):
                    continue
                if not _block_formula_role_provenance_is_disjoint(
                    model,
                    sheet=sheet,
                    rows=rows,
                    grand_column=address.col,
                    component_columns=component_columns,
                    target_index=target_index,
                    sibling_indices=sibling_sums,
                ):
                    continue

                target_input_domain_has_observed_values = (
                    _domain_has_observed_values(
                        masked_model,
                        sheet=sheet,
                        rows=rows,
                        columns=target_columns,
                    )
                )

                siblings = tuple(
                    HeaderRoleWitness(
                        output_column=component_columns[index],
                        output_header_cell=_cell(
                            sheet, output_header.row, component_columns[index]
                        ),
                        output_header=output_header.texts[index + 1],
                        role_tokens=output_header.roles[index],
                        source_intervals=source_header.intervals_by_role[index],
                        formula_cell=_cell(
                            sheet, row_start, component_columns[index]
                        ),
                    )
                    for index in sorted(sibling_sums)
                )
                certificate = HeaderPartitionCertificate(
                    protocol=PROTOCOL,
                    sheet=sheet,
                    grand_formula_cell=_cell(sheet, row_start, address.col),
                    target_formula_cell=_cell(sheet, row_start, target_column),
                    output_header_row=output_header.row,
                    source_header_row=source_header.row,
                    row_start=row_start,
                    row_end=row_end,
                    grand_interval=grand.intervals[0],
                    component_columns=component_columns,
                    shared_output_tokens=output_header.shared_tokens,
                    target_output_header=output_header.texts[target_index + 1],
                    target_role_tokens=output_header.roles[target_index],
                    target_intervals=source_header.intervals_by_role[target_index],
                    sibling_witnesses=siblings,
                    unmapped_columns=source_header.unmapped_columns,
                    excluded_target_cells=excluded_target_cells,
                    target_input_domain_has_observed_values=(
                        target_input_domain_has_observed_values
                    ),
                )
                certificates[_certificate_key(certificate)] = certificate

    return tuple(certificates[key] for key in sorted(certificates))


def _render_sum(intervals: tuple[ColumnInterval, ...], row: int) -> str:
    arguments: list[Ref | Range] = []
    for interval in intervals:
        start = Ref(Address(row=row, col=interval.start))
        end = Ref(Address(row=row, col=interval.end))
        arguments.append(start if interval.start == interval.end else Range(start, end))
    return "=" + render(Func("SUM", tuple(arguments)))


def _observe_certificate(
    model: WorkbookModel,
    certificate: HeaderPartitionCertificate,
) -> HeaderPartitionObservation:
    cells: list[HeaderPartitionCellComparison] = []
    target_column = parse_address(certificate.target_formula_cell[1]).col
    for row in range(certificate.row_start, certificate.row_end + 1):
        target = _cell(certificate.sheet, row, target_column)
        observed = _parse_row_sum(model, target, expected_row=row)
        if observed is None:
            observed_intervals: tuple[ColumnInterval, ...] = ()
            missing: tuple[int, ...] = ()
            extra: tuple[int, ...] = ()
            edit_kind = "unsupported_observed_formula"
            interpretation = "workbook_internal_schema_incomparable"
            disagrees: bool | None = None
            comparison_supported = False
        else:
            observed_intervals = observed.intervals
            observed_columns = _interval_columns(observed.intervals)
            candidate_columns = _interval_columns(certificate.target_intervals)
            missing = tuple(sorted(candidate_columns - observed_columns))
            extra = tuple(sorted(observed_columns - candidate_columns))
            disagrees = bool(missing or extra)
            comparison_supported = True
            if not disagrees:
                edit_kind = "header_domain_agreement"
                interpretation = "workbook_internal_schema_agreement"
            elif missing and not extra:
                edit_kind = "header_domain_omission"
                interpretation = "workbook_internal_schema_disagreement"
            elif extra and not missing:
                edit_kind = "header_domain_overreach"
                interpretation = "workbook_internal_schema_disagreement"
            else:
                edit_kind = "header_domain_substitution"
                interpretation = "workbook_internal_schema_disagreement"
            if not certificate.target_input_domain_has_observed_values:
                interpretation += "_inactive_target_domain"
        actionable_schema_disagreement = bool(
            comparison_supported
            and disagrees
            and certificate.target_input_domain_has_observed_values
        )
        cells.append(
            HeaderPartitionCellComparison(
                target=target,
                observed_formula=model.formulas[target],
                candidate_formula=_render_sum(certificate.target_intervals, row),
                observed_intervals=observed_intervals,
                candidate_intervals=certificate.target_intervals,
                missing_columns=missing,
                extra_columns=extra,
                edit_kind=edit_kind,
                interpretation=interpretation,
                observed_disagrees=disagrees,
                comparison_supported=comparison_supported,
                actionable_schema_disagreement=actionable_schema_disagreement,
            )
        )
    return HeaderPartitionObservation(certificate=certificate, cells=tuple(cells))


def _block_from_observation(
    observation: HeaderPartitionObservation,
) -> HeaderPartitionBlock | None:
    if not any(cell.observed_disagrees is True for cell in observation.cells):
        return None
    return HeaderPartitionBlock(
        certificate=observation.certificate,
        cells=observation.cells,
    )


def analyze_header_partitions(
    model: WorkbookModel,
    *,
    config: HeaderPartitionConfig | None = None,
) -> HeaderPartitionResult:
    """Return auditable candidates and abstain unless exactly one block differs."""

    if not model.header_partition_metadata_complete:
        return HeaderPartitionResult(
            protocol=PROTOCOL,
            certificates=(),
            observations=(),
            qualified_blocks=(),
            deterministic_representative=None,
            abstain_reason="structure_metadata_unavailable",
        )
    certificates = discover_header_partition_certificates(model, config=config)
    observations = tuple(
        _observe_certificate(model, certificate) for certificate in certificates
    )
    blocks = tuple(
        block
        for observation in observations
        for block in (_block_from_observation(observation),)
        if block is not None
    )
    if len(blocks) == 1:
        block = blocks[0]
        if block.incomparable_cells:
            representative = None
            abstain_reason = "qualified_block_contains_incomparable_rows"
        elif not block.certificate.target_input_domain_has_observed_values:
            representative = None
            abstain_reason = "target_input_domain_empty"
        else:
            representative = block.deterministic_representative
            abstain_reason = None
    elif not blocks:
        representative = None
        if any(
            not cell.comparison_supported
            for observation in observations
            for cell in observation.cells
        ):
            abstain_reason = "observed_target_incomparable"
        else:
            abstain_reason = "no_qualified_block"
    else:
        representative = None
        abstain_reason = "multiple_qualified_blocks"
    return HeaderPartitionResult(
        protocol=PROTOCOL,
        certificates=certificates,
        observations=observations,
        qualified_blocks=blocks,
        deterministic_representative=representative,
        abstain_reason=abstain_reason,
    )


__all__ = [
    "PROTOCOL",
    "ColumnInterval",
    "HeaderPartitionBlock",
    "HeaderPartitionCellComparison",
    "HeaderPartitionCertificate",
    "HeaderPartitionConfig",
    "HeaderPartitionObservation",
    "HeaderPartitionResult",
    "HeaderRoleWitness",
    "analyze_header_partitions",
    "discover_header_partition_certificates",
    "normalize_header",
]
