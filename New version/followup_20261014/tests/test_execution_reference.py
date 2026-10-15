import sys
import tempfile
import unittest
from pathlib import Path
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from execution_reference import compare, formula_declarations, typed_value


class ExecutionReferenceTests(unittest.TestCase):
    def test_boolean_is_not_number(self):
        self.assertEqual(compare(typed_value(True), typed_value(1)), 'type_mismatch')

    def test_error_is_not_success(self):
        self.assertEqual(compare(typed_value(None, 'unsupported'), typed_value(3)),
                         'actual_error_reference_number')
        self.assertEqual(compare(typed_value(None, '#N/A'), typed_value(None, '#N/A')), 'same_error')
        self.assertEqual(compare(typed_value(None, '#VALUE!'), typed_value(None, '#N/A')), 'different_error')

    def test_missing_nonfinite_and_empty_text(self):
        self.assertEqual(compare(typed_value(None), typed_value(None)), 'not_comparable')
        self.assertEqual(compare(typed_value(float('inf')), typed_value(5)), 'not_comparable')
        self.assertEqual(compare(typed_value(''), typed_value('')), 'agreement')

    def test_numeric_tolerance(self):
        self.assertEqual(compare(typed_value(1e9), typed_value(1e9 + 1)), 'agreement')
        self.assertEqual(compare(typed_value(.01), typed_value(.02)), 'disagreement')

    def test_raw_empty_array_follower_and_error_cache_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'raw.xlsx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('xl/workbook.xml', '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="A!B" r:id="r1"/></sheets></workbook>''')
                archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
                archive.writestr('xl/worksheets/sheet1.xml', '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f t="array" ref="A1:A2">ROW(A1:A2)</f><v>1</v></c><c r="B1" t="e"><f>1/0</f><v>#DIV/0!</v></c></row><row r="2"><c r="A2"><f ca="1"/><v>2</v></c></row></sheetData></worksheet>''')
            records = formula_declarations(path)
            self.assertEqual(len(records), 3)
            self.assertIsNone(records['A!B!A2']['formula_text'])
            self.assertEqual(records['A!B!A2']['cache'], {'kind': 'number', 'value': 2.})
            self.assertEqual(records['A!B!B1']['cache'], {'kind': 'error', 'error': '#DIV/0!'})


if __name__ == '__main__':
    unittest.main()
