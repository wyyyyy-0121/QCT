"""Persistent, macro-disabled LibreOffice evaluation bridge for V5-PSL."""

from __future__ import annotations

import json
import select
import shutil
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from .v5_psl_types import OfficeEvaluation, OfficeScenario
from .workbook import CellKey, WorkbookModel


class LibreOfficeUnavailable(RuntimeError):
    pass


class LibreOfficeEvaluator:
    """Keep one isolated Calc process alive for all probes of one workbook."""

    def __init__(self, model: WorkbookModel, *, timeout_seconds: float = 180.0):
        source = Path(model.source)
        if not source.is_file() or source.suffix.lower() not in {".xlsx", ".xlsm", ".ods", ".xls"}:
            raise LibreOfficeUnavailable("Workbook source is not a supported local file")
        system_python = Path("/usr/bin/python3")
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not system_python.is_file() or not soffice:
            raise LibreOfficeUnavailable("python3-uno or LibreOffice is unavailable")
        root = Path(__file__).resolve().parents[1]
        worker = root / "scripts" / "libreoffice_psl_worker.py"
        self.timeout_seconds = float(timeout_seconds)
        self.process = subprocess.Popen(
            [
                str(system_python), str(worker),
                "--workbook", str(source.resolve()),
                "--soffice", str(Path(soffice).resolve()),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        ready = self._read_response()
        if ready.get("status") != "ready":
            self.close()
            raise LibreOfficeUnavailable(str(ready.get("error", "LibreOffice worker failed to start")))
        self.engine_version = str(ready.get("engine_version", "LibreOffice"))

    def _read_response(self) -> dict[str, object]:
        if self.process.stdout is None:
            raise LibreOfficeUnavailable("LibreOffice worker has no stdout")
        readable, _, _ = select.select([self.process.stdout], [], [], self.timeout_seconds)
        if not readable:
            self.close()
            raise LibreOfficeUnavailable("LibreOffice worker timed out")
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise LibreOfficeUnavailable(f"LibreOffice worker stopped: {stderr.strip()}")
        payload = json.loads(line)
        if payload.get("status") == "error":
            raise LibreOfficeUnavailable(str(payload.get("error", "LibreOffice evaluation failed")))
        return payload

    def evaluate(
        self,
        model: WorkbookModel,
        scenarios: Sequence[OfficeScenario],
        formula_overrides: Mapping[CellKey, str] | None = None,
    ) -> tuple[OfficeEvaluation, list[OfficeEvaluation]]:
        if self.process.stdin is None:
            raise LibreOfficeUnavailable("LibreOffice worker has no stdin")
        request = {
            "command": "evaluate",
            "formula_cells": [[sheet, address] for sheet, address in model.formula_cells],
            "formula_overrides": [
                [sheet, address, formula]
                for (sheet, address), formula in sorted((formula_overrides or {}).items())
            ],
            "scenarios": [
                {
                    "scenario_id": row.scenario_id,
                    "value_overrides": [
                        [sheet, address, value]
                        for (sheet, address), value in sorted(row.value_overrides.items())
                    ],
                }
                for row in scenarios
            ],
        }
        self.process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        response = self._read_response()

        def decode(row: Mapping[str, object]) -> OfficeEvaluation:
            values = {
                (str(sheet), str(address)): value
                for sheet, address, value in row.get("values", [])  # type: ignore[union-attr]
            }
            errors = {
                (str(sheet), str(address)): str(error)
                for sheet, address, error in row.get("errors", [])  # type: ignore[union-attr]
            }
            return OfficeEvaluation(values=values, errors=errors)

        base = decode(response["base"])  # type: ignore[arg-type]
        rows = [decode(row) for row in response.get("scenarios", [])]  # type: ignore[arg-type]
        if len(rows) != len(scenarios):
            raise LibreOfficeUnavailable("LibreOffice returned an incomplete scenario batch")
        return base, rows

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write('{"command":"close"}\n')
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def __enter__(self) -> "LibreOfficeEvaluator":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


__all__ = ["LibreOfficeEvaluator", "LibreOfficeUnavailable"]
