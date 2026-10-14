"""Generate 36 deterministic ordinary/stress V5.2 red-team workbooks.

Each workbook contains one injected silent error plus twenty correct structural
exception formulas.  The exceptions make "source already outside V4 Top-5"
an explicit test condition instead of hoping it appears in ordinary synthetic
templates.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


ERRORS = {
    "M1_reference_shift": (
        lambda row: f"=A{row}*2",
        lambda row: f"=A{row - 1}*2",
    ),
    "M2_range_boundary": (
        lambda row: f"=SUM(A{row}:A{row + 1})",
        lambda row: f"=SUM(A{row}:A{row + 2})",
    ),
    "M3_operator": (
        lambda row: f"=A{row}*2",
        lambda row: f"=A{row}+2",
    ),
    "M4_function": (
        lambda row: f"=SUM(A{row}:A{row + 1})",
        lambda row: f"=AVERAGE(A{row}:A{row + 1})",
    ),
    "M5_absolute_reference": (
        lambda row: f"=A{row}*$A$15",
        lambda row: f"=A{row}*A15",
    ),
    "M6_copy_offset": (
        lambda row: f"=A{row}+A{row + 1}",
        lambda row: f"=A{row - 1}+A{row}",
    ),
}
DEPTH_CHAINS = {"shallow": 0, "medium": 2, "deep": 5}


def _column(number: int) -> str:
    value = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _sheet_xml(error_type: str, depth: str, *, stress: bool) -> str:
    correct_builder, mutant_builder = ERRORS[error_type]
    cells: dict[str, tuple[str, str]] = {}
    for row in range(2, 21):
        cells[f"A{row}"] = ("value", str(10 + row * 3))

    if stress:
        # Twenty correct structural exceptions.  Each is surrounded by a regular
        # vertical copy family and has a longer downstream chain than the target.
        for col_number in range(2, 22):
            col = _column(col_number)
            constant = col_number + 1
            for row in range(2, 11):
                formula = f"=A{row}*{constant}"
                if row == 6:
                    formula = f"=SUM($A$2:$A$11)+{constant}"
                cells[f"{col}{row}"] = ("formula", formula)
            cells[f"{col}12"] = ("formula", f"={col}6+1")
            for row in range(13, 21):
                cells[f"{col}{row}"] = ("formula", f"={col}{row - 1}+1")

    target_col = "V"
    for row in range(2, 11):
        formula = correct_builder(row)
        if row == 6:
            formula = mutant_builder(row)
        cells[f"{target_col}{row}"] = ("formula", formula)
    previous = "V6"
    for offset in range(DEPTH_CHAINS[depth]):
        col = _column(23 + offset)
        cells[f"{col}6"] = ("formula", f"={previous}+1")
        previous = f"{col}6"

    rows: dict[int, list[str]] = {}
    for address, (kind, value) in cells.items():
        row = int("".join(character for character in address if character.isdigit()))
        if kind == "formula":
            element = f'<c r="{address}"><f>{escape(value[1:])}</f><v>0</v></c>'
        else:
            element = f'<c r="{address}"><v>{escape(value)}</v></c>'
        rows.setdefault(row, []).append(element)
    row_xml = "".join(
        f'<row r="{row}">{"".join(sorted(items))}</row>'
        for row, items in sorted(rows.items())
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{row_xml}</sheetData></worksheet>'
    )


def _write_xlsx(path: Path, error_type: str, depth: str, *, stress: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Model" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        ),
        "xl/worksheets/sheet1.xml": _sheet_xml(error_type, depth, stress=stress),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def build_redteam_workbooks(output: Path) -> list[dict[str, object]]:
    records = []
    for error_type, (correct_builder, _) in ERRORS.items():
        for depth, chain_length in DEPTH_CHAINS.items():
            for stratum in ("top5", "below5"):
                stress = stratum == "below5"
                stem = f"{'stress' if stress else 'ordinary'}_{error_type}_{depth}"
                path = output / f"{stem}.xlsx"
                _write_xlsx(path, error_type, depth, stress=stress)
                records.append({
                    "instance_id": stem,
                    "path": path,
                    "source_cell": "Model!V6",
                    "correct_formula": correct_builder(6),
                    "error_type": error_type,
                    "depth_bin": depth,
                    "actual_depth": chain_length,
                    "intended_v4_stratum": stratum,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
    return records


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for record in build_redteam_workbooks(args.output):
        print(record["path"])
