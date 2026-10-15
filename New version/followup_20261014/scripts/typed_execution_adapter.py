"""Typed, conservative execution for the supported formula subset.

This adapter is execution evidence only.  It does not infer business intent or
authorize a repair.  In particular, an OOXML error cell remains an error when a
formula references it; it is never converted to the literal string ``#VALUE!``.
"""

from __future__ import annotations

import math
import posixpath
import statistics
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from formulaguard.formula import (
    Binary,
    FormulaSyntaxError,
    Func,
    Node,
    Number,
    Range,
    Ref,
    Unary,
    flatten_values,
    parse_formula,
)
from formulaguard.workbook import CellKey, WorkbookModel

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


@dataclass(frozen=True)
class ExcelError:
    """An Excel error token, distinct from a text cell containing the same text."""

    code: str


class AdapterFailure(ValueError):
    """A stable failure category for unsupported or invalid execution."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//x:t", NS))
            for item in root.findall("x:si", NS)]


def load_typed_inputs(path: str | Path) -> dict[CellKey, object]:
    """Read non-formula OOXML cells while preserving error and text types.

    Formula cells are deliberately omitted.  Their values must be produced by
    the adapter rather than by a potentially stale workbook cache.
    """
    result: dict[CellKey, object] = {}
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relations = {item.attrib["Id"]: item.attrib["Target"]
                     for item in rel_root}
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        for sheet in workbook.findall("x:sheets/x:sheet", NS):
            target = relations[sheet.attrib[REL_ID]]
            part = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            root = ET.fromstring(archive.read(part))
            name = sheet.attrib["name"]
            for cell in root.findall("x:sheetData/x:row/x:c", NS):
                if cell.find("x:f", NS) is not None:
                    continue
                address = cell.attrib["r"]
                kind = cell.attrib.get("t", "n")
                if kind == "inlineStr":
                    result[(name, address)] = "".join(
                        node.text or "" for node in cell.findall(".//x:t", NS))
                    continue
                value = cell.find("x:v", NS)
                text = value.text if value is not None else None
                if text is None:
                    result[(name, address)] = None
                elif kind == "e":
                    result[(name, address)] = ExcelError(text)
                elif kind == "b":
                    result[(name, address)] = text == "1"
                elif kind == "s":
                    try:
                        result[(name, address)] = shared[int(text)]
                    except (ValueError, IndexError) as exc:
                        raise AdapterFailure("invalid_shared_string") from exc
                elif kind == "str":
                    result[(name, address)] = text
                else:
                    try:
                        number = float(text)
                    except ValueError as exc:
                        raise AdapterFailure("invalid_numeric_cell") from exc
                    result[(name, address)] = int(number) if number.is_integer() else number
    return result


def _error(value: object) -> ExcelError | None:
    return value if isinstance(value, ExcelError) else None


def _numeric(value: object) -> float | ExcelError:
    if isinstance(value, ExcelError):
        return value
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return ExcelError("#NUM!")
        return float(value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return ExcelError("#VALUE!")
    return parsed if math.isfinite(parsed) else ExcelError("#NUM!")


def _first_error(values: list[object]) -> ExcelError | None:
    return next((value for value in values if isinstance(value, ExcelError)), None)


class TypedExecutionAdapter:
    """Evaluate a WorkbookModel with typed OOXML inputs and Excel-like errors."""

    VERSION = "typed-execution-adapter-dev1"

    def __init__(self, model: WorkbookModel, typed_inputs: Mapping[CellKey, object]):
        self.model = model
        self.inputs = dict(typed_inputs)
        self.values: dict[CellKey, object] = {
            key: value for key, value in self.inputs.items() if key not in model.formulas
        }
        self.errors: dict[CellKey, str] = {}
        self._visiting: set[CellKey] = set()
        self._computed: set[CellKey] = set()

    @classmethod
    def from_xlsx(cls, path: str | Path) -> "TypedExecutionAdapter":
        model = WorkbookModel.from_xlsx(path)
        return cls(model, load_typed_inputs(path))

    def _value_of(self, key: CellKey) -> object:
        if key in self._computed:
            return self.values[key]
        if key in self._visiting:
            raise AdapterFailure("circular_reference")
        formula = self.model.formulas.get(key)
        if formula is None:
            return self.values.get(key, 0.0)
        self._visiting.add(key)
        try:
            value = self._eval_node(parse_formula(formula), key[0])
            if isinstance(value, ExcelError):
                self.errors[key] = value.code
            self.values[key] = value
            self._computed.add(key)
            return value
        except AdapterFailure as exc:
            self.errors[key] = exc.code
            raise
        except (FormulaSyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
            self.errors[key] = type(exc).__name__ + ": " + str(exc)
            raise AdapterFailure("execution_error") from exc
        finally:
            self._visiting.discard(key)

    def _eval_node(self, node: Node, current_sheet: str) -> object:
        if isinstance(node, Number):
            return node.value
        if isinstance(node, Ref):
            return self._value_of((node.sheet or current_sheet, node.address.a1.replace("$", "")))
        if isinstance(node, Range):
            sheet = node.start.sheet or node.end.sheet or current_sheet
            return [self._value_of(key) for key in self.model._range_keys(
                sheet, node.start.address, node.end.address)]
        if isinstance(node, Unary):
            value = _numeric(self._eval_node(node.value, current_sheet))
            return value if isinstance(value, ExcelError) else (value if node.op == "+" else -value)
        if isinstance(node, Binary):
            left = self._eval_node(node.left, current_sheet)
            right = self._eval_node(node.right, current_sheet)
            error = _first_error([left, right])
            if error is not None:
                return error
            if node.op in ("=", "<>"):
                return left == right if node.op == "=" else left != right
            if node.op in ("<", ">", "<=", ">="):
                lhs, rhs = _numeric(left), _numeric(right)
                error = _first_error([lhs, rhs])
                if error is not None:
                    return error
                return {"<": lhs < rhs, ">": lhs > rhs,
                        "<=": lhs <= rhs, ">=": lhs >= rhs}[node.op]
            lhs, rhs = _numeric(left), _numeric(right)
            error = _first_error([lhs, rhs])
            if error is not None:
                return error
            if node.op == "+": return lhs + rhs
            if node.op == "-": return lhs - rhs
            if node.op == "*": return lhs * rhs
            if node.op == "/": return ExcelError("#DIV/0!") if abs(rhs) < 1e-12 else lhs / rhs
            if node.op == "^":
                try:
                    value = lhs ** rhs
                except (OverflowError, ValueError):
                    return ExcelError("#NUM!")
                return value if math.isfinite(value) else ExcelError("#NUM!")
            return ExcelError("#VALUE!")
        if isinstance(node, Func):
            if node.name == "IF":
                if len(node.args) not in (2, 3):
                    return ExcelError("#VALUE!")
                condition = self._eval_node(node.args[0], current_sheet)
                if isinstance(condition, ExcelError):
                    return condition
                branch = node.args[1] if bool(condition) else (node.args[2] if len(node.args) == 3 else None)
                return False if branch is None else self._eval_node(branch, current_sheet)
            args = [self._eval_node(arg, current_sheet) for arg in node.args]
            error = _first_error(args)
            if error is not None:
                return error
            if node.name == "IFERROR":
                return args[0] if not isinstance(args[0], ExcelError) else args[1]
            if node.name in {"AND", "OR"}:
                booleans = [bool(value) for value in args]
                return all(booleans) if node.name == "AND" else any(booleans)
            flat = [value for value in flatten_values(args) if value not in (None, "")]
            numeric = [_numeric(value) for value in flat]
            error = _first_error(numeric)
            if error is not None:
                return error
            numbers = [float(value) for value in numeric]
            if node.name == "SUM": return sum(numbers)
            if node.name == "AVERAGE": return statistics.fmean(numbers) if numbers else ExcelError("#DIV/0!")
            if node.name == "MIN": return min(numbers) if numbers else ExcelError("#VALUE!")
            if node.name == "MAX": return max(numbers) if numbers else ExcelError("#VALUE!")
            if node.name == "COUNT": return len(numbers)
            return ExcelError("#NAME?")
        return ExcelError("#VALUE!")

    def evaluate(self, targets: tuple[CellKey, ...] | None = None) -> tuple[dict[CellKey, object], dict[CellKey, str]]:
        requested = self.model.formula_cells if targets is None else tuple(dict.fromkeys(targets))
        for key in requested:
            try:
                self._value_of(key)
            except AdapterFailure:
                pass
        return dict(self.values), dict(self.errors)


def typed_value(value: object) -> dict[str, object]:
    """Serialize a result without collapsing errors into text."""
    if isinstance(value, ExcelError):
        return {"kind": "error", "error": value.code}
    if isinstance(value, bool):
        return {"kind": "boolean", "value": value}
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return {"kind": "number", "value": value}
    if isinstance(value, str):
        return {"kind": "text", "value": value}
    if value is None:
        return {"kind": "missing"}
    return {"kind": "unhandled", "value": repr(value)}
