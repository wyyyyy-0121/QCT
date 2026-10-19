#!/usr/bin/env python3
"""Score metadata mapping without importing its mapper or snapshot builder."""
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock
from score_relation_m6 import formula_value, branch_expression

EXPERIMENT = EVIDENCE / 'model_m8_mapping'
MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def verify_metadata(workbook, metadata):
    if set(metadata) != {'sheets'}:
        raise ValueError('Metadata top-level fields changed')
    for cells in metadata['sheets'].values():
        for cell in cells.values():
            allowed = {'kind', 'text'} if cell['kind'] == 'text' else {'kind'}
            if set(cell) != allowed or cell['kind'] not in {'text', 'formula', 'number', 'other'}:
                raise ValueError('Metadata includes values or unsupported fields')
    # Independent OOXML check: every actual formula slot is content-free in metadata.
    with zipfile.ZipFile(workbook) as archive:
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {row.attrib['Id']: row.attrib['Target'] for row in rels}
        names = set()
        for sheet in book.find(MAIN + 'sheets'):
            name = sheet.attrib['name']
            names.add(name)
            target = targets[sheet.attrib[REL + 'id']]
            path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
            xml = ET.fromstring(archive.read(path))
            formula_slots = {cell.attrib['r'] for cell in xml.iter(MAIN + 'c') if cell.find(MAIN + 'f') is not None}
            recorded = {address for address, cell in metadata['sheets'][name].items() if cell['kind'] == 'formula'}
            if recorded != formula_slots:
                raise ValueError('Formula slots differ from independent XML inventory')
        if names != set(metadata['sheets']):
            raise ValueError('Metadata sheet set changed')


def correct_repair(result, adjusted):
    if result['status'] != 'propose' or not result.get('suggested_formula'):
        return False, 0
    references = {'C18': 'q', 'S28': 'd'} if adjusted else {'D30': 'q', 'D31': 'd'}
    try:
        formula = branch_expression(result['suggested_formula']) if adjusted else result['suggested_formula']
        if adjusted:
            original = result['observed_formula']
            active = branch_expression(original)
            if (not original.endswith(active[1:] + ')') or not result['suggested_formula'].endswith(formula[1:] + ')')
                    or original[:-len(active)] != result['suggested_formula'][:-len(formula)]):
                return False, 0
        for q, d in [(10, 2), (5, 10), (Fraction(3, 2), Fraction(1, 2)), (21, 7), (11, 3)]:
            if formula_value(formula, references, q, d) != Fraction(q) / Fraction(d) * 100:
                return False, 0
        return True, 5
    except (ValueError, KeyError, SyntaxError, ZeroDivisionError):
        return False, 0


def main():
    _, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = json.loads(lock_path.read_text())
    for path, expected_hash in lock['files_sha256'].items():
        if sha256(Path(path)) != expected_hash:
            raise SystemExit('Locked input changed: ' + path)
    terminal = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    if terminal['input_lock_sha256'] != sha256(lock_path) or terminal['runtime_sha256'] != sha256(EXPERIMENT / 'runs/runtime.json'):
        raise SystemExit('Input/runtime lock differs')
    expected = json.loads((EXPERIMENT / 'scoring/expected.json').read_text())
    if len(terminal['outputs']) != 18 or {row['id'] for row in terminal['outputs']} != set(expected):
        raise SystemExit('Task coverage changed')
    counts, groups, mismatches, predictions, checked_metadata = Counter(), {}, [], {}, set()
    correct_faults, proposals, correct_originals_changed, fraction_checks = 0, 0, 0, 0
    for row in terminal['outputs']:
        key = row['id']
        target = expected[key]
        group = groups.setdefault(target['kind'], Counter())
        group['conditions'] += 1
        if row['status'] != 'complete':
            counts[row['status']] += 1
            group[row['status']] += 1
            mismatches.append(dict(id=key, terminal_status=row['status']))
            continue
        if sha256(Path(row['path'])) != row['sha256']:
            raise SystemExit('Output changed')
        result = json.loads(Path(row['path']).read_text())
        request_path = EXPERIMENT / 'requests' / (key + '.json')
        request = json.loads(request_path.read_text())
        if result['request_sha256'] != sha256(request_path) or result['metadata_sha256'] != sha256(Path(request['metadata'])):
            raise SystemExit('Prediction provenance changed')
        if any(field in request for field in ('references', 'relations', 'constraints', 'candidates')):
            raise SystemExit('Inference request contains manually supplied address/relation')
        pair = (request['workbook'], request['metadata'])
        if pair not in checked_metadata:
            verify_metadata(Path(pair[0]), json.loads(Path(pair[1]).read_text()))
            checked_metadata.add(pair)
        predictions[key] = result
        counts[result['status']] += 1
        group[result['status']] += 1
        if (result['status'], result['reason'], result.get('reference')) != (
                target['status'], target['reason'], target['reference']):
            mismatches.append(dict(id=key, status=result['status'], reason=result['reason'], reference=result.get('reference')))
        if result['formula_content_used_for_mapping'] or result['labels_read']:
            raise SystemExit('Mapping evidence boundary violated')
        if result.get('suggested_formula'):
            proposals += 1
            if target['kind'] == 'end_to_end_correct':
                correct_originals_changed += 1
        if target['is_fault']:
            correct, checked = correct_repair(result, key.endswith('adjusted'))
            correct_faults += correct
            fraction_checks += checked
    same_metadata = len({sha256(EXPERIMENT / 'metadata' / (name + '.json')) for name in (
        'original', 'fault_ratio', 'fault_adjusted')}) == 1
    same_mapping = all(predictions.get('qualified_standard', {}).get(key) == predictions.get('changed_formula', {}).get(key)
                       for key in ('status', 'reason', 'reference', 'candidates'))
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    diagnostic_passed = not mismatches and same_metadata and same_mapping
    gate = diagnostic_passed and correct_faults == 2 and correct_originals_changed == 0
    summary = dict(experiment='M8 static-label address mapping without target formulas', task_count=18,
                   counts=dict(counts), groups={key: dict(value) for key, value in groups.items()},
                   expectation_mismatches=mismatches, diagnostic_checks_passed=diagnostic_passed,
                   mechanism_continuation_gate_passed=gate,
                   decision='eligible_for_further_review' if gate else 'stop_label_only_mechanism_do_not_adopt',
                   end_to_end_faults=2, correct_fault_repairs=correct_faults,
                   end_to_end_correct_originals=2, correct_originals_modified=correct_originals_changed,
                   all_repair_proposals=proposals, independent_fraction_checks=fraction_checks,
                   original_and_fault_metadata_identical=same_metadata, formula_change_mapping_identical=same_mapping,
                   formula_slots_independently_verified=True, metadata_workbooks_checked=len(checked_metadata),
                   inference_addresses_manually_supplied=False, mapping_query_text_manually_supplied=True,
                   independent_human_annotation=False, final_validation_eligible=False,
                   natural_accuracy_established=False, natural_validation_sources=0, natural_validation_families=0,
                   runtime={key: runtime[key] for key in ('requested_worker_count', 'worker_count', 'wall_seconds',
                            'child_cpu_seconds', 'aggregate_peak_rss_bytes_sampled', 'all_tasks_complete')},
                   source_input_lock_sha256=sha256(lock_path), source_output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'))
    with (ROOT / 'MODEL_M8_MAPPING_SUMMARY.json').open('x') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(summary, indent=2))
    if not diagnostic_passed:
        raise SystemExit('M8 diagnostic discrepancy; preserve evidence and stop')


if __name__ == '__main__':
    main()
