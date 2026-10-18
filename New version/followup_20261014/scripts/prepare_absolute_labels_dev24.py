"""Author-only fold files from independently audited dev23 relation states."""
from pathlib import Path
from collections import Counter
import hashlib
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from prepare_tristate_states_dev23 import DATA as STATES
from build_keep_features_dev21 import BASE, DATA as FEATURES, case_path
from build_candidates_dev18 import compact
from absolute_selection_dev24 import options
from certified_preferences_dev22 import certified_pairs
DATA = ROOT/'development/absolute_selection_dev24_data_v1'


def digest(rows, fields):
    return hashlib.sha256('\n'.join('\t'.join(str(r[k]) for k in fields) for r in rows).encode()).hexdigest()


def prepare():
    if DATA.exists(): raise SystemExit('Preserve dev24 labels')
    verified = read(ROOT/'qa/TRISTATE_RELATIONS_DEV23_VERIFICATION_20261018.json')
    assert verified['all_saved_checks_passed']
    lock = read(STATES/'preparation_lock.json')
    assert verified['preparation_lock_sha256'] == sha(STATES/'preparation_lock.json')
    for rel,value in lock['files'].items(): assert sha(STATES/rel)==value, rel
    metadata = {r['case']: r for r in read(STATES/'state_counts.json')}
    files = {}; summaries = []; wall = time.perf_counter()
    sources = [Path(__file__), ROOT/'scripts/absolute_selection_dev24.py', ROOT/'scripts/certified_preferences_dev22.py',
        ROOT/'ABSOLUTE_SELECTION_DEV24_PREREGISTRATION_20261018.md']
    save(DATA/'source_lock.json', dict(files={str(p.relative_to(ROOT)):sha(p) for p in sources}))
    for item in read(BASE/'public_index.json'):
        case = item['case']; meta = metadata[case]
        states = read(STATES/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives']
        chosen = options(states)
        rows = [{**{k:r[k] for k in ['case','cell','id','kind','label']},
            'family':meta['family'], 'source':meta['source']} for r in chosen]
        pairs,stats = certified_pairs(states)
        # Reconstructing from sampled options needs a keep row even if its
        # state is unknown. Such placeholders never become training examples.
        present = {(r['cell'],r['id']) for r in rows}
        rows += [{**{k:r[k] for k in ['case','cell','id','kind','label']}, 'family':meta['family'],'source':meta['source']}
            for r in states if r['kind']=='keep' and (r['cell'],r['id']) not in present]
        p = DATA/'author_case_options'/(case_path(case)+'.json.gz')
        compact(p, dict(case=case, alternatives=rows)); files[str(p.relative_to(DATA))]=sha(p)
        summaries.append(dict(case=case, source=meta['source'], family=meta['family'], options=len(chosen),
            classes=dict(Counter(str(r['label']) for r in chosen)),
            option_sha256=digest(chosen,['case','cell','id','kind','label']),
            directed_pairs=len(pairs), pair_sha256=digest(pairs,['case','cell','left_id','right_id','label']), **{'pair_stats':stats}))
        print('prepared dev24',case,len(chosen),len(pairs),flush=True)
    folds=[]
    for fold in read(BASE/'fold_index.json')['folds']:
        rows=[]
        for case in fold['train_cases']:
            assert metadata[case]['source']!=fold['origin']
            rows.extend(read(DATA/'author_case_options'/(case_path(case)+'.json.gz'))['alternatives'])
        p=DATA/'training_labels'/(fold['id']+'.json.gz')
        compact(p, dict(training_cases=fold['train_cases'],heldout_cases=fold['test_cases'],alternatives=rows))
        files[str(p.relative_to(DATA))]=sha(p)
        folds.append({**fold, 'train_label_file':str(p.relative_to(DATA)), 'train_label_sha256':sha(p)})
        print('prepared dev24 fold',fold['id'],len(rows),flush=True)
    for name,value in [('fold_index.json',dict(folds=folds)),('state_counts.json',summaries)]:
        save(DATA/name,value); files[name]=sha(DATA/name)
    save(DATA/'preparation_lock.json',dict(files=files,source_lock_sha256=sha(DATA/'source_lock.json'),
        upstream_state_lock_sha256=sha(STATES/'preparation_lock.json'), upstream_fold_index_sha256=sha(BASE/'fold_index.json'),
        feature_lock_sha256=sha(FEATURES/'feature_lock.json'),
        independent_certificate_verification_sha256=sha(ROOT/'qa/TRISTATE_RELATIONS_DEV23_VERIFICATION_20261018.json'),
        final_validation_eligible=False,wall_seconds=time.perf_counter()-wall))
    print('DEV24 FOLD LABELS LOCKED',flush=True)


if __name__=='__main__': prepare()
