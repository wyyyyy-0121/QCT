"""Author-only pre/post formula diff, permitted only after original prediction lock."""
from pathlib import Path
import collections
import sys
import xml.etree.ElementTree as ET
import zipfile
import posixpath
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'qa')]
from run_selector_dev5 import read, save, sha
from run_hobyah_natural_dev26 import RUN, verify
from structuralguard.formula import translate_formula


def xml_formulas(path):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    result = {}
    with zipfile.ZipFile(path) as archive:
        rels = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        for sheet in book.findall('s:sheets/s:sheet', ns):
            target = rels[sheet.attrib['{' + ns['r'] + '}id']]
            name = posixpath.normpath('xl/' + target) if not target.startswith('/') else target.lstrip('/')
            root = ET.fromstring(archive.read(name))
            masters = {}
            cells = root.findall('.//s:sheetData/s:row/s:c', ns)
            for cell in cells:
                f = cell.find('s:f', ns)
                if f is not None and f.attrib.get('t') == 'shared' and f.text:
                    assert f.attrib['si'] not in masters
                    masters[f.attrib['si']] = (cell.attrib['r'], '=' + f.text)
            for cell in cells:
                f = cell.find('s:f', ns)
                if f is not None:
                    if f.attrib.get('t') == 'shared':
                        anchor, formula = masters[f.attrib['si']]
                        formula = translate_formula(formula, anchor, cell.attrib['r'])
                    else:
                        assert f.text is not None, (sheet.attrib['name'], cell.attrib['r'])
                        formula = '=' + f.text
                    result[sheet.attrib['name'] + '!' + cell.attrib['r']] = formula
    return result


def snapshot(path):
    book = openpyxl.load_workbook(path, data_only=False)
    values = {}; formulas = {}; comments = []; notices = []
    for sheet in book:
        for row in sheet:
            for cell in row:
                key = sheet.title + '!' + cell.coordinate
                if cell.value is not None:
                    values[key] = cell.value
                    if cell.data_type == 'f': formulas[key] = cell.value
                    if isinstance(cell.value, str) and not cell.value.startswith('='):
                        if any(t in cell.value.lower() for t in ['copyright', 'license', 'corrected', 'j13', 'j14', 'errata', 'answer']):
                            notices.append(dict(cell=key, text=cell.value))
                if cell.comment: comments.append(dict(cell=key, text=cell.comment.text))
    assert formulas == xml_formulas(path)
    return dict(sheets=book.sheetnames, values=values, formulas=formulas, comments=comments, notices=notices)


def main():
    verify(); target = RUN / 'author_diff.json.gz'; assert not target.exists()
    acquisition = read(RUN / 'acquisition.json')
    for row in acquisition['records']: assert sha(ROOT / row['path']) == row['sha256']
    before = snapshot(RUN / 'raw/before.xlsx'); after = snapshot(RUN / 'raw/after.xlsx')
    changes = []
    for key in sorted(before['formulas'].keys() | after['formulas'].keys()):
        if before['formulas'].get(key) != after['formulas'].get(key):
            changes.append(dict(cell=key, before=before['formulas'].get(key), after=after['formulas'].get(key)))
    values = []
    for key in sorted(before['values'].keys() | after['values'].keys()):
        old, new = before['values'].get(key), after['values'].get(key)
        if old != new:
            values.append(dict(cell=key, before=old, after=new))
    payload = dict(before=before, after=after, formula_changes=changes, all_value_changes=values,
                   original_prediction_lock_sha256=sha(RUN / 'prediction_lock.json'),
                   author_auditor_sha256=sha(Path(__file__)), literal_ooxml_formula_audit_passed=True,
                   final_validation_eligible=False, all_changed_formulas_assumed_errors=False)
    save(target, payload)
    print('DEV26 literal OOXML diff', len(before['formulas']), len(after['formulas']), 'formula changes', len(changes), flush=True)
    for r in changes: print(r, flush=True)
    print('Original notices', before['notices'], flush=True)
    print('Original comments', before['comments'], flush=True)


if __name__ == '__main__': main()
