"""Dependency-light protocol types shared by V5-PSL evaluator backends."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .workbook import CellKey


class OfficeScenario(Protocol):
    scenario_id: str
    value_overrides: Mapping[CellKey, float | int]


@dataclass(frozen=True)
class OfficeEvaluation:
    values: Mapping[CellKey, object]
    errors: Mapping[CellKey, str]
