"""Author-only dev18 labels and whole-origin folds, after the feature lock."""
from collections import Counter, defaultdict
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from build_candidates_dev18 import DATA, OLD, compact
from run_selector_dev5 import read, save, sha
from prepare_annotation_dev14 import equivalent as lcoe_equivalent
from product_sum_oracle_dev17 import equivalent as public_equivalent
from openpyxl import load_workbook
from semantic_fingerprint_dev16 import fingerprint
from formulaguard.workbook import WorkbookModel

def label(candidate, truth, equivalent):
    cell = candidate['cell']
    if cell not in truth['expected_formulas']: return None
    # Correct cells cannot become successful repairs through equivalent rewrites.
    return int(cell in truth['errors'] and equivalent(candidate['formula'], truth['expected_formulas'][cell], cell))

def prepare():
    if (DATA/'label_preparation_lock.json').exists(): raise SystemExit('Preserve labels')
    lock = read(DATA/'feature_lock.json')
    for rel, digest in lock['files'].items(): assert sha(DATA/rel) == digest
    old = read(OLD/'heldout_truth.json.gz')['cases']
    public = {t['id']:t for t in read(ROOT/'development/multisource_dev17_inputs_v1/truth.json')['cases']}
    cases = {}; duplicate = defaultdict(list); files = {}; summaries = []
    for item in read(DATA/'public_index.json'):
        case = item['case']
        payload = read(DATA/'features'/(case.replace('/', '__')+'.json.gz'))
        w = None
        if item['group'] == 'public_relations':
            t = public[item['id']]
            w = load_workbook(ROOT/item['input'])
            eq = lambda a,b,c: public_equivalent(a,b,c.rsplit('!',1)[0],w)
            family = item['origin_group']+'__original_template'
        else:
            t = old[case]; family = t['family']
            eq = (lambda a,b,c: lcoe_equivalent(a,b)) if item['group'] == 'lcoe' else (lambda a,b,c: a == b)
        t = {k:t[k] for k in ['expected_formulas', 'errors', 'observed_formulas', 'scenario']}
        cases[case] = {**t, 'family':family, 'origin_group':item['origin_group'], 'group':item['group']}
        labels = {c['id']:label(c,t,eq) for c in payload['candidates']}
        path = DATA/'case_labels'/(case.replace('/', '__')+'.json.gz')
        compact(path, labels); files[str(path.relative_to(DATA))] = sha(path)
        summaries.append({'case':case, 'positive':sum(y==1 for y in labels.values()),
                          'negative':sum(y==0 for y in labels.values()), 'unknown':sum(y is None for y in labels.values())})
        duplicate[fingerprint(WorkbookModel.from_xlsx(ROOT/item['input']), item['parallel_sheets'])].append(case)
        if w: w.close()
        print('labelled', case, summaries[-1], flush=True)
    for members in duplicate.values(): assert len({cases[c]['origin_group'] for c in members}) == 1
    origins = sorted({t['origin_group'] for t in cases.values()}); assert len(origins) == 5
    folds = []
    for origin in origins:
        test = [c for c,t in cases.items() if t['origin_group']==origin]
        train = [c for c in cases if c not in set(test)]
        rows = []
        for c in train:
            labels = read(DATA/'case_labels'/(c.replace('/', '__')+'.json.gz'))
            rows.extend({'id':cid, 'label':y, 'case':c, 'family':cases[c]['family'],
                         'source':cases[c]['origin_group']} for cid,y in labels.items() if y is not None)
        name = 'source__'+origin; path = DATA/'training_labels'/(name+'.json.gz')
        compact(path, {'rows':rows, 'training_cases':train, 'heldout_cases':test})
        files[str(path.relative_to(DATA))] = sha(path)
        folds.append({'id':name, 'origin':origin, 'train_cases':train, 'test_cases':test,
                      'train_label_file':str(path.relative_to(DATA)), 'train_label_sha256':sha(path)})
    save(DATA/'fold_index.json', {'folds':folds, 'case_groups':{c:{k:t[k] for k in ['family','origin_group','group','scenario']} for c,t in cases.items()},
         'semantic_duplicate_groups':[m for m in duplicate.values() if len(m)>1], 'same_semantic_input_never_crosses_folds':True})
    compact(DATA/'heldout_truth.json.gz', {'cases':cases, 'scope':'revealed development only'})
    save(DATA/'label_counts.json', summaries)
    for n in ['fold_index.json', 'heldout_truth.json.gz', 'label_counts.json']: files[n] = sha(DATA/n)
    save(DATA/'label_preparation_lock.json', {'files':files, 'feature_lock_sha256':sha(DATA/'feature_lock.json'),
         'author_sources':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__), ROOT/'scripts/product_sum_oracle_dev17.py']}})
    print('DEV18 LABELS LOCKED', len(cases), len(folds), flush=True)

if __name__ == '__main__': prepare()
