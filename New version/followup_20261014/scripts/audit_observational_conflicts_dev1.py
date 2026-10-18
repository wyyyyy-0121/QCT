"""Revealed-data diagnostic of identical observations with conflicting labels.

This script intentionally reads truth. It must never be imported by a selector.
Workbook identity excludes the source path and transient parser caches; those
are not business information. Every public workbook field used by the current
reader is retained. This is an identifiability audit, not a metric exemption.
"""
from collections import defaultdict
from pathlib import Path
import datetime
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/observational_conflicts_dev1'
sys.path.insert(0, str(ROOT / 'scripts'))
from run_selector_dev8 import read, save, sha, RUN as CONTROL, truth_and_observed
from formulaguard.workbook import WorkbookModel

FIELDS = ['cells', 'formulas', 'cell_visibility', 'number_formats',
          'sheet_visibility', 'formula_kinds', 'shared_formula_groups',
          'shared_formula_regions', 'header_partition_metadata_complete',
          'hidden_rows', 'hidden_columns', 'merged_ranges', 'formula_regions']


def typed(value):
    if isinstance(value, dict):
        pairs = [[typed(k), typed(v)] for k,v in value.items()]
        return ['dict', sorted(pairs, key=lambda p:json.dumps(p[0], sort_keys=True))]
    if isinstance(value, (set, frozenset)):
        return ['set', sorted([typed(v) for v in value],key=lambda p:json.dumps(p,sort_keys=True))]
    if isinstance(value, (tuple,list)):
        return [type(value).__name__, [typed(v) for v in value]]
    if hasattr(value,'isoformat'):
        return [type(value).__name__,value.isoformat()]
    if value is None or isinstance(value,(str,int,float,bool)):
        return [type(value).__name__,value]
    raise TypeError('Unsupported observed metadata: '+type(value).__name__)


def fingerprint(model, parallel_sheets):
    payload = {field:typed(getattr(model,field)) for field in FIELDS}
    payload['parallel_sheets'] = parallel_sheets
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def main():
    if RUN.exists():
        raise SystemExit('Preserve existing identifiability audit')
    buckets=defaultdict(list)
    for item in read(CONTROL/'public_index.json'):
        model=WorkbookModel.from_xlsx(ROOT/item['input'])
        digest=fingerprint(model,item['parallel_sheets'])
        truth,observed=truth_and_observed(item)
        assert observed=={s+'!'+a:f for (s,a),f in model.formulas.items()}
        buckets[digest].append((item,truth,observed))
    conflicts=[]
    for digest,records in buckets.items():
        if len(records)<2:
            continue
        disputed={cell for cell in records[0][2] if len({r[1]['expected_formulas'][cell]
                    for r in records})>1}
        if not disputed:
            continue
        members=[{'id':i['id'],'group':i['group'],'input':i['input'],
                  'input_sha256':sha(ROOT/i['input']),
                  'errors':len(t['errors']), 'scenario':t.get('scenario')} for i,t,_o in records]
        examples=[{'cell':cell,'observed':records[0][2][cell],
                   'expected_by_case':{i['group']+'/'+i['id']:t['expected_formulas'][cell]
                                       for i,t,_o in records}} for cell in sorted(disputed)]
        conflicts.append({'observed_fingerprint':digest,'members':members,
                          'conflicting_cells':len(disputed),'conflicts':examples})
    pair=next(c for c in conflicts if {'c05','c06'} <= {m['id'] for m in c['members']})
    assert len({m['input_sha256'] for m in pair['members']})==1
    assert pair['conflicting_cells']==24
    result={'role':'revealed diagnostic only; answers deliberately read; never predictor input',
            'observed_fields':FIELDS,'source_paths_and_transient_caches_excluded':True,
            'cases':sum(len(v) for v in buckets.values()),
            'distinct_observed_inputs':len(buckets),'conflicting_groups':conflicts,
            'byte_identical_c05_c06_pair':True,
            'pair_limit':{'scope':'c05/c06 only, equal case weighting and identical semantic inputs',
                          'erroneous_cells_in_c06':24,'clean_cells_in_c05_at_same_positions':24,
                          'maximum_pooled_precision_for_any_correct_repair':0.5,
                          'reason':'Every correct repair of c06 necessarily proposes the same wrong change in c05.',
                          'coverage_if_abstaining_on_all_conflicts':0.0},
            'metric_denominators_unchanged':True,'final_validation_eligible':False,
            'script_sha256':sha(Path(__file__)),
            'control_public_index_sha256':sha(CONTROL/'public_index.json'),
            'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(RUN/'AUDIT.json',result)
    print(json.dumps({'cases':result['cases'],'distinct_observed_inputs':len(buckets),
                      'conflicting_groups':len(conflicts),'pair_limit':result['pair_limit']},indent=2))


if __name__=='__main__':
    main()
