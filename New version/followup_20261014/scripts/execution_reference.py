"""Typed execution comparisons; an engine/cache is never business repair truth."""
import math
import posixpath
import xml.etree.ElementTree as ET
import zipfile

NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def typed_value(value, error=None):
    if error is not None:
        return {'kind': 'error', 'error': str(error)}
    if isinstance(value, bool):
        return {'kind': 'boolean', 'value': value}
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            return {'kind': 'number', 'value': value}
        return {'kind': 'nonfinite', 'value': str(value)}
    if isinstance(value, str):
        return {'kind': 'text', 'value': value}
    if value is None:
        return {'kind': 'missing'}
    return {'kind': 'unhandled', 'value': repr(value)}


def compare(actual, reference):
    """Keep error, absent and type mismatches out of successful comparisons.

    Excel booleans are distinct from 0/1 numbers. Numeric engine agreement uses
    both relative and absolute tolerances; date serials remain numbers here.
    """
    if actual['kind'] == 'error':
        if reference['kind'] == 'error':
            return ('same_error' if actual.get('error') == reference.get('error')
                    else 'different_error')
        return 'actual_error_reference_' + reference['kind']
    if reference['kind'] == 'error':
        return 'reference_error_actual_' + actual['kind']
    if actual['kind'] not in {'number', 'boolean', 'text'} or reference['kind'] not in {
            'number', 'boolean', 'text'}:
        return 'not_comparable'
    if actual['kind'] != reference['kind']:
        return 'type_mismatch'
    if actual['kind'] == 'number':
        same = math.isclose(actual['value'], reference['value'], rel_tol=1e-8, abs_tol=1e-8)
    else:
        same = actual['value'] == reference['value']
    return 'agreement' if same else 'disagreement'


def formula_declarations(path):
    """Read every raw formula declaration and its typed original cached result.

    Empty array followers and shared formulas remain present. No reader-derived
    formula count is used as the denominator for this execution audit.
    """
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared_strings = []
        if 'xl/sharedStrings.xml' in names:
            for item in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('x:si', NS):
                shared_strings.append(''.join(t.text or '' for t in item.iterfind('.//x:t', NS)))
        relations = {n.attrib['Id']: n.attrib['Target'] for n in
                     ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        records = {}
        for sheet in workbook.findall('x:sheets/x:sheet', NS):
            target = relations[sheet.attrib[REL]]
            target = (target.lstrip('/') if target.startswith('/')
                      else posixpath.normpath('xl/' + target))
            for cell in ET.fromstring(archive.read(target)).findall('x:sheetData/x:row/x:c', NS):
                formula = cell.find('x:f', NS)
                if formula is None:
                    continue
                node = cell.find('x:v', NS)
                text = node.text if node is not None else None
                kind = cell.attrib.get('t', 'n')
                if text is None:
                    cache = {'kind': 'missing'}
                elif kind == 'e':
                    cache = {'kind': 'error', 'error': text}
                elif kind == 'b':
                    cache = {'kind': 'boolean', 'value': text == '1'}
                elif kind in {'str', 'inlineStr'}:
                    cache = {'kind': 'text', 'value': text}
                elif kind == 's':
                    cache = {'kind': 'text', 'value': shared_strings[int(text)]}
                elif kind == 'n':
                    try:
                        cache = typed_value(float(text))
                    except ValueError:
                        cache = {'kind': 'invalid_cache', 'value': text}
                else:
                    cache = {'kind': 'unhandled_cache', 'type': kind, 'value': text}
                records[sheet.attrib['name'] + '!' + cell.attrib['r']] = {
                    'formula_text': formula.text, 'attributes': dict(formula.attrib), 'cache': cache}
        return records
