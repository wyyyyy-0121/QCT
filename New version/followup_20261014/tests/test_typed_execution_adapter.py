import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "baseline/source/HybridGuard_V5_handoff_20260904/src"))

from typed_execution_adapter import ExcelError, TypedExecutionAdapter, load_typed_inputs, typed_value


def make_book(path: Path, rows: str) -> None:
    workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" r:id="r1"/></sheets></workbook>'''
    relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>'''
    sheet = f'''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{rows}</sheetData></worksheet>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class TypedExecutionAdapterTests(unittest.TestCase):
    def book(self, rows: str):
        folder = tempfile.TemporaryDirectory()
        path = Path(folder.name) / "typed.xlsx"
        make_book(path, rows)
        self.addCleanup(folder.cleanup)
        return path

    def test_error_cell_is_not_literal_text(self):
        path = self.book('<row r="1"><c r="A1" t="e"><v>#DIV/0!</v></c><c r="B1"><f>A1</f><v>#DIV/0!</v></c></row>')
        inputs = load_typed_inputs(path)
        self.assertEqual(inputs[("Sheet1", "A1")], ExcelError("#DIV/0!"))
        values, errors = TypedExecutionAdapter.from_xlsx(path).evaluate()
        self.assertEqual(typed_value(values[("Sheet1", "B1")]), {"kind": "error", "error": "#DIV/0!"})
        self.assertEqual(errors[("Sheet1", "B1")], "#DIV/0!")

    def test_same_spelling_string_remains_text(self):
        path = self.book('<row r="1"><c r="A1" t="str"><v>#DIV/0!</v></c><c r="B1"><f>A1</f><v>#DIV/0!</v></c></row>')
        inputs = load_typed_inputs(path)
        self.assertEqual(inputs[("Sheet1", "A1")], "#DIV/0!")
        values, _ = TypedExecutionAdapter.from_xlsx(path).evaluate()
        self.assertEqual(typed_value(values[("Sheet1", "B1")]), {"kind": "text", "value": "#DIV/0!"})

    def test_if_only_evaluates_selected_branch(self):
        path = self.book('<row r="1"><c r="A1"><v>7</v></c><c r="B1"><f>IF(1,A1,1/0)</f><v>7</v></c></row>')
        values, errors = TypedExecutionAdapter.from_xlsx(path).evaluate()
        self.assertEqual(typed_value(values[("Sheet1", "B1")]), {"kind": "number", "value": 7.0})
        self.assertNotIn(("Sheet1", "B1"), errors)

    def test_error_condition_propagates_without_evaluating_branches(self):
        path = self.book('<row r="1"><c r="A1" t="e"><v>#N/A</v></c><c r="B1"><f>IF(A1,1,2)</f><v>#N/A</v></c></row>')
        values, _ = TypedExecutionAdapter.from_xlsx(path).evaluate()
        self.assertEqual(typed_value(values[("Sheet1", "B1")]), {"kind": "error", "error": "#N/A"})

    def test_division_and_aggregate_errors_are_typed(self):
        path = self.book('<row r="1"><c r="A1"><v>1</v></c><c r="B1"><f>A1/0</f><v>#DIV/0!</v></c><c r="C1"><f>SUM(A1,B1)</f><v>#DIV/0!</v></c></row>')
        values, _ = TypedExecutionAdapter.from_xlsx(path).evaluate()
        self.assertEqual(typed_value(values[("Sheet1", "B1")]), {"kind": "error", "error": "#DIV/0!"})
        self.assertEqual(typed_value(values[("Sheet1", "C1")]), {"kind": "error", "error": "#DIV/0!"})


if __name__ == "__main__":
    unittest.main()
