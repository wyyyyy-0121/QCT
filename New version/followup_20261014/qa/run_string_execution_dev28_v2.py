"""All original formulas and frozen independent smoke, including unsupported."""
from pathlib import Path
from collections import Counter
import hashlib
import os
import sys
import time

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'qa'),
               str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_string_execution_dev28 import RUN as PRIOR, CASES, value_record
from hard_reference_string_execution_dev28 import verify_execution, reference_value, check_provenance
from string_execution_dev28_v2 import execute, parse, Unsupported, VERSION
from typed_execution_adapter import load_typed_inputs, ExcelError

RUN = ROOT / 'development/string_execution_dev28_v2'


def main():
    assert not RUN.exists()
    verify_execution()
    RUN.mkdir()
    (RUN / '.gitignore').write_text('local/\n')
    refs = [PRIOR / 'local/hard_reference_cv500_uno.json.gz',
            PRIOR / 'local/hard_reference_smoke_uno.json.gz', PRIOR / 'local/hard_reference_smoke.xlsx']
    paths = [Path(__file__), ROOT / 'scripts/string_execution_dev28_v2.py',
             ROOT / 'scripts/string_execution_dev28.py', ROOT / 'scripts/typed_execution_adapter.py',
             ROOT / 'tests/test_string_execution_dev28_v2.py',
             ROOT / 'STRING_EXECUTION_DEV28_V2_REGISTRATION_20261018.md',
             ROOT / 'qa/hard_reference_string_execution_dev28.py',
             ROOT / 'qa/run_string_execution_dev28.py', ROOT / 'scripts/run_selector_dev5.py']
    save(RUN / 'source_lock.json', dict(version=VERSION,
         files={str(p.relative_to(ROOT)): sha(p) for p in paths},
         inputs={name: sha(p) for name, p in CASES},
         local_references={str(p.relative_to(ROOT)): sha(p) for p in refs},
         prior_execution_lock_sha256=sha(PRIOR / 'execution_lock.json'),
         prior_hard_reference_sha256=sha(PRIOR / 'hard_recalculation_reference.json')))
    # Reference outputs enter comparison only after inference has been locked.
    accesses = set()
    active = [True]
    def guard(event, args):
        if not active[0] or event != 'open' or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        name = os.fsdecode(args[0])
        if any(s in name.lower() for s in ['after.xlsx', 'natural_truth', 'natural_score', 'author_diff',
                                         'certification', 'historical_fix', 'natural_pair_docs', '_uno.json']):
            raise PermissionError('v2 inference cannot read truth/reference: ' + name)
        if '/raw/' in name or name.endswith('hard_reference_smoke.xlsx'):
            accesses.add(name)
    sys.addaudithook(guard)
    rows, local = [], []
    wall, cpu = time.perf_counter(), time.process_time()
    for case, path in CASES + [('smoke', refs[2])]:
        book = openpyxl.load_workbook(path, data_only=False)
        typed = load_typed_inputs(path)
        formulas = {(s.title, c.coordinate): c.value for s in book for row in s for c in row if c.data_type == 'f'}
        items = []
        for key, formula in sorted(formulas.items()):
            item = dict(cell=key[0] + '!' + key[1], formula_sha256=hashlib.sha256(formula.encode()).hexdigest())
            try:
                node = parse(formula)
                count = check_provenance(formula, key[0])
                value = execute(node, key[0], typed, formula_cells=formulas, sheet_names=book.sheetnames)
                item.update(status='executed', value=value_record(value), independent_references_checked=count)
                local.append(dict(case=case, cell=item['cell'], value=value, is_error=isinstance(value, ExcelError)))
            except Unsupported as error:
                item.update(status='unsupported', reason=error.code)
            items.append(item)
        rows.append(dict(case=case, formulas=len(formulas), counts=dict(Counter(
            r['reason'] if r['status'] == 'unsupported' else 'executed' for r in items)), cells=items))
    save(RUN / 'execution.json.gz', dict(cases=rows, input_accesses=sorted(accesses),
         labels_read=[], reference_outputs_read=[], repair_suggestions_generated=False,
         cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall,
         final_validation_eligible=False))
    save(RUN / 'execution_lock.json', dict(execution_sha256=sha(RUN / 'execution.json.gz'),
         source_lock_sha256=sha(RUN / 'source_lock.json')))
    active[0] = False
    # Full text is transient here and never submitted; output records are hashed.
    reference = {'cv500': read(refs[0]), 'smoke': read(refs[1])}
    comparisons = []
    for r in local:
        if r['case'] not in reference:
            continue
        raw = reference[r['case']]['cells'][r['cell']]
        expected = reference_value(raw)
        value = r['value']
        match = (type(value) is type(expected) and value == expected) or (
            type(value) in (int, float) and type(expected) in (int, float) and value == expected)
        comparisons.append(dict(case=r['case'], cell=r['cell'], exact_agreement=match,
                                reference=value_record(expected)))
    lock = read(RUN / 'source_lock.json')
    for rel, digest in {**lock['files'], **lock['local_references']}.items():
        assert sha(ROOT / rel) == digest, rel
    verify_execution()
    for name, path in CASES:
        assert sha(path) == lock['inputs'][name]
    save(RUN / 'independent_reference.json', dict(rows=comparisons,
         exact_agreements=sum(r['exact_agreement'] for r in comparisons), compared=len(comparisons),
         execution_lock_sha256=sha(RUN / 'execution_lock.json'),
         all_unsupported_retained=True, labels_read=[], business_truth_claimed=False,
         final_validation_eligible=False))
    for row in rows:
        print('DEV28 V2', row['case'], row['formulas'], row['counts'], flush=True)
    print('DEV28 V2 independently matched', sum(r['exact_agreement'] for r in comparisons), '/', len(comparisons), flush=True)
    assert len(comparisons) == 522 and all(r['exact_agreement'] for r in comparisons)
    assert rows[-1]['formulas'] == 24 and rows[-1]['counts']['executed'] == 17
    assert sum(r['formulas'] for r in rows[:-1]) == 1003


if __name__ == '__main__':
    main()
