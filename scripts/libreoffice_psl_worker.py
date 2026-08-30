"""JSON-lines UNO worker used by FormulaGuard's LibreOffice fallback."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


def property_value(name: str, value: object) -> PropertyValue:
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def connect(port: int, timeout: float = 30.0):
    context = uno.getComponentContext()
    resolver = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", context,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            remote = resolver.resolve(
                f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
            )
            desktop = remote.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", remote,
            )
            return desktop
        except Exception:
            time.sleep(0.10)
    raise RuntimeError("Timed out connecting to isolated LibreOffice process")


def cell_for(document, sheet: str, address: str):
    return document.Sheets.getByName(sheet).getCellRangeByName(address)


def read_cells(document, formula_cells: list[list[str]]) -> dict[str, object]:
    values = []
    errors = []
    for sheet, address in formula_cells:
        cell = cell_for(document, sheet, address)
        error = int(cell.getError())
        if error:
            errors.append([sheet, address, f"libreoffice_error:{error}"])
            continue
        value = float(cell.Value)
        if value == 0.0 and cell.String and cell.String != "0":
            values.append([sheet, address, str(cell.String)])
        else:
            values.append([sheet, address, value])
    return {"values": values, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--soffice", type=Path, required=True)
    args = parser.parse_args()
    profile = Path(tempfile.mkdtemp(prefix="formulaguard-lo-profile-"))
    port = free_port()
    command = [
        str(args.soffice), "--headless", "--nologo", "--nodefault",
        "--nofirststartwizard", "--norestore", "--nolockcheck",
        f"-env:UserInstallation={uno.systemPathToFileUrl(str(profile))}",
        f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ServiceManager",
    ]
    office = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    document = None
    try:
        desktop = connect(port)
        document = desktop.loadComponentFromURL(
            uno.systemPathToFileUrl(str(args.workbook.resolve())),
            "_blank",
            0,
            (
                property_value("Hidden", True),
                property_value("ReadOnly", False),
                property_value("MacroExecutionMode", 0),
                property_value("UpdateDocMode", 0),
            ),
        )
        if document is None:
            raise RuntimeError("LibreOffice could not open workbook")
        version = subprocess.run(
            [str(args.soffice), "--version"], capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        print(json.dumps({"status": "ready", "engine_version": version}), flush=True)
        original_inputs: dict[tuple[str, str], float] = {}
        original_formulas: dict[tuple[str, str], str] = {}
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("command") == "close":
                break
            if request.get("command") != "evaluate":
                print(json.dumps({"status": "error", "error": "unknown command"}), flush=True)
                continue
            try:
                formula_cells = request["formula_cells"]
                for sheet, address in formula_cells:
                    key = (sheet, address)
                    if key not in original_formulas:
                        original_formulas[key] = str(cell_for(document, sheet, address).Formula)
                    cell_for(document, sheet, address).Formula = original_formulas[key]
                scenario_cells = {
                    (sheet, address)
                    for row in request["scenarios"]
                    for sheet, address, _ in row["value_overrides"]
                }
                for sheet, address in scenario_cells:
                    key = (sheet, address)
                    if key not in original_inputs:
                        original_inputs[key] = float(cell_for(document, sheet, address).Value)
                    cell_for(document, sheet, address).Value = original_inputs[key]
                for sheet, address, formula in request.get("formula_overrides", []):
                    cell_for(document, sheet, address).Formula = formula
                document.calculateAll()
                base = read_cells(document, formula_cells)
                rows = []
                for scenario in request["scenarios"]:
                    for sheet, address, value in scenario["value_overrides"]:
                        cell_for(document, sheet, address).Value = float(value)
                    document.calculateAll()
                    rows.append(read_cells(document, formula_cells))
                print(json.dumps({"status": "ok", "base": base, "scenarios": rows}), flush=True)
            except Exception as exc:
                print(json.dumps({
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }), flush=True)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}), flush=True)
        return 1
    finally:
        if document is not None:
            try:
                document.close(True)
            except Exception:
                try:
                    document.dispose()
                except Exception:
                    pass
        office.terminate()
        try:
            office.wait(timeout=10)
        except subprocess.TimeoutExpired:
            office.kill()
            office.wait(timeout=5)
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
