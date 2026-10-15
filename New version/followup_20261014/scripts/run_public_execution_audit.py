"""Independent LibreOffice execution audit for the excluded Pycel fixtures.

This is compatibility evidence only. Neither cached values nor a second
spreadsheet engine supplies business-intent labels or repair truth.
"""
from collections import Counter
from pathlib import Path
import datetime
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'development/public_pycel_dev1'
RUN = ROOT / 'development/execution_reference_dev1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from execution_reference import compare, formula_declarations, typed_value
from formulaguard.workbook import WorkbookModel


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + '\n')


def read(path):
    return json.loads(path.read_text())


def run_worker(source, cells, timeout):
    worker = ROOT / 'scripts/libreoffice_reference_worker.py'
    with tempfile.TemporaryDirectory(prefix='hybridguard-lo-request-') as folder:
        folder = Path(folder)
        request, result = folder / 'request.json', folder / 'result.json'
        save(request, {'input': str(source), 'cells': cells})
        started = time.perf_counter()
        process = subprocess.Popen(['/usr/bin/python3', str(worker), str(request), str(result)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.returncode:
                return {'status': 'worker_failed', 'returncode': process.returncode,
                        'stdout': stdout[-2000:], 'stderr': stderr[-2000:],
                        'wall_seconds': time.perf_counter() - started}
            return {**read(result), 'status': 'complete',
                    'worker_returncode': process.returncode,
                    'stderr': stderr[-2000:],
                    'wall_seconds_parent': time.perf_counter() - started}
        except subprocess.TimeoutExpired:
            # The worker starts LibreOffice in its own process group. Kill that
            # group so a timeout cannot leave a hidden office process running.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate(timeout=10)
            return {'status': 'timeout', 'timeout_seconds': timeout,
                    'stdout': stdout[-2000:], 'stderr': stderr[-2000:],
                    'wall_seconds': time.perf_counter() - started}


def prior_verified():
    lock = read(PUBLIC / 'prediction_lock.json')
    for filename, key in [('source_lock.json', 'source_lock_sha256'),
                          ('registration.json', 'registration_sha256'),
                          ('acquisition_receipt.json', 'acquisition_receipt_sha256')]:
        assert sha(PUBLIC / filename) == lock[key]
    for base, files in [(ROOT, read(PUBLIC / 'source_lock.json')['files']),
                        (PUBLIC, lock['files']), (PUBLIC, lock['inputs'])]:
        for path, expected in files.items():
            assert sha(base / path) == expected, path
    return lock


def smoke():
    """Real independent-engine check, including blank text and an array follower."""
    from openpyxl import Workbook
    from openpyxl.worksheet.formula import ArrayFormula
    with tempfile.TemporaryDirectory(prefix='hybridguard-lo-smoke-') as folder:
        source = Path(folder) / 'smoke.xlsx'
        workbook = Workbook(); sheet = workbook.active
        formulas = {'A1': '=1+2', 'A2': '=TRUE()', 'A3': '="hello"',
                    'A4': '=1/0', 'A5': '=SUM(A1,4)', 'A6': '=""'}
        for address, formula in formulas.items():
            sheet[address] = formula
        sheet['A7'] = ArrayFormula(ref='A7:A8', text='=ROW(A7:A8)')
        workbook.save(source)
        before = sha(source)
        result = run_worker(source, ['Sheet!A' + str(i) for i in range(1, 9)], timeout=60)
        assert result['status'] == 'complete', result
        cells = result['cells']
        assert cells['Sheet!A1']['value'] == 3
        assert cells['Sheet!A2']['kind'] == 'boolean' and cells['Sheet!A2']['value'] is True
        assert cells['Sheet!A3']['kind'] == 'text' and cells['Sheet!A3']['value'] == 'hello'
        assert cells['Sheet!A4']['kind'] == 'error' and cells['Sheet!A4']['error'] == '#DIV/0!'
        assert cells['Sheet!A5']['value'] == 7
        assert cells['Sheet!A6']['kind'] == 'text' and cells['Sheet!A6']['value'] == ''
        assert cells['Sheet!A7']['value'] == 7 and cells['Sheet!A8']['value'] == 8
        assert sha(source) == before
        assert result['read_only'] and result['forced_calculate_all'] and not result['workbook_saved']
        save(ROOT / 'qa/LIBREOFFICE_SMOKE_20261015.json', {
            'all_assertions_passed': True, 'source_hash_before': before, 'source_hash_after': sha(source),
            'result': result, 'purpose': 'execution semantics smoke only; no business labels',
            'runner_sha256': sha(Path(__file__)),
            'worker_sha256': sha(ROOT / 'scripts/libreoffice_reference_worker.py')})
        print('8-cell read-only integration check passed, including array follower and blank text')


def register():
    if RUN.exists():
        raise SystemExit('Preserve registered execution evidence; select a new run')
    prior_verified()
    selected = read(PUBLIC / 'registration.json')['selected_files']
    version = subprocess.check_output(['/usr/bin/libreoffice', '--version'], text=True, timeout=15).strip()
    sources = [Path(__file__), ROOT / 'scripts/execution_reference.py',
               ROOT / 'scripts/libreoffice_reference_worker.py', ROOT / 'tests/test_execution_reference.py']
    sources += sorted((ROOT / 'baseline/source').rglob('*.py'))
    save(RUN / 'registration.json', {
        'role': 'revealed public development: independent execution compatibility only',
        'final_validation_eligible': False, 'new_final_sources': 0, 'new_final_families': 0,
        'selection': 'all 14 previously acquired pinned Pycel workbooks, including zero-formula input',
        'selected_files': selected, 'no_business_repair_labels': True,
        'reference': 'LibreOffice isolated profile, read-only import, explicit calculateAll, never store',
        'timeout_seconds': 120, 'reference_failure_policy': 'retain timeout/load failure; never drop cells',
        'comparison': 'numeric relative/absolute tolerance 1e-8; text exact; booleans distinct',
        'logical_value_caveat': 'UNO numerical outputs with a logical number format are represented as boolean',
        'cache_policy': 'original cache may be stale; error cache is observed evidence, not intentional-error proof',
        'source_immutability': 'verify exact input hashes before and after every run',
        'previous_predictions_sha256': sha(PUBLIC / 'prediction_lock.json'),
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    save(RUN / 'source_lock.json', {
        'files': {str(path.relative_to(ROOT)): sha(path) for path in sources},
        'environment': {'python': sys.version, 'system_python': subprocess.check_output(
            ['/usr/bin/python3', '--version'], text=True).strip(), 'libreoffice': version,
            'binaries': {path: sha(Path(path).resolve()) for path in
                         ['/usr/lib/libreoffice/program/soffice.bin', '/usr/bin/python3']},
            'uno_module_sha256': sha(Path('/usr/lib/python3/dist-packages/uno.py'))},
    })
    print('Registered', len(selected), 'excluded development workbooks;', version, flush=True)


def verify_source():
    for path, expected in read(RUN / 'source_lock.json')['files'].items():
        assert sha(ROOT / path) == expected, path
    return prior_verified()


def execute():
    if (RUN / 'execution_lock.json').exists() or (RUN / 'cases').exists():
        raise SystemExit('Preserve execution evidence, including incomplete attempts')
    verify_source()
    receipt = read(PUBLIC / 'acquisition_receipt.json')
    records = {item['source_path']: item for item in receipt['records']}
    selected = read(RUN / 'registration.json')['selected_files']
    cases = []
    files = {}
    for number, relative in enumerate(selected, 1):
        source = PUBLIC / 'raw' / relative
        case = f'public{number:02d}'
        entry = {'id': case, 'source_path': relative,
                 'input_sha256': records[relative].get('sha256'),
                 'labels_available': False, 'business_truth': None}
        if not source.exists():
            entry.update(status='acquisition_failed')
            cases.append(entry); continue
        entry['input_sha256'] = sha(source)
        assert entry['input_sha256'] == records[relative]['sha256']
        try:
            declarations = formula_declarations(source)
            cells = sorted(declarations)
            model = WorkbookModel.from_xlsx(source)
            values, errors = model.evaluate()
            entry.update(raw_formula_declarations=len(declarations),
                         loaded_formula_cells=len(model.formulas),
                         loaded_formula_omissions=sorted(set(declarations) -
                                                         {s + '!' + a for s, a in model.formulas}),
                         original_model_evaluation_errors=len(errors))
            # Record original-model execution BEFORE obtaining the reference.
            original = {}
            for sheet, address in model.formulas:
                original[sheet + '!' + address] = typed_value(
                    values.get((sheet, address)), errors.get((sheet, address)))
            original_path = RUN / 'cases' / (case + '_original.json')
            save(original_path, original); files[str(original_path.relative_to(RUN))] = sha(original_path)
            result = run_worker(source, cells, timeout=read(RUN / 'registration.json')['timeout_seconds'])
            result_path = RUN / 'cases' / (case + '_reference.json')
            save(result_path, result); files[str(result_path.relative_to(RUN))] = sha(result_path)
            entry['worker'] = {key: value for key, value in result.items() if key != 'cells'}
            entry.update(status=result['status'])
        except Exception as error:
            entry.update(status='audit_failed', error=repr(error))
        entry['source_hash_after'] = sha(source)
        assert entry['source_hash_after'] == entry['input_sha256'], 'Input workbook was changed'
        entry['source_unchanged'] = True
        cases.append(entry)
        print(case, relative, entry['status'], entry.get('raw_formula_declarations'),
              entry.get('worker', {}).get('wall_seconds_parent'), flush=True)
    report = {
        'status': 'complete', 'role': 'excluded public software fixture execution audit',
        'origin': 'dgorissen/pycel pinned fixtures; no final-validation eligibility',
        'labels_available': False, 'precision': None, 'coverage': None,
        'cases': cases, 'case_count': len(cases),
        'python': platform.python_version(), 'platform': platform.platform(),
        'command': [sys.executable, *sys.argv],
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'interpretation': 'Independent execution agreement is not a business-intent or repair label.',
        'source_hashes': {relative: sha(PUBLIC / 'raw' / relative) for relative in selected
                          if (PUBLIC / 'raw' / relative).exists()},
    }
    save(RUN / 'execution.json', report); files['execution.json'] = sha(RUN / 'execution.json')
    save(RUN / 'execution_lock.json', {'files': files,
        'source_lock_sha256': sha(RUN / 'source_lock.json'),
        'registration_sha256': sha(RUN / 'registration.json'),
        'inputs': report['source_hashes'], 'business_labels_read': [], 'repair_proposals_generated': False})


def verify_execution():
    verify_source()
    lock = read(RUN / 'execution_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'registration.json') == lock['registration_sha256']
    for path, expected in lock['files'].items():
        assert sha(RUN / path) == expected, path
    for path, expected in lock['inputs'].items():
        assert sha(PUBLIC / 'raw' / path) == expected, path
    assert not lock['business_labels_read'] and not lock['repair_proposals_generated']


def analysis_report():
    verify_execution()
    execution = read(RUN / 'execution.json')
    cases, totals = [], Counter()
    for entry in execution['cases']:
        case = dict(entry)
        declarations = formula_declarations(PUBLIC / 'raw' / entry['source_path'])
        totals['raw_formula_declarations'] += len(declarations)
        if entry['status'] != 'complete':
            totals['reference_failed_formula_declarations'] += len(declarations)
            cases.append(case); continue
        result = read(RUN / 'cases' / (entry['id'] + '_reference.json'))
        original = read(RUN / 'cases' / (entry['id'] + '_original.json'))
        assert set(result['cells']) == set(declarations)
        assert result['read_only'] and result['forced_calculate_all'] and not result['workbook_saved']
        comparisons, details = Counter(), []
        for label, declaration in sorted(declarations.items()):
            cache = declaration['cache']; independent = result['cells'][label]
            cached_result = compare(independent, cache)
            actual = original.get(label)
            engine_result = compare(actual, independent) if actual else 'not_loaded_by_original_reader'
            comparisons['cache_' + cached_result] += 1
            comparisons['original_vs_reference_' + engine_result] += 1
            comparisons['reference_kind_' + independent['kind']] += 1
            details.append({'cell': label, 'declaration_attributes': declaration['attributes'],
                            'original_cache': cache, 'libreoffice': independent,
                            'original_model': actual, 'cache_comparison': cached_result,
                            'original_vs_reference': engine_result})
        case.update(comparisons=dict(comparisons), details=details)
        totals.update(comparisons);cases.append(case)
    return {'cases': cases, 'totals': dict(totals), 'business_labels_available': False,
            'precision': None, 'coverage': None, 'final_validation_eligible': False,
            'execution_lock_sha256': sha(RUN / 'execution_lock.json'),
            'interpretation': 'Execution compatibility only; cache errors do not prove intended errors, '
                              'engine agreement does not prove business intent or authorize a repair.'}


def analyze():
    if (RUN / 'analysis.json').exists():
        raise SystemExit('Preserve analysis evidence')
    result = analysis_report()
    save(RUN / 'analysis.json', result)
    save(RUN / 'analysis_lock.json', {'analysis_sha256': sha(RUN / 'analysis.json'),
                                     'execution_lock_sha256': sha(RUN / 'execution_lock.json')})
    print(json.dumps(result['totals'], indent=2))


def verify():
    expected = analysis_report()
    assert expected == read(RUN / 'analysis.json')
    lock = read(RUN / 'analysis_lock.json')
    assert sha(RUN / 'analysis.json') == lock['analysis_sha256']
    assert sha(RUN / 'execution_lock.json') == lock['execution_lock_sha256']
    save(ROOT / 'qa/EXECUTION_REFERENCE_VERIFICATION_20261015.json', {
        'all_locks_verified': True, 'analysis_recomputed_per_cell': True,
        'original_inputs_unchanged': True, 'totals': expected['totals'],
        'final_validation_eligible': False, 'precision': None, 'coverage': None,
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'analysis_sha256': sha(RUN / 'analysis.json')})
    print('Verified exact inputs, source locks, typed reference results and every comparison')


if __name__ == '__main__':
    stages = {'smoke': smoke, 'register': register, 'execute': execute, 'analyze': analyze, 'verify': verify}
    stages[sys.argv[1]]()
