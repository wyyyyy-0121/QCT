from __future__ import annotations

import argparse
import csv
import json
import posixpath
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path


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
    completed = subprocess.run(
        [libreoffice, "--headless", "--convert-to", "xlsx", "--outdir", str(converted), str(source)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    target = converted / f"{source.stem}.xlsx"
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
    parser.add_argument("--expected-faults", type=int, default=36)
    args = parser.parse_args()

    converted = args.converted or args.output.parent / "converted"
    rows = []
    property_files = sorted(args.properties.rglob("*.properties"))
    for property_file in property_files:
        props = read_properties(property_file)
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
        for ordinal, (key, coordinate) in enumerate(faulty, 1):
            include = 1
            reason = base_reason
            source_cell = ""
            if usable:
                try:
                    source_cell = property_coordinate(coordinate, sheets)
                except Exception as exc:
                    include = 0
                    reason = f"coordinate_error:{exc}"
            else:
                include = 0
            rows.append({
                "instance_id": f"{property_file.stem}_fault{ordinal}",
                "workbook": relative(usable, args.output.parent) if usable else "",
                "source_cell": source_cell,
                "correct_formula": "",
                "include": include,
                "exclusion_reason": reason,
                "property_file": relative(property_file, args.output.parent),
                "property_coordinate": coordinate,
                "fault_type": props.get(f"FAULT_TYPE_{key.rsplit('_', 1)[-1]}", ""),
                "original_workbook": str(workbook or ""),
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "instance_id", "workbook", "source_cell", "correct_formula", "include", "exclusion_reason",
        "property_file", "property_coordinate", "fault_type", "original_workbook",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "property_files": len(property_files),
        "fault_rows": len(rows),
        "expected_faults": args.expected_faults,
        "expected_fault_count_met": len(rows) == args.expected_faults,
        "included_before_formula_parser_audit": sum(int(row["include"]) for row in rows),
        "excluded_before_formula_parser_audit": sum(not int(row["include"]) for row in rows),
    }
    args.output.with_suffix(".audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
