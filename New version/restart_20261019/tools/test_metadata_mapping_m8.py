from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook

from metadata_mapping_m8 import map_field, snapshot


class MetadataMappingTests(unittest.TestCase):
    def test_formula_and_numeric_values_do_not_enter_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'control.xlsx'
            book = Workbook()
            sheet = book.active
            sheet['A1'], sheet['B1'], sheet['C1'] = 'Flow (Q)', '=1+2', 'scfm'
            sheet['A2'], sheet['B2'] = 'Input', 20
            book.save(path)
            old = snapshot(path)
            sheet['B1'], sheet['B2'] = '=999/3', 99
            book.save(path)
            self.assertEqual(snapshot(path), old)
            self.assertEqual(old['sheets']['Sheet']['B1'], {'kind': 'formula'})
            self.assertEqual(old['sheets']['Sheet']['B2'], {'kind': 'number'})

    def data(self, units=('scfm', 'acfm')):
        cells = {}
        for row, (label, unit) in enumerate(zip(['Flow (Qwi) at standard conditions', 'Flow (Qwi) at actual conditions'], units), 1):
            cells['A' + str(row)] = dict(kind='text', text=label)
            cells['B' + str(row)] = dict(kind='number')
            cells['C' + str(row)] = dict(kind='text', text=unit) if unit else dict(kind='formula')
        return dict(sheets={'S': cells})

    def test_units_and_conditions_disambiguate_without_dropping_unknowns(self):
        self.assertEqual(map_field(self.data(), dict(term='Qwi'))['reason'], 'ambiguous_fields')
        self.assertEqual(map_field(self.data(), dict(term='Qwi', unit='scfm'))['reference']['cell'], 'B1')
        self.assertEqual(map_field(self.data(), dict(term='Flow (Qwi) at actual conditions'))['reference']['cell'], 'B2')
        self.assertEqual(map_field(self.data(('scfm', None)), dict(term='Qwi', unit='scfm'))['reason'],
                         'unit_not_statically_verified')

    def test_scientific_symbol_and_unit_case_is_preserved(self):
        self.assertEqual(map_field(self.data(), dict(term='qwi'))['status'], 'unresolved')
        self.assertEqual(map_field(self.data(('MW', 'mW')), dict(term='Qwi', unit='MW'))['reference']['cell'], 'B1')
        self.assertEqual(map_field(self.data(('MW', 'mW')), dict(term='Qwi', unit='mW'))['reference']['cell'], 'B2')

    def test_multiple_header_values_remain_ambiguous(self):
        data = dict(sheets={'S': {'A1': dict(kind='text', text='Parameter'),
                                'D1': dict(kind='text', text='Calculated Value'),
                                'E1': dict(kind='text', text='Units'),
                                'F1': dict(kind='text', text='Calculated Value'),
                                'A2': dict(kind='text', text='Flow (Q)'), 'D2': dict(kind='formula'),
                                'E2': dict(kind='text', text='scfm'), 'F2': dict(kind='formula')}})
        self.assertEqual(map_field(data, dict(term='Q'))['reason'], 'ambiguous_fields')

    def test_address_hints_missing_fields_and_wrong_units_are_rejected(self):
        for query in [dict(term='Qwi', cell='B1'), dict(term='Absent'), dict(term='Qwi', unit='kg')]:
            self.assertEqual(map_field(self.data(), query)['status'], 'unresolved')


if __name__ == '__main__':
    unittest.main()
