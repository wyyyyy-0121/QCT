"""Frozen VEnron V1 explicit-error and exact-reversion proxy primitives."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping, Sequence

import openpyxl


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
    workbook = openpyxl.load_workbook(
        path,
        read_only=True,
        data_only=True,
        keep_links=False,
    )
    errors: list[dict[str, str]] = []
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    key = (sheet.title, cell.coordinate)
                    if key not in formula_keys:
                        continue
                    value = str(cell.value).upper() if cell.value is not None else ""
                    if value in EXPLICIT_ERROR_TOKENS:
                        errors.append({
                            "sheet": sheet.title,
                            "address": cell.coordinate,
                            "error": value,
                        })
    finally:
        workbook.close()
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
