"""Frozen VEnron V1 explicit-error and exact-reversion proxy primitives."""

from __future__ import annotations

import hashlib
import posixpath
import zipfile
from pathlib import Path
from typing import Mapping, Sequence
from xml.etree import ElementTree

EXPLICIT_ERROR_TOKENS = frozenset({
    "#NULL!",
    "#DIV/0!",
    "#VALUE!",
    "#REF!",
    "#NAME?",
    "#NUM!",
    "#N/A",
    "#GETTING_DATA",
    "#SPILL!",
    "#CALC!",
})
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def formula_map(profile: Mapping[str, object]) -> dict[tuple[str, str], str]:
    rows = profile.get("formulas")
    if not isinstance(rows, list):
        raise ValueError("VEnron formula profile has no formula list")
    result: dict[tuple[str, str], str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("VEnron formula profile row is malformed")
        key = (str(row.get("sheet", "")), str(row.get("address", "")))
        formula = str(row.get("formula", "")).strip()
        if not all(key) or not formula or key in result:
            raise ValueError("VEnron formula profile key is invalid or duplicated")
        result[key] = formula
    return result


def direct_formula_edits(
    previous: Mapping[str, object], current: Mapping[str, object]
) -> list[dict[str, str]]:
    left = formula_map(previous)
    right = formula_map(current)
    keys = sorted(key for key in set(left) & set(right) if left[key] != right[key])
    return [
        {
            "sheet": key[0],
            "address": key[1],
            "previous_formula": left[key],
            "current_formula": right[key],
        }
        for key in keys
    ]


def explicit_formula_errors(
    path: Path,
    formula_profile: Mapping[str, object],
) -> list[dict[str, str]]:
    formula_keys = set(formula_map(formula_profile))
    keys_by_sheet: dict[str, list[str]] = {}
    for sheet, address in sorted(formula_keys):
        keys_by_sheet.setdefault(sheet, []).append(address)
    errors: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        members = set(archive.namelist())
        workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relations_root = ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relations_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
            if "Id" in relation.attrib and "Target" in relation.attrib
        }
        sheet_members: dict[str, str] = {}
        for sheet in workbook_root.findall(f".//{{{MAIN_NS}}}sheet"):
            name = sheet.attrib.get("name", "")
            relation_id = sheet.attrib.get(f"{{{DOCUMENT_REL_NS}}}id", "")
            target = targets.get(relation_id, "").replace("\\", "/")
            if target.startswith("/"):
                member = target.lstrip("/")
            else:
                member = posixpath.normpath(posixpath.join("xl", target))
            if (
                not name
                or not member.startswith("xl/worksheets/")
                or member not in members
            ):
                raise ValueError("cached VEnron workbook has an unsafe sheet relation")
            sheet_members[name] = member
        if not set(keys_by_sheet).issubset(sheet_members):
            missing = sorted(set(keys_by_sheet) - set(sheet_members))
            raise ValueError(f"cached VEnron workbook lost sheets: {missing!r}")

        cell_tag = f"{{{MAIN_NS}}}c"
        value_tag = f"{{{MAIN_NS}}}v"
        for sheet_name, addresses in keys_by_sheet.items():
            wanted = set(addresses)
            with archive.open(sheet_members[sheet_name]) as handle:
                for _, cell in ElementTree.iterparse(handle, events=("end",)):
                    if cell.tag != cell_tag:
                        continue
                    address = cell.attrib.get("r", "")
                    if address in wanted and cell.attrib.get("t") == "e":
                        value_node = cell.find(value_tag)
                        value = (
                            value_node.text.upper()
                            if value_node is not None and value_node.text
                            else ""
                        )
                        if value in EXPLICIT_ERROR_TOKENS:
                            errors.append({
                                "sheet": sheet_name,
                                "address": address,
                                "error": value,
                            })
                    cell.clear()
    errors.sort(key=lambda row: (row["sheet"], row["address"], row["error"]))
    return errors


def error_key_set(rows: Sequence[Mapping[str, object]]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("sheet", "")), str(row.get("address", "")))
        if not all(key) or str(row.get("error", "")) not in EXPLICIT_ERROR_TOKENS:
            raise ValueError("VEnron explicit-error profile row is invalid")
        result.add(key)
    return result


def exact_reversions(
    previous: Mapping[str, object],
    current: Mapping[str, object],
    future_profiles: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    edits = direct_formula_edits(previous, current)
    future_maps = [formula_map(profile) for profile in future_profiles[:3]]
    reversions: list[dict[str, object]] = []
    for edit in edits:
        key = (edit["sheet"], edit["address"])
        before = edit["previous_formula"]
        observed = edit["current_formula"]
        for horizon, future in enumerate(future_maps, 1):
            formula = future.get(key)
            if formula is None:
                break
            if formula == observed:
                continue
            if formula == before:
                reversions.append({
                    "sheet": key[0],
                    "address": key[1],
                    "horizon": horizon,
                    "previous_formula": before,
                    "intermediate_formula": observed,
                })
            break
    reversions.sort(key=lambda row: (str(row["sheet"]), str(row["address"])))
    return reversions


def error_key_hash(rows: Sequence[Mapping[str, object]]) -> str:
    keys = sorted((str(row.get("sheet", "")), str(row.get("address", ""))) for row in rows)
    return hashlib.sha256(
        "\n".join(f"{sheet}\0{address}" for sheet, address in keys).encode("utf-8")
    ).hexdigest()
