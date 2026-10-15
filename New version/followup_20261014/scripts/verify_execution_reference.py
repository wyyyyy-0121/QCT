"""Independently reconcile the locked execution audit, without its comparator."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/execution_reference_dev1'
PUBLIC = ROOT / 'development/public_pycel_dev1'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relation(left, right):
    if left['kind'] == 'error' or right['kind'] == 'error':
        if left['kind'] == right['kind']:
            return 'same_error' if left['error'] == right['error'] else 'different_error'
        if left['kind'] == 'error':
            return 'actual_error_reference_' + right['kind']
        return 'reference_error_actual_' + left['kind']
    valid = {'number', 'boolean', 'text'}
    if left['kind'] not in valid or right['kind'] not in valid:
        return 'not_comparable'
    if left['kind'] != right['kind']:
        return 'type_mismatch'
    a, b = left['value'], right['value']
    if left['kind'] == 'number':
        equal = abs(a - b) <= max(1e-8, 1e-8 * max(abs(a), abs(b)))
    else:
        equal = a == b
    return 'agreement' if equal else 'disagreement'


def raw_caches(path):
    """Independent XML enumeration, including empty array result declarations."""
    result = {}
    with zipfile.ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(t.text or '' for t in item.findall('.//m:t', NS))
                      for item in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        relations = {r.attrib['Id']: r.attrib['Target'] for r in
                     ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        for sheet in ET.fromstring(archive.read('xl/workbook.xml')).findall('m:sheets/m:sheet', NS):
            target = relations[sheet.attrib[REL]]
            part = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            for cell in ET.fromstring(archive.read(part)).findall('m:sheetData/m:row/m:c', NS):
                if cell.find('m:f', NS) is None:
                    continue
                kind = cell.attrib.get('t', 'n'); value = cell.find('m:v', NS)
                value = value.text if value is not None else None
                if value is None:
                    typed = {'kind': 'missing'}
                elif kind == 'e':
                    typed = {'kind': 'error', 'error': value}
                elif kind == 'b':
                    typed = {'kind': 'boolean', 'value': value == '1'}
                elif kind == 'n':
                    numeric = float(value)
                    typed = {'kind': 'number', 'value': numeric} if math.isfinite(numeric) else {
                        'kind': 'nonfinite', 'value': str(numeric)}
                elif kind in {'str', 'inlineStr', 's'}:
                    typed = {'kind': 'text', 'value': shared[int(value)] if kind == 's' else value}
                else:
                    typed = {'kind': 'unhandled_cache', 'type': kind, 'value': value}
                result[sheet.attrib['name'] + '!' + cell.attrib['r']] = typed
    return result


def verify():
    lock = read(RUN / 'execution_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'registration.json') == lock['registration_sha256']
    source_lock = read(RUN / 'source_lock.json')
    for relative, expected in source_lock['files'].items():
        assert sha(ROOT / relative) == expected, relative
    for filename, expected in source_lock['environment']['binaries'].items():
        assert sha(Path(filename).resolve()) == expected, filename
    assert sha(Path('/usr/lib/python3/dist-packages/uno.py')) == source_lock['environment']['uno_module_sha256']
    for relative, expected in lock['files'].items():
        assert sha(RUN / relative) == expected, relative
    registration = read(RUN / 'registration.json')
    assert not registration['final_validation_eligible']
    assert not lock['business_labels_read'] and not lock['repair_proposals_generated']
    execution = read(RUN / 'execution.json')
    analysis = read(RUN / 'analysis.json')
    assert analysis['precision'] is analysis['coverage'] is None
    assert not analysis['business_labels_available'] and not analysis['final_validation_eligible']
    analysis_lock = read(RUN / 'analysis_lock.json')
    assert sha(RUN / 'analysis.json') == analysis_lock['analysis_sha256']
    assert sha(RUN / 'execution_lock.json') == analysis_lock['execution_lock_sha256']
    assert len(execution['cases']) == len(analysis['cases']) == len(registration['selected_files']) == 14
    totals, statuses = Counter(), Counter()
    for run_case, case, relative in zip(execution['cases'], analysis['cases'], registration['selected_files']):
        assert run_case['id'] == case['id']
        assert case['source_path'] == relative
        source = PUBLIC / 'raw' / relative
        assert sha(source) == lock['inputs'][relative] == case['input_sha256'] == case['source_hash_after']
        caches = raw_caches(source)
        totals['raw_formula_declarations'] += len(caches)
        statuses[case['status']] += 1
        if case['status'] != 'complete':
            totals['reference_failed_formula_declarations'] += len(caches)
            assert 'details' not in case
            continue
        reference = read(RUN / 'cases' / (case['id'] + '_reference.json'))
        original = read(RUN / 'cases' / (case['id'] + '_original.json'))
        assert reference['forced_calculate_all'] and reference['read_only']
        assert not reference['workbook_saved'] and reference['worker_returncode'] == 0
        assert set(reference['cells']) == {d['cell'] for d in case['details']} == set(caches)
        model = WorkbookModel.from_xlsx(source)
        values, errors = model.evaluate()
        assert set(original) == {s + '!' + a for s, a in model.formulas}
        for label, observation in original.items():
            key = tuple(label.rsplit('!', 1))
            if key in errors:
                assert observation == {'kind': 'error', 'error': str(errors[key])}
            else:
                value = values.get(key)
                if isinstance(value, bool):
                    expected = {'kind': 'boolean', 'value': value}
                elif isinstance(value, (int, float)):
                    expected = {'kind': 'number', 'value': value} if math.isfinite(value) else {
                        'kind': 'nonfinite', 'value': str(value)}
                elif isinstance(value, str):
                    expected = {'kind': 'text', 'value': value}
                else:
                    expected = {'kind': 'missing'} if value is None else {'kind': 'unhandled', 'value': repr(value)}
                assert observation == expected, label
        counts = Counter()
        for detail in case['details']:
            label = detail['cell']; independent = reference['cells'][label]
            actual = original.get(label)
            assert detail['original_cache'] == caches[label]
            assert detail['libreoffice'] == independent
            assert detail['original_model'] == actual
            cache_result = relation(independent, caches[label])
            engine_result = relation(actual, independent) if actual else 'not_loaded_by_original_reader'
            assert detail['cache_comparison'] == cache_result
            assert detail['original_vs_reference'] == engine_result
            counts['cache_' + cache_result] += 1
            counts['original_vs_reference_' + engine_result] += 1
            counts['reference_kind_' + independent['kind']] += 1
        assert dict(counts) == case['comparisons']
        assert sum(counts[k] for k in counts if k.startswith('cache_')) == len(caches)
        assert sum(counts[k] for k in counts if k.startswith('original_vs_reference_')) == len(caches)
        totals.update(counts)
    assert dict(totals) == analysis['totals']
    result = {'all_locks_verified': True, 'original_execution_recomputed': True,
              'independent_xml_and_comparator_used': True,
              'every_raw_formula_declaration_accounted_for': True,
              'original_inputs_unchanged': True, 'totals': dict(totals),
              'case_statuses': dict(statuses), 'precision': None, 'coverage': None,
              'business_repair_labels_available': False,
              'verifier_sha256': sha(Path(__file__)),
              'analysis_sha256': sha(RUN / 'analysis.json')}
    target = ROOT / 'qa/EXECUTION_REFERENCE_INDEPENDENT_VERIFICATION_20261015.json'
    target.write_text(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    verify()
