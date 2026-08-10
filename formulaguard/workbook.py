"""Read XLSX packages, build dependency graphs, and evaluate supported formulas."""

from __future__ import annotations

import math
import posixpath
import statistics
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from .a1 import Address, iter_rect, parse_address, plain_address
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
    def __init__(self, cells: Mapping[CellKey, object], formulas: Mapping[CellKey, str], source: str = ""):
        self.cells = dict(cells)
        self.formulas = {key: value if value.startswith("=") else "=" + value for key, value in formulas.items()}
        self.source = source
        self._ast_cache: dict[str, Node] = {}

    @classmethod
    def from_cells(cls, cells: Mapping[CellKey, object], formulas: Mapping[CellKey, str]):
        return cls(cells, formulas, source="in-memory")

    @classmethod
    def from_xlsx(cls, path: str | Path) -> "WorkbookModel":
        path = Path(path)
        with zipfile.ZipFile(path) as zf:
            shared_strings = cls._read_shared_strings(zf)
            workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
            rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rels = {
                rel.attrib["Id"]: rel.attrib["Target"]
                for rel in rel_root.findall(f"{{{NS_PKG_REL}}}Relationship")
            }
            sheet_paths: list[tuple[str, str]] = []
            for sheet in workbook_root.findall("x:sheets/x:sheet", NS):
                name = sheet.attrib["name"]
                rel_id = sheet.attrib[f"{{{NS_REL}}}id"]
                target = rels[rel_id]
                target_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
                sheet_paths.append((name, target_path))

            cells: dict[CellKey, object] = {}
            formulas: dict[CellKey, str] = {}
            for sheet_name, sheet_path in sheet_paths:
                root = ET.fromstring(zf.read(sheet_path))
                shared_formulas: dict[str, tuple[str, str]] = {}
                pending_shared: list[tuple[str, str]] = []
                for cell in root.findall(".//x:sheetData/x:row/x:c", NS):
                    address = plain_address(cell.attrib["r"])
                    f_node = cell.find("x:f", NS)
                    if f_node is not None:
                        formula_text = f_node.text or ""
                        shared_index = f_node.attrib.get("si")
                        if formula_text:
                            formula = "=" + formula_text
                            formulas[(sheet_name, address)] = formula
                            if shared_index is not None:
                                shared_formulas[shared_index] = (address, formula)
                        elif shared_index is not None:
                            pending_shared.append((address, shared_index))
                    value = cls._cell_value(cell, shared_strings)
                    if value is not None:
                        cells[(sheet_name, address)] = value
                for address, shared_index in pending_shared:
                    if shared_index not in shared_formulas:
                        continue
                    source_addr, source_formula = shared_formulas[shared_index]
                    formulas[(sheet_name, address)] = translate_formula(source_formula, source_addr, address)
        return cls(cells, formulas, source=str(path))

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

    def ast(self, formula: str) -> Node:
        if formula not in self._ast_cache:
            self._ast_cache[formula] = parse_formula(formula)
        return self._ast_cache[formula]

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
                    for address in iter_rect(item.start.address, item.end.address):
                        source = (sheet, address)
                        precedents[cell].add(source)
                        dependents[source].add(cell)
        for key in set(self.cells) | set(self.formulas):
            precedents.setdefault(key, set())
            dependents.setdefault(key, set())
        return DependencyGraph(dict(precedents), dict(dependents))

    def evaluate(self, overrides: Mapping[CellKey, str] | None = None):
        overrides = overrides or {}
        values: dict[CellKey, object] = dict(self.cells)
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
                return self.cells.get(key, 0.0)
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
                return [value_of((sheet, address)) for address in iter_rect(node.start.address, node.end.address)]
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
                args = [eval_node(arg, current_sheet) for arg in node.args]  # type: ignore[arg-type]
                if node.name == "IF":
                    if len(args) not in (2, 3):
                        raise ValueError("IF expects two or three arguments")
                    return args[1] if bool(args[0]) else (args[2] if len(args) == 3 else False)
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

        for key in self.formula_cells:
            try:
                value_of(key)
            except Exception:
                pass
        return values, errors

    def changed_formula_cells(self, other: "WorkbookModel", tolerance: float = 1e-9) -> set[CellKey]:
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
