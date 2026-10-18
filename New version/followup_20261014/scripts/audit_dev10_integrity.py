"""Independently audit frozen dev10 evidence without rerunning or editing it."""
from collections import Counter
from pathlib import Path
import datetime as dt
import gzip
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
RUN = ROOT / 'development/public_candidate_pipeline_dev10'
TARGET = ROOT / 'qa/DEV10_INDEPENDENT_AUDIT_20261018.json'
sys.path.insert(0, str(ROOT / 'scripts'))
from execution_reference import formula_declarations


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def audit():
    from openpyxl import load_workbook
    lock = read(RUN / 'prediction_lock.json')
    index = read(RUN / 'public_index.json')
    acquisition = {r['path']: r for r in
                   read(ROOT / 'development/public_candidate_audit_dev7/REPORT.json')['records']}
    frozen = read(RUN / 'source_lock.json')['files']
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    for relative, expected in frozen.items():
        assert sha(ROOT / relative) == expected, relative
    for relative, expected in lock['files'].items():
        assert sha(RUN / relative) == expected, relative
    cases, risks = [], []
    for item in index:
        path = REPO / item['relative_path']
        before = sha(path)
        assert before == item['sha256'] == lock['inputs'][item['relative_path']]
        assert before == acquisition[item['relative_path']]['sha256']
        prediction = read(RUN / 'predictions' / (item['id'] + '.json.gz'))
        assert prediction['input_sha256'] == before
        with zipfile.ZipFile(path) as archive:
            workbook = ET.fromstring(archive.read('xl/workbook.xml'))
            sheets = [s.attrib['name'] for s in workbook.findall(
                '{*}sheets/{*}sheet')]
        entry = {'id': item['id'], 'input_sha256': before,
                 'acquisition_sha_matches': True, 'status': prediction['status'],
                 'sheet_manifest': sheets}
        if prediction['status'] == 'inference_complete_unscored':
            declarations = formula_declarations(path)
            # openpyxl independently expands shared-formula references.
            book = load_workbook(path, data_only=False, read_only=False)
            observed = {}
            for sheet in book:
                for row in sheet:
                    for cell in row:
                        if cell.data_type == 'f':
                            formula = cell.value
                            if not isinstance(formula, str):
                                formula = '=' + formula.text.lstrip('=')
                            observed[sheet.title + '!' + cell.coordinate] = formula
            book.close()
            entry.update(raw_formula_declarations=len(declarations),
                         raw_nonempty_formula_texts=sum(bool(d['formula_text']) for d in declarations.values()),
                         raw_shared_followers=sum(d['attributes'].get('t') == 'shared' and
                                                  not d['formula_text'] for d in declarations.values()),
                         loaded_formula_cells=prediction['formula_cells'],
                         evaluation_errors=len(prediction['evaluation_errors']),
                         evaluated_without_error=prediction['evaluated_without_error'],
                         proposals={}, recorded_originals_compared={},
                         worker_cpu_seconds=prediction['cpu_seconds'])
            for name, result in prediction['predictions'].items():
                rows = result['rows']
                labels = [r['cell'] for r in rows]
                assert len(labels) == len(set(labels)) == prediction['formula_cells']
                assert set(labels) <= set(declarations)
                assert set(labels) <= set(observed)
                compared = 0
                for row in rows:
                    if 'original_formula' in row:
                        assert row['original_formula'] == observed[row['cell']], (item['id'], name, row['cell'])
                        compared += 1
                proposals = [r for r in rows if r.get('suggested_formula')
                             and r['suggested_formula'] != observed[r['cell']]
                             and (name == 'paper' or r.get('status') == 'propose')]
                entry['proposals'][name] = len(proposals)
                entry['recorded_originals_compared'][name] = compared
                if name == 'dev6':
                    for row in proposals:
                        original = observed[row['cell']]
                        risks.append({'id': item['id'], 'cell': row['cell'],
                                      'original': original, 'suggested': row['suggested_formula'],
                                      'reason': row.get('reason'),
                                      'risk_class': 'string_unit_or_check_name' if
                                      ('"' in original or 'check_' in original.lower())
                                      else 'unlabelled_reference_change',
                                      'correctness': None})
            entry['raw_declarations_absent_from_prediction'] = sorted(set(declarations) - set(labels))
            entry['openpyxl_formulas_absent_from_prediction'] = sorted(set(observed) - set(labels))
            entry['original_formula_consistency_verified'] = True
            entry['worker_peak_rss_kib'] = prediction['peak_rss_kib']
        else:
            assert prediction['status'] == 'inference_failed'
            entry['failure'] = ('protected_answer_sheet' if item['id'] == 'public05'
                                else 'xlsm_not_supported')
            entry['formula_contents_read_by_this_audit'] = False
        assert sha(path) == before
        entry['input_unchanged_during_independent_audit'] = True
        cases.append(entry)
    raw = read(RUN / 'audit.json')
    complete = [c for c in cases if c['status'] == 'inference_complete_unscored']
    result = {
        'role': 'independent post-prediction integrity audit; revealed development only',
        'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'auditor_sha256': sha(Path(__file__)),
        'prediction_lock_sha256': sha(RUN / 'prediction_lock.json'),
        'verified_source_files': len(frozen), 'cases': cases, 'risks': risks,
        'totals': {key: sum(c[key] for c in complete) for key in
                   ['raw_formula_declarations', 'raw_nonempty_formula_texts',
                    'raw_shared_followers', 'loaded_formula_cells', 'evaluation_errors',
                    'evaluated_without_error', 'worker_cpu_seconds']},
        'proposal_totals': dict(Counter({name: sum(c['proposals'][name] for c in complete)
                                        for name in ['paper', 'dev2', 'dev4', 'dev5', 'dev6', 'dev9']})),
        'case_counts': dict(Counter(c['status'] for c in cases)),
        'runtime': {'wall_seconds': raw['wall_seconds'],
                    'parent_only_cpu_seconds': raw['cpu_seconds'],
                    'successful_workers_cpu_seconds': sum(c['worker_cpu_seconds'] for c in complete),
                    'failed_workers_cpu_seconds': None, 'gpu_used': False,
                    'scope': 'SG/FG/Hybrid and developer candidates; no parallel sheet list supplied'},
        'precision': None, 'coverage': None, 'final_validation_eligible': False,
        'limitations': [
            'Original audit paper proposal totals incorrectly require status=propose; corrected here.',
            'Input hashes now match original acquisition receipts, but no historical pre-run hash evidence is added.',
            'Recorded original formulas agree with independent readers; this does not prove no transient in-memory mutation.',
            'public05 loaded WorkbookModel before SG rejected Answer keys; embedded answer isolation was not established.',
            'No external answer files are used here; public05 formula contents are not read by this independent audit.',
            'Current 11 records have no timeout; the historical runner does not persist a timeout prediction file.',
            'No business truth exists; all 18 dev6 suggestions remain unscored.',
            'Empty parallel-sheet metadata means the parallel-sheet component was not exercised.',
        ]}
    assert result['totals']['loaded_formula_cells'] == (result['totals']['evaluation_errors'] +
                                                      result['totals']['evaluated_without_error'])
    return result


if __name__ == '__main__':
    result = audit()
    if TARGET.exists():
        old = read(TARGET)
        for key in ['utc']:
            result[key] = old[key]
        assert result == old, 'Independent audit changed'
    else:
        TARGET.parent.mkdir(exist_ok=True)
        with TARGET.open('x') as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write('\n')
    print('DEV10 INDEPENDENT AUDIT VERIFIED', json.dumps(
        {k: result[k] for k in ['totals', 'proposal_totals', 'case_counts']}, sort_keys=True))
