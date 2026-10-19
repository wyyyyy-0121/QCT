#!/usr/bin/env python3
"""Prepare fixed M6 engineering conditions and separately locked score key."""
from copy import deepcopy
import datetime as dt
import json
from pathlib import Path
import sys

import openpyxl

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m6_relation'


def write(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


def main():
    _, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    EXPERIMENT.mkdir(exist_ok=False)
    for name in ('workbooks', 'requests', 'scoring'):
        (EXPERIMENT / name).mkdir()
    books = {}
    for name, formula in [('counter', '=B2*(3-C2)/2'), ('correct', '=B2/C2'), ('exception', '=B2*(2-C2)')]:
        path = EXPERIMENT / 'workbooks' / (name + '.xlsx')
        book = openpyxl.Workbook()
        book.active.title = 'Model'
        book.active['B2'], book.active['C2'], book.active['D2'] = 10, 1, formula
        book.save(path)
        books[name] = path
    epa = EVIDENCE.parent / 'epa_pairs/xlsx_export/oxidizers_before.xlsx'
    if sha256(epa) != '0acb06582e7f898b5bcbfe262b2f55294bd4b3a6d2eab63461f03c89ad86358c':
        raise SystemExit('EPA original differs from E3')
    symbols = {'q': {'units': {'flow': 1}}, 'd': {'units': {}}}
    ratio = [dict(lhs='y*d', rhs='q')]
    affine = [dict(lhs='y', rhs='q*(2-d)')]
    common = dict(sheet='Model', cell='D2', references={'B2': 'q', 'C2': 'd'},
                  symbols=symbols, output_units={'flow': 1}, relations=ratio)
    epa_request = dict(sheet='Design Parameters', cell='D36',
                       references={"'Data Inputs'!B23": 'q', 'D34': 'd'}, symbols=symbols,
                       output_units={'flow': 1}, relations=ratio,
                       branch={'guard': 'D35="Not applicable"', 'inactive': "'Data Inputs'!B23"})
    cases = []

    def add(name, source, base, changes, status, reason, semantic=None):
        request = deepcopy(base)
        request.update(deepcopy(changes))
        request.update(workbook=str(source), workbook_sha256=sha256(source))
        cases.append((name, request, dict(status=status, reason=reason, semantic=semantic)))

    add('epa_none', epa, epa_request, dict(relations=[]), 'abstain', 'missing_business_relation')
    add('epa_ratio', epa, epa_request, {}, 'propose', 'candidate_satisfies_explicit_relation', 'ratio')
    add('epa_conflict', epa, epa_request, dict(relations=ratio + affine), 'abstain', 'conflicting_business_relations')
    add('epa_wrong_guard', epa, epa_request, dict(branch={'guard': 'D35="active"', 'inactive': "'Data Inputs'!B23"}),
        'unsupported', 'guard or inactive branch differs')
    add('counter_ratio', books['counter'], common, {}, 'propose', 'candidate_satisfies_explicit_relation', 'ratio')
    add('counter_affine', books['counter'], common, dict(relations=affine), 'propose', 'candidate_satisfies_explicit_relation', 'affine')
    add('counter_none', books['counter'], common, dict(relations=[], symbols={'q': {'units': {}}, 'd': {'units': {}}}, output_units={}),
        'abstain', 'missing_business_relation')
    add('counter_units', books['counter'], common, dict(relations=[]),
        'abstain', 'missing_business_relation')
    add('counter_conflict', books['counter'], common, dict(relations=ratio + affine), 'abstain', 'conflicting_business_relations')
    add('counter_missing_mapping', books['counter'], common, dict(references={'B2': 'q'}), 'unsupported', 'missing_reference_mapping')
    add('counter_nonlinear', books['counter'], common, dict(relations=[dict(lhs='y*y', rhs='q*q')]),
        'unsupported', 'output_relation_not_linear_and_unique')
    add('counter_units_mismatch', books['counter'], common, dict(output_units={'mass': 1}),
        'unsupported', 'relation_units_mismatch')
    add('counter_nonunique_domain', books['counter'], common, dict(relations=[dict(lhs='y*(d-1)', rhs='q')]),
        'abstain', 'output_coefficient_not_provably_nonzero')
    add('counter_undeclared', books['counter'], common, dict(relations=[dict(lhs='y*x', rhs='q')]),
        'unsupported', 'arithmetic syntax unsupported')
    add('correct_original', books['correct'], common, {}, 'abstain', 'original_satisfies_contract')
    add('legal_exception', books['exception'], common, dict(relations=affine), 'abstain', 'original_satisfies_contract')
    assert len(cases) == 16
    manifest, expected, files = [], {}, [epa, *books.values()]
    for name, request, target in cases:
        path = EXPERIMENT / 'requests' / (name + '.json')
        write(path, request)
        files.append(path)
        expected[name] = target
        manifest.append(dict(id=name, argv=[sys.executable, str(ROOT / 'tools/predict_relation_m6.py'), str(path),
                                           '--output', 'prediction.json'], outputs=['prediction.json'], timeout_seconds=120))
    manifest_path = EXPERIMENT / 'manifest.jsonl'
    with manifest_path.open('x') as handle:
        handle.write(''.join(json.dumps(row) + '\n' for row in manifest))
    key = EXPERIMENT / 'scoring/expected.json'
    write(key, expected)
    files += [manifest_path, key, Path(__file__), ROOT / 'MODEL_M6_RELATION_PLAN.md',
              ROOT / 'tools/relation_candidates_m6.py', ROOT / 'tools/predict_relation_m6.py',
              ROOT / 'tools/e3_contract.py', ROOT / 'tools/trace_paper_candidates.py',
              ROOT / 'tools/candidate_gate_m1.py', RUNNER]
    lock = dict(created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                files_sha256={str(p): sha256(p) for p in files}, workers=20, task_count=16,
                input_model_lock_sha256=sha256(EVIDENCE / 'input_model_lock.json'),
                relation_origin='Manually supplied; engineering conditions plus one revealed EPA target',
                automatic_relation_extraction=False, final_validation_eligible=False)
    write(EXPERIMENT / 'input_lock.json', lock)
    print('M6 INPUTS LOCKED', manifest_path)


if __name__ == '__main__':
    main()
