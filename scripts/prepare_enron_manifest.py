from __future__ import annotations

import argparse
import csv
import json
import posixpath
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.a1 import iter_rect, parse_address


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"x": NS_MAIN, "r": NS_REL}


def read_properties(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(".//x:t", NS))
        for item in root.findall("x:si", NS)
    ]


def read_overview(path: Path) -> list[dict[str, str]]:
    """Read the 36 event rows from the official enron-errors.xlsx overview."""
    with zipfile.ZipFile(path) as archive:
        strings = _shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rels = {
            node.attrib["Id"]: node.attrib["Target"]
            for node in relationships.findall(
                "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
            )
        }
        sheet = workbook.find("x:sheets/x:sheet", NS)
        if sheet is None:
            raise ValueError("overview workbook has no worksheet")
        target = rels[sheet.attrib[f"{{{NS_REL}}}id"]]
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
            posixpath.join("xl", target)
        )
        root = ET.fromstring(archive.read(sheet_path))
        table: dict[tuple[int, int], str] = {}
        for cell in root.findall(".//x:sheetData/x:row/x:c", NS):
            address = parse_address(cell.attrib["r"])
            value = cell.find("x:v", NS)
            if value is None or value.text is None:
                continue
            text = strings[int(value.text)] if cell.attrib.get("t") == "s" else value.text
            table[(address.row, address.col)] = text
    headers = [table.get((5, col), "") for col in range(1, 14)]
    events = []
    for row in range(6, 42):
        values = [table.get((row, col), "") for col in range(1, 14)]
        if values[0]:
            events.append(dict(zip(headers, values)))
    return events


def expand_fault_spec(spec: str) -> set[str] | None:
    """Expand an overview A1/range list; return None for abbreviated 'etc.' specs."""
    if not spec or "etc" in spec.casefold():
        return None
    addresses: set[str] = set()
    for token in spec.split(";"):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            start, end = (part.strip() for part in token.split(":", 1))
            addresses.update(iter_rect(parse_address(start), parse_address(end)))
        else:
            addresses.add(parse_address(token).a1.replace("$", ""))
    return addresses


def sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("xl/workbook.xml"))
    return [node.attrib["name"] for node in root.findall("x:sheets/x:sheet", NS)]


def property_coordinate(value: str, sheets: list[str]) -> str:
    match = re.fullmatch(r"(\d+)!([A-Za-z]{1,3})!([1-9]\d*)", value.strip())
    if not match:
        raise ValueError(f"unsupported property coordinate: {value}")
    sheet_index = int(match.group(1))
    if sheet_index >= len(sheets):
        raise ValueError(f"sheet index {sheet_index} is outside workbook with {len(sheets)} sheets")
    return f"{sheets[sheet_index]}!{match.group(2).upper()}{match.group(3)}"


def locate_workbook(workbooks: Path, excel_sheet: str, property_stem: str) -> Path | None:
    requested = Path(excel_sheet.replace("\\", "/")).name
    names = [requested, *[property_stem + suffix for suffix in (".xlsx", ".xlsm", ".xls")]]
    indexed = {path.name.lower(): path for path in workbooks.rglob("*") if path.is_file()}
    return next((indexed[name.lower()] for name in names if name.lower() in indexed), None)


def convert_xls(source: Path, converted: Path, libreoffice: str | None) -> tuple[Path | None, str]:
    if source.suffix.lower() != ".xls":
        return source, ""
    if not libreoffice:
        return None, "legacy_xls_requires_libreoffice_conversion"
    converted.mkdir(parents=True, exist_ok=True)
    target = converted / f"{source.stem}.xlsx"
    if target.is_file():
        return target, ""
    completed = subprocess.run(
        [libreoffice, "--headless", "--convert-to", "xlsx", "--outdir", str(converted), str(source)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 or not target.is_file():
        return None, f"libreoffice_conversion_failed:{completed.returncode}"
    return target, ""


def relative(path: Path, base: Path) -> str:
    return Path(posixpath.relpath(path.resolve().as_posix(), base.resolve().as_posix())).as_posix()


def main():
    parser = argparse.ArgumentParser(description="Build an auditable Enron manifest from workbooks and properties files")
    parser.add_argument("--workbooks", type=Path, required=True)
    parser.add_argument("--properties", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--converted", type=Path)
    parser.add_argument("--libreoffice")
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--expected-faults", type=int, default=36)
    args = parser.parse_args()

    converted = args.converted or args.output.parent / "converted"
    overview_path = args.overview or args.properties.parent / "enron-errors.xlsx"
    events = read_overview(overview_path)
    property_files = sorted(args.properties.rglob("*.properties"))
    property_cells: dict[int, list[str]] = {}
    usable_workbooks: dict[int, Path] = {}
    workbook_reasons: dict[int, str] = {}
    for property_file in property_files:
        props = read_properties(property_file)
        spreadsheet_number = int(property_file.stem)
        faulty = sorted(
            ((key, value) for key, value in props.items() if key.startswith("FAULTY_CELLS_")),
            key=lambda item: int(item[0].rsplit("_", 1)[-1]),
        )
        workbook = locate_workbook(args.workbooks, props.get("EXCEL_SHEET", ""), property_file.stem)
        usable, base_reason = (None, "workbook_not_found") if workbook is None else convert_xls(
            workbook, converted, args.libreoffice
        )
        sheets = []
        if usable:
            try:
                sheets = sheet_names(usable)
            except Exception as exc:
                base_reason = f"workbook_load_error:{type(exc).__name__}"
                usable = None
        labels = []
        if usable:
            for _, coordinate in faulty:
                try:
                    labels.append(property_coordinate(coordinate, sheets))
                except Exception as exc:
                    base_reason = f"coordinate_error:{exc}"
        property_cells[spreadsheet_number] = labels
        if usable:
            usable_workbooks[spreadsheet_number] = usable
        workbook_reasons[spreadsheet_number] = base_reason

    events_by_spreadsheet: dict[int, list[dict[str, str]]] = {}
    for event in events:
        number = int(float(event["Spreadsheet Nr"]))
        events_by_spreadsheet.setdefault(number, []).append(event)

    rows = []
    unmapped_property_cells: dict[int, list[str]] = {}
    for spreadsheet_number, group in sorted(events_by_spreadsheet.items()):
        available = set(property_cells.get(spreadsheet_number, []))
        assignments: dict[str, set[str]] = {}
        mapping_notes: dict[str, str] = {}
        unresolved: list[dict[str, str]] = []
        for event in group:
            event_id = str(int(float(event["Error Nr"])))
            expanded = expand_fault_spec(event.get("Faulty cells", ""))
            worksheet = event.get("Faulty worksheet", "").strip()
            if expanded is None:
                unresolved.append(event)
                continue
            matched = {
                label for label in available
                if label.rsplit("!", 1)[-1] in expanded
                and (not worksheet or label.rsplit("!", 1)[0].strip() == worksheet)
            }
            if not matched:
                address_only = {
                    label for label in available
                    if label.rsplit("!", 1)[-1] in expanded
                }
                if address_only:
                    matched = address_only
                    mapping_notes[event_id] = "overview_sheet_name_mismatch_used_property_sheet"
            assignments[event_id] = matched
            available -= matched
        if len(unresolved) == 1:
            event_id = str(int(float(unresolved[0]["Error Nr"])))
            assignments[event_id] = set(available)
            available.clear()
        if available:
            unmapped_property_cells[spreadsheet_number] = sorted(available)

        for event in group:
            event_number = int(float(event["Error Nr"]))
            labels = sorted(assignments.get(str(event_number), set()))
            workbook = usable_workbooks.get(spreadsheet_number)
            cell_type = event.get("Cell type", "")
            change = event.get("Change", "")
            reason = workbook_reasons.get(spreadsheet_number, "properties_or_workbook_not_found")
            include = 1
            if cell_type.casefold() != "formula":
                include, reason = 0, f"outside_scope_cell_type:{cell_type or 'unknown'}"
            elif not event.get("Faulty Spreadsheet", ""):
                include, reason = 0, "faulty_workbook_not_available"
            elif change.casefold() == "inserted" and not labels:
                include, reason = 0, "faulty_version_has_no_formula_at_inserted_cell"
            elif workbook is None:
                include = 0
            elif not labels:
                include, reason = 0, "no_property_cells_mapped_to_event"
            elif mapping_notes.get(str(event_number)):
                include, reason = 0, "annotation_conflict_overview_vs_properties_sheet"
            rows.append({
                "instance_id": f"enron_event_{event_number:02d}",
                "error_event": event_number,
                "spreadsheet_number": spreadsheet_number,
                "workbook": relative(workbook, args.output.parent) if workbook else "",
                "source_cell": labels[0] if len(labels) == 1 else "",
                "source_cells": ";".join(labels),
                "labeled_cell_count": len(labels),
                "correct_formula": "",
                "include": include,
                "exclusion_reason": reason,
                "error_type": event.get("Type", ""),
                "error_subtype": event.get("Subtype", ""),
                "cell_type": cell_type,
                "change": change,
                "error_description": event.get("Additional information", ""),
                "faulty_spreadsheet_name": event.get("Faulty Spreadsheet", ""),
                "faulty_worksheet": event.get("Faulty worksheet", ""),
                "faulty_cells_overview": event.get("Faulty cells", ""),
                "mapping_note": mapping_notes.get(str(event_number), ""),
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "instance_id", "error_event", "spreadsheet_number", "workbook", "source_cell",
        "source_cells", "labeled_cell_count", "correct_formula", "include", "exclusion_reason",
        "error_type", "error_subtype", "cell_type", "change", "error_description",
        "faulty_spreadsheet_name", "faulty_worksheet", "faulty_cells_overview",
        "mapping_note",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "property_files": len(property_files),
        "fault_events": len(rows),
        "expected_faults": args.expected_faults,
        "expected_fault_count_met": len(rows) == args.expected_faults,
        "formula_events": sum(row["cell_type"].casefold() == "formula" for row in rows),
        "property_cell_labels": sum(len(values) for values in property_cells.values()),
        "unmapped_property_cells": unmapped_property_cells,
        "included_before_formula_parser_audit": sum(int(row["include"]) for row in rows),
        "excluded_before_formula_parser_audit": sum(not int(row["include"]) for row in rows),
    }
    args.output.with_suffix(".audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
