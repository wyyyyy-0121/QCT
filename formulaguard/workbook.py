"""Read XLSX packages, build dependency graphs, and evaluate supported formulas."""

from __future__ import annotations

import math
import posixpath
import statistics
import xml.etree.ElementTree as ET
import zipfile
from bisect import bisect_left
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .a1 import parse_address, plain_address
from .formula import (
    Binary,
    FormulaSyntaxError,
    Func,
    Node,
    Number,
    Range,
    Ref,
    Unary,
    flatten_values,
    formula_fingerprint,
    iter_refs,
    numeric,
    parse_formula,
    translate_formula,
)

CellKey = tuple[str, str]
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"x": NS_MAIN, "r": NS_REL}


def _forward_range_bounds(
    reference: str,
) -> tuple[str, str, tuple[int, int, int, int]]:
    parts = reference.split(":")
    if len(parts) == 1:
        start_text = end_text = parts[0]
    elif len(parts) == 2:
        start_text, end_text = parts
    else:
        raise ValueError(f"Invalid cell range: {reference}")
    start = parse_address(start_text)
    end = parse_address(end_text)
    if start.row > end.row or start.col > end.col:
        raise ValueError(f"Range endpoints must be forward: {reference}")
    return (
        plain_address(start_text),
        plain_address(end_text),
        (start.row, end.row, start.col, end.col),
    )


def _shared_formula_index(raw_index: str | None) -> str | None:
    if raw_index is None or not raw_index.strip():
        return None
    try:
        index = int(raw_index)
    except ValueError:
        return None
    if not 0 <= index <= 4_294_967_295:
        return None
    return str(index)


BUILTIN_NUMBER_FORMATS = {
    0: "General",
    1: "0",
    2: "0.00",
    9: "0%",
    10: "0.00%",
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    49: "@",
}


@dataclass
class DependencyGraph:
    precedents: dict[CellKey, set[CellKey]] = field(default_factory=dict)
    dependents: dict[CellKey, set[CellKey]] = field(default_factory=dict)

    def descendants(self, start: CellKey) -> set[CellKey]:
        seen: set[CellKey] = set()
        queue = deque(self.dependents.get(start, ()))
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(self.dependents.get(node, ()))
        return seen

    def ancestors(self, start: CellKey) -> set[CellKey]:
        seen: set[CellKey] = set()
        queue = deque(self.precedents.get(start, ()))
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(self.precedents.get(node, ()))
        return seen

    def sinks(self, formula_cells: Iterable[CellKey]) -> list[CellKey]:
        return sorted(cell for cell in formula_cells if not self.dependents.get(cell))

    def shortest_sink_depth(self, start: CellKey, formula_cells: Iterable[CellKey]) -> int | None:
        sinks = set(self.sinks(formula_cells))
        queue = deque([(start, 0)])
        seen = {start}
        while queue:
            node, depth = queue.popleft()
            if node in sinks and node != start:
                return depth
            for nxt in self.dependents.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, depth + 1))
        return 0 if start in sinks else None

    def shortest_path_length(self, start: CellKey, target: CellKey) -> int | None:
        queue = deque([(start, 0)])
        seen = {start}
        while queue:
            node, depth = queue.popleft()
            if node == target:
                return depth
            for nxt in self.dependents.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, depth + 1))
        return None

    def shortest_path(self, start: CellKey, target: CellKey) -> list[CellKey] | None:
        """Return one shortest dependency path, including both endpoints."""
        queue = deque([start])
        parent: dict[CellKey, CellKey | None] = {start: None}
        while queue:
            node = queue.popleft()
            if node == target:
                path: list[CellKey] = []
                current: CellKey | None = target
                while current is not None:
                    path.append(current)
                    current = parent[current]
                return list(reversed(path))
            for nxt in sorted(self.dependents.get(node, ())):
                if nxt not in parent:
                    parent[nxt] = node
                    queue.append(nxt)
        return None


class WorkbookModel:
    def __init__(
        self,
        cells: Mapping[CellKey, object],
        formulas: Mapping[CellKey, str],
        source: str = "",
        *,
        cell_visibility: Mapping[CellKey, bool] | None = None,
        number_formats: Mapping[CellKey, str] | None = None,
        sheet_visibility: Mapping[str, bool] | None = None,
        merged_ranges: Mapping[str, Iterable[tuple[str, str]]] | None = None,
        formula_kinds: Mapping[CellKey, str] | None = None,
        formula_regions: Mapping[
            str, Iterable[tuple[str, str, str]]
        ] | None = None,
        shared_formula_groups: Mapping[CellKey, str] | None = None,
        hidden_rows: Mapping[str, Iterable[int]] | None = None,
        hidden_columns: Mapping[str, Iterable[tuple[int, int]]] | None = None,
        header_partition_metadata_complete: bool = False,
    ):
        if not isinstance(header_partition_metadata_complete, bool):
            raise TypeError("header_partition_metadata_complete must be boolean")
        self.cells = dict(cells)
        self.formulas = {key: value if value.startswith("=") else "=" + value for key, value in formulas.items()}
        self.source = source
        all_cells = set(self.cells) | set(self.formulas)
        self.cell_visibility = {
            key: bool((cell_visibility or {}).get(key, True))
            for key in all_cells
        }
        self.number_formats = {
            key: str(value)
            for key, value in (number_formats or {}).items()
            if key in all_cells
        }
        self.sheet_visibility = {
            str(sheet): bool(visible)
            for sheet, visible in (sheet_visibility or {}).items()
        }
        self.formula_kinds = {
            key: str((formula_kinds or {}).get(key, "normal"))
            for key in self.formulas
        }
        self.shared_formula_groups = {
            key: str(group)
            for key, group in (shared_formula_groups or {}).items()
        }
        if any(not group for group in self.shared_formula_groups.values()):
            raise ValueError("shared formula group identifiers must not be empty")
        self.header_partition_metadata_complete = header_partition_metadata_complete
        self.hidden_rows = {
            str(sheet): frozenset(int(row) for row in rows)
            for sheet, rows in (hidden_rows or {}).items()
        }
        if any(row < 1 for rows in self.hidden_rows.values() for row in rows):
            raise ValueError("hidden rows must be positive")
        normalized_hidden_columns: dict[str, tuple[tuple[int, int], ...]] = {}
        for sheet, ranges in (hidden_columns or {}).items():
            normalized_ranges: list[tuple[int, int]] = []
            for start, end in ranges:
                start, end = int(start), int(end)
                if start < 1 or end < start:
                    raise ValueError("hidden column ranges must be positive and forward")
                normalized_ranges.append((start, end))
            normalized_hidden_columns[str(sheet)] = tuple(sorted(normalized_ranges))
        self.hidden_columns = normalized_hidden_columns
        normalized_merged_ranges: dict[
            str, tuple[tuple[str, str], ...]
        ] = {}
        merged_bounds: dict[str, tuple[tuple[int, int, int, int], ...]] = {}
        for sheet, ranges in (merged_ranges or {}).items():
            normalized: list[tuple[str, str]] = []
            bounds: list[tuple[int, int, int, int]] = []
            for start_text, end_text in ranges:
                start = parse_address(start_text)
                end = parse_address(end_text)
                if start.row > end.row or start.col > end.col:
                    raise ValueError(
                        f"Merged range endpoints must be forward: {sheet}!"
                        f"{start_text}:{end_text}"
                    )
                normalized.append((plain_address(start_text), plain_address(end_text)))
                bounds.append((start.row, end.row, start.col, end.col))
            normalized_merged_ranges[str(sheet)] = tuple(sorted(normalized))
            merged_bounds[str(sheet)] = tuple(sorted(bounds))
        self.merged_ranges = normalized_merged_ranges
        self._merged_bounds = merged_bounds
        normalized_formula_regions: dict[
            str, tuple[tuple[str, str, str], ...]
        ] = {}
        formula_region_bounds: dict[
            str, tuple[tuple[int, int, int, int, str], ...]
        ] = {}
        for sheet, regions in (formula_regions or {}).items():
            normalized: list[tuple[str, str, str]] = []
            bounds: list[tuple[int, int, int, int, str]] = []
            for start_text, end_text, kind_text in regions:
                start = parse_address(start_text)
                end = parse_address(end_text)
                kind = str(kind_text)
                if start.row > end.row or start.col > end.col:
                    raise ValueError(
                        f"Formula region endpoints must be forward: {sheet}!"
                        f"{start_text}:{end_text}"
                    )
                if not kind:
                    raise ValueError("formula region kind must not be empty")
                normalized.append(
                    (plain_address(start_text), plain_address(end_text), kind)
                )
                bounds.append((start.row, end.row, start.col, end.col, kind))
            normalized_formula_regions[str(sheet)] = tuple(sorted(normalized))
            formula_region_bounds[str(sheet)] = tuple(sorted(bounds))
        self.formula_regions = normalized_formula_regions
        self._formula_region_bounds = formula_region_bounds
        coordinate_index: dict[str, list[tuple[int, int, CellKey]]] = defaultdict(list)
        for key in all_cells:
            address = parse_address(key[1])
            coordinate_index[key[0]].append((address.row, address.col, key))
        self._coordinate_index = {
            sheet: tuple(sorted(entries))
            for sheet, entries in coordinate_index.items()
        }
        self._ast_cache: dict[str, Node] = {}

    @classmethod
    def from_cells(
        cls,
        cells: Mapping[CellKey, object],
        formulas: Mapping[CellKey, str],
        *,
        cell_visibility: Mapping[CellKey, bool] | None = None,
        number_formats: Mapping[CellKey, str] | None = None,
        sheet_visibility: Mapping[str, bool] | None = None,
        merged_ranges: Mapping[str, Iterable[tuple[str, str]]] | None = None,
        formula_kinds: Mapping[CellKey, str] | None = None,
        formula_regions: Mapping[
            str, Iterable[tuple[str, str, str]]
        ] | None = None,
        shared_formula_groups: Mapping[CellKey, str] | None = None,
        hidden_rows: Mapping[str, Iterable[int]] | None = None,
        hidden_columns: Mapping[str, Iterable[tuple[int, int]]] | None = None,
        header_partition_metadata_complete: bool = False,
    ) -> WorkbookModel:
        return cls(
            cells,
            formulas,
            source="in-memory",
            cell_visibility=cell_visibility,
            number_formats=number_formats,
            sheet_visibility=sheet_visibility,
            merged_ranges=merged_ranges,
            formula_kinds=formula_kinds,
            formula_regions=formula_regions,
            shared_formula_groups=shared_formula_groups,
            hidden_rows=hidden_rows,
            hidden_columns=hidden_columns,
            header_partition_metadata_complete=header_partition_metadata_complete,
        )

    @classmethod
    def from_xlsx(cls, path: str | Path) -> WorkbookModel:
        path = Path(path)
        with zipfile.ZipFile(path) as zf:
            shared_strings = cls._read_shared_strings(zf)
            workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
            rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rels = {
                rel.attrib["Id"]: rel.attrib["Target"]
                for rel in rel_root.findall(f"{{{NS_PKG_REL}}}Relationship")
            }
            sheet_paths: list[tuple[str, str, bool]] = []
            for sheet in workbook_root.findall("x:sheets/x:sheet", NS):
                name = sheet.attrib["name"]
                rel_id = sheet.attrib[f"{{{NS_REL}}}id"]
                target = rels[rel_id]
                target_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
                sheet_paths.append((name, target_path, sheet.attrib.get("state", "visible") == "visible"))

            style_formats = cls._read_number_formats(zf)

            cells: dict[CellKey, object] = {}
            formulas: dict[CellKey, str] = {}
            formula_kinds: dict[CellKey, str] = {}
            cell_visibility: dict[CellKey, bool] = {}
            number_formats: dict[CellKey, str] = {}
            merged_ranges: dict[str, tuple[tuple[str, str], ...]] = {}
            formula_regions: dict[str, tuple[tuple[str, str, str], ...]] = {}
            shared_formula_groups: dict[CellKey, str] = {}
            hidden_rows: dict[str, frozenset[int]] = {}
            hidden_columns_by_sheet: dict[
                str, tuple[tuple[int, int], ...]
            ] = {}
            metadata_complete = True
            sheet_visibility = {name: visible for name, _, visible in sheet_paths}
            for sheet_name, sheet_path, sheet_visible in sheet_paths:
                root = ET.fromstring(zf.read(sheet_path))
                sheet_merges: list[tuple[str, str]] = []
                for merged in root.findall("x:mergeCells/x:mergeCell", NS):
                    reference = merged.attrib.get("ref", "")
                    try:
                        start, end, _ = _forward_range_bounds(reference)
                    except ValueError:
                        metadata_complete = False
                        continue
                    if start == end:
                        metadata_complete = False
                        continue
                    sheet_merges.append((start, end))
                merged_ranges[sheet_name] = tuple(sheet_merges)
                hidden_columns_list: list[tuple[int, int]] = []
                for column in root.findall("x:cols/x:col", NS):
                    if column.attrib.get("hidden") not in {"1", "true"}:
                        continue
                    try:
                        start = int(column.attrib["min"])
                        end = int(column.attrib["max"])
                    except (KeyError, ValueError):
                        metadata_complete = False
                        continue
                    if start < 1 or end < start:
                        metadata_complete = False
                        continue
                    hidden_columns_list.append((start, end))
                hidden_columns = tuple(hidden_columns_list)
                hidden_columns_by_sheet[sheet_name] = hidden_columns
                sheet_hidden_rows: set[int] = set()
                for row in root.findall(".//x:sheetData/x:row", NS):
                    if row.attrib.get("hidden") not in {"1", "true"}:
                        continue
                    try:
                        row_number = int(row.attrib["r"])
                    except (KeyError, ValueError):
                        metadata_complete = False
                        continue
                    if row_number < 1:
                        metadata_complete = False
                        continue
                    sheet_hidden_rows.add(row_number)
                hidden_rows[sheet_name] = frozenset(sheet_hidden_rows)
                shared_formula_masters: dict[
                    str,
                    list[
                        tuple[
                            str,
                            str,
                            tuple[int, int, int, int] | None,
                        ]
                    ],
                ] = defaultdict(list)
                shared_formula_members: dict[str, set[str]] = defaultdict(set)
                pending_shared: list[tuple[str, str]] = []
                sheet_formula_regions: list[tuple[str, str, str]] = []
                for row in root.findall(".//x:sheetData/x:row", NS):
                    row_visible = row.attrib.get("hidden") not in {"1", "true"}
                    for cell in row.findall("x:c", NS):
                        address = plain_address(cell.attrib["r"])
                        key = (sheet_name, address)
                        column = parse_address(address).col
                        column_visible = not any(start <= column <= end for start, end in hidden_columns)
                        cell_visibility[key] = sheet_visible and row_visible and column_visible
                        style_index = int(cell.attrib.get("s", "0"))
                        if style_index in style_formats:
                            number_formats[key] = style_formats[style_index]
                        f_node = cell.find("x:f", NS)
                        if f_node is not None:
                            formula_text = f_node.text or ""
                            raw_shared_index = f_node.attrib.get("si")
                            shared_index = _shared_formula_index(raw_shared_index)
                            formula_kind = f_node.attrib.get("t", "normal")
                            formula_kinds[key] = formula_kind
                            if formula_kind == "shared":
                                if shared_index is None:
                                    metadata_complete = False
                                else:
                                    if address in shared_formula_members[shared_index]:
                                        metadata_complete = False
                                    shared_formula_members[shared_index].add(address)
                                    shared_formula_groups[key] = (
                                        f"{sheet_name}:{shared_index}"
                                    )
                            elif raw_shared_index is not None:
                                metadata_complete = False
                            region_reference = f_node.attrib.get("ref")
                            if formula_kind in {"array", "dataTable"}:
                                if not region_reference:
                                    metadata_complete = False
                                else:
                                    try:
                                        start, end, bounds = _forward_range_bounds(
                                            region_reference
                                        )
                                        anchor_address = parse_address(address)
                                        if (
                                            anchor_address.row != bounds[0]
                                            or anchor_address.col != bounds[2]
                                        ):
                                            raise ValueError("invalid formula region")
                                        sheet_formula_regions.append(
                                            (start, end, formula_kind)
                                        )
                                    except ValueError:
                                        metadata_complete = False
                            if formula_text:
                                formula = "=" + formula_text
                                formulas[key] = formula
                                if formula_kind == "shared" and shared_index is not None:
                                    bounds = None
                                    if not region_reference:
                                        metadata_complete = False
                                    else:
                                        try:
                                            _, _, bounds = _forward_range_bounds(
                                                region_reference
                                            )
                                        except ValueError:
                                            metadata_complete = False
                                    shared_formula_masters[shared_index].append(
                                        (address, formula, bounds)
                                    )
                            elif formula_kind == "shared" and shared_index is not None:
                                if region_reference is not None:
                                    metadata_complete = False
                                pending_shared.append((address, shared_index))
                        value = cls._cell_value(cell, shared_strings)
                        if value is not None:
                            cells[key] = value
                for address, shared_index in pending_shared:
                    masters = shared_formula_masters.get(shared_index, ())
                    if len(masters) != 1:
                        metadata_complete = False
                        continue
                    source_addr, source_formula, _ = masters[0]
                    key = (sheet_name, address)
                    formulas[key] = translate_formula(source_formula, source_addr, address)
                    formula_kinds[key] = "shared"
                for shared_index, members in shared_formula_members.items():
                    masters = shared_formula_masters.get(shared_index, ())
                    if len(masters) != 1:
                        metadata_complete = False
                        continue
                    master_address, _, bounds = masters[0]
                    if bounds is None:
                        metadata_complete = False
                        continue
                    row_start, row_end, column_start, column_end = bounds
                    expected_members = (row_end - row_start + 1) * (
                        column_end - column_start + 1
                    )
                    if len(members) != expected_members:
                        metadata_complete = False
                        continue
                    if master_address not in members or any(
                        not (
                            row_start <= parse_address(member).row <= row_end
                            and column_start
                            <= parse_address(member).col
                            <= column_end
                        )
                        for member in members
                    ):
                        metadata_complete = False
                formula_regions[sheet_name] = tuple(sheet_formula_regions)
        return cls(
            cells,
            formulas,
            source=str(path),
            cell_visibility=cell_visibility,
            number_formats=number_formats,
            sheet_visibility=sheet_visibility,
            merged_ranges=merged_ranges,
            formula_kinds=formula_kinds,
            formula_regions=formula_regions,
            shared_formula_groups=shared_formula_groups,
            hidden_rows=hidden_rows,
            hidden_columns=hidden_columns_by_sheet,
            header_partition_metadata_complete=metadata_complete,
        )

    @staticmethod
    def _read_number_formats(zf: zipfile.ZipFile) -> dict[int, str]:
        if "xl/styles.xml" not in zf.namelist():
            return {}
        root = ET.fromstring(zf.read("xl/styles.xml"))
        custom = {
            int(item.attrib["numFmtId"]): item.attrib.get("formatCode", "")
            for item in root.findall("x:numFmts/x:numFmt", NS)
        }
        result: dict[int, str] = {}
        for index, style in enumerate(root.findall("x:cellXfs/x:xf", NS)):
            format_id = int(style.attrib.get("numFmtId", "0"))
            result[index] = custom.get(format_id, BUILTIN_NUMBER_FORMATS.get(format_id, f"builtin:{format_id}"))
        return result

    @staticmethod
    def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in zf.namelist():
            return []
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        values: list[str] = []
        for si in root.findall("x:si", NS):
            values.append("".join(node.text or "" for node in si.findall(".//x:t", NS)))
        return values

    @staticmethod
    def _cell_value(cell: ET.Element, shared_strings: list[str]):
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//x:t", NS))
        v_node = cell.find("x:v", NS)
        if v_node is None or v_node.text is None:
            return None
        text = v_node.text
        if cell_type == "s":
            return shared_strings[int(text)]
        if cell_type == "b":
            return text == "1"
        if cell_type in ("str", "e"):
            return text
        try:
            number = float(text)
            return int(number) if number.is_integer() else number
        except ValueError:
            return text

    @property
    def formula_cells(self) -> list[CellKey]:
        return sorted(self.formulas)

    @property
    def visible_text_cells(self) -> dict[CellKey, str]:
        return {
            key: value
            for key, value in self.cells.items()
            if isinstance(value, str) and self.is_visible(key)
        }

    def is_visible(self, key: CellKey) -> bool:
        if not self.sheet_visibility.get(key[0], True):
            return False
        address = parse_address(key[1])
        if address.row in self.hidden_rows.get(key[0], ()):
            return False
        if any(
            start <= address.col <= end
            for start, end in self.hidden_columns.get(key[0], ())
        ):
            return False
        return self.cell_visibility.get(key, True)

    def is_merged(self, key: CellKey) -> bool:
        address = parse_address(key[1])
        return any(
            row_start <= address.row <= row_end
            and col_start <= address.col <= col_end
            for row_start, row_end, col_start, col_end in self._merged_bounds.get(
                key[0], ()
            )
        )

    def formula_kind(self, key: CellKey) -> str:
        address = parse_address(key[1])
        region_kinds = {
            kind
            for row_start, row_end, col_start, col_end, kind
            in self._formula_region_bounds.get(key[0], ())
            if row_start <= address.row <= row_end
            and col_start <= address.col <= col_end
        }
        if len(region_kinds) > 1:
            return "overlapping-special-formulas"
        if region_kinds:
            return next(iter(region_kinds))
        if key in self.shared_formula_groups:
            return "shared"
        return self.formula_kinds.get(key, "normal")

    def shared_formula_group(self, key: CellKey) -> str | None:
        return self.shared_formula_groups.get(key)

    def is_formula_derived(self, key: CellKey) -> bool:
        if key in self.formulas:
            return True
        address = parse_address(key[1])
        return any(
            row_start <= address.row <= row_end
            and col_start <= address.col <= col_end
            for row_start, row_end, col_start, col_end, _
            in self._formula_region_bounds.get(key[0], ())
        )

    def number_format(self, key: CellKey) -> str:
        return self.number_formats.get(key, "General")

    def ast(self, formula: str) -> Node:
        if formula not in self._ast_cache:
            self._ast_cache[formula] = parse_formula(formula)
        return self._ast_cache[formula]

    def _range_keys(
        self,
        sheet: str,
        start,
        end,
        *,
        extra_keys: Iterable[CellKey] = (),
    ) -> tuple[CellKey, ...]:
        row_min, row_max = sorted((start.row, end.row))
        column_min, column_max = sorted((start.col, end.col))
        entries = self._coordinate_index.get(sheet, ())
        index = bisect_left(entries, (row_min, 0, ("", "")))
        keys: set[CellKey] = set()
        for row, column, key in entries[index:]:
            if row > row_max:
                break
            if column_min <= column <= column_max:
                keys.add(key)
        for key in extra_keys:
            if key[0] != sheet or key in keys:
                continue
            address = parse_address(key[1])
            if (
                row_min <= address.row <= row_max
                and column_min <= address.col <= column_max
            ):
                keys.add(key)
        return tuple(
            sorted(
                keys,
                key=lambda key: (
                    parse_address(key[1]).row,
                    parse_address(key[1]).col,
                    key,
                ),
            )
        )

    def fingerprints(self, overrides: Mapping[CellKey, str] | None = None) -> dict[CellKey, str]:
        overrides = overrides or {}
        result: dict[CellKey, str] = {}
        for key in self.formula_cells:
            formula = overrides.get(key, self.formulas[key])
            try:
                result[key] = formula_fingerprint(formula, key[1])
            except FormulaSyntaxError:
                result[key] = "UNSUPPORTED:" + formula.replace(" ", "").upper()
        return result

    def dependency_graph(self, overrides: Mapping[CellKey, str] | None = None) -> DependencyGraph:
        overrides = overrides or {}
        precedents: dict[CellKey, set[CellKey]] = defaultdict(set)
        dependents: dict[CellKey, set[CellKey]] = defaultdict(set)
        for cell in self.formula_cells:
            formula = overrides.get(cell, self.formulas[cell])
            try:
                node = self.ast(formula)
            except FormulaSyntaxError:
                continue
            for item in iter_refs(node):
                if isinstance(item, Ref):
                    sheet = item.sheet or cell[0]
                    address = item.address.a1.replace("$", "")
                    source = (sheet, address)
                    precedents[cell].add(source)
                    dependents[source].add(cell)
                else:
                    sheet = item.start.sheet or item.end.sheet or cell[0]
                    for source in self._range_keys(
                        sheet,
                        item.start.address,
                        item.end.address,
                    ):
                        precedents[cell].add(source)
                        dependents[source].add(cell)
        for key in set(self.cells) | set(self.formulas):
            precedents.setdefault(key, set())
            dependents.setdefault(key, set())
        return DependencyGraph(dict(precedents), dict(dependents))

    def evaluate(
        self,
        overrides: Mapping[CellKey, str] | None = None,
        *,
        value_overrides: Mapping[CellKey, object] | None = None,
        targets: Iterable[CellKey] | None = None,
    ):
        overrides = overrides or {}
        value_overrides = value_overrides or {}
        overlap = set(value_overrides) & (set(self.formulas) | set(overrides))
        if overlap:
            labels = ", ".join(f"{sheet}!{address}" for sheet, address in sorted(overlap))
            raise ValueError(f"Value overrides cannot replace formula cells: {labels}")
        values: dict[CellKey, object] = {
            key: value
            for key, value in self.cells.items()
            if key not in self.formulas and key not in overrides
        }
        values.update(value_overrides)
        errors: dict[CellKey, str] = {}
        visiting: set[CellKey] = set()
        computed: set[CellKey] = set()

        def value_of(key: CellKey):
            if key in errors:
                raise ValueError(errors[key])
            if key in computed:
                return values[key]
            formula = overrides.get(key, self.formulas.get(key))
            if formula is None:
                return values.get(key, 0.0)
            # Cached XLSX values are not trusted for formulas; force evaluation.
            values.pop(key, None)
            if key in visiting:
                raise ValueError("Circular reference")
            visiting.add(key)
            try:
                result = eval_node(self.ast(formula), key[0])
                values[key] = result
                computed.add(key)
                return result
            except Exception as exc:  # evaluation errors are part of validation evidence
                errors[key] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                visiting.discard(key)

        def eval_node(node: Node, current_sheet: str):
            if isinstance(node, Number):
                return node.value
            if isinstance(node, Ref):
                return value_of((node.sheet or current_sheet, node.address.a1.replace("$", "")))
            if isinstance(node, Range):
                sheet = node.start.sheet or node.end.sheet or current_sheet
                return [
                    value_of(key)
                    for key in self._range_keys(
                        sheet,
                        node.start.address,
                        node.end.address,
                        extra_keys=value_overrides,
                    )
                ]
            if isinstance(node, Unary):
                val = numeric(eval_node(node.value, current_sheet))  # type: ignore[arg-type]
                return val if node.op == "+" else -val
            if isinstance(node, Binary):
                left = eval_node(node.left, current_sheet)  # type: ignore[arg-type]
                right = eval_node(node.right, current_sheet)  # type: ignore[arg-type]
                if node.op == "+":
                    return numeric(left) + numeric(right)
                if node.op == "-":
                    return numeric(left) - numeric(right)
                if node.op == "*":
                    return numeric(left) * numeric(right)
                if node.op == "/":
                    denom = numeric(right)
                    if abs(denom) < 1e-12:
                        raise ZeroDivisionError("division by zero")
                    return numeric(left) / denom
                if node.op == "^":
                    return numeric(left) ** numeric(right)
                if node.op == "=":
                    return left == right
                if node.op == "<>":
                    return left != right
                if node.op == "<":
                    return numeric(left) < numeric(right)
                if node.op == ">":
                    return numeric(left) > numeric(right)
                if node.op == "<=":
                    return numeric(left) <= numeric(right)
                if node.op == ">=":
                    return numeric(left) >= numeric(right)
                raise ValueError(f"Unsupported operator {node.op}")
            if isinstance(node, Func):
                if node.name == "IF":
                    if len(node.args) not in (2, 3):
                        raise ValueError("IF expects two or three arguments")
                    condition = eval_node(node.args[0], current_sheet)  # type: ignore[arg-type]
                    if bool(condition):
                        return eval_node(node.args[1], current_sheet)  # type: ignore[arg-type]
                    if len(node.args) == 3:
                        return eval_node(node.args[2], current_sheet)  # type: ignore[arg-type]
                    return False
                args = [eval_node(arg, current_sheet) for arg in node.args]  # type: ignore[arg-type]
                flat = [numeric(value) for value in flatten_values(args) if value not in (None, "")]
                if node.name == "SUM":
                    return sum(flat)
                if node.name == "AVERAGE":
                    if not flat:
                        raise ZeroDivisionError("AVERAGE of empty set")
                    return statistics.fmean(flat)
                if node.name == "MIN":
                    return min(flat)
                if node.name == "MAX":
                    return max(flat)
                if node.name == "COUNT":
                    return len(flat)
                raise ValueError(f"Unsupported function {node.name}")
            raise TypeError(type(node))

        requested = self.formula_cells if targets is None else tuple(dict.fromkeys(targets))
        for key in requested:
            try:
                value_of(key)
            except Exception:
                pass
        return values, errors

    def changed_formula_cells(self, other: WorkbookModel, tolerance: float = 1e-9) -> set[CellKey]:
        left, left_errors = self.evaluate()
        right, right_errors = other.evaluate()
        changed: set[CellKey] = set()
        for key in set(self.formulas) | set(other.formulas):
            if key in left_errors or key in right_errors:
                if left_errors.get(key) != right_errors.get(key):
                    changed.add(key)
                continue
            a, b = left.get(key), right.get(key)
            try:
                if not math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance):
                    changed.add(key)
            except (TypeError, ValueError):
                if a != b:
                    changed.add(key)
        return changed
