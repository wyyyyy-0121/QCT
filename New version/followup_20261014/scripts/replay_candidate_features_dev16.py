"""Label-free feature reconstruction plus duplicate-input decision consistency."""
from collections import defaultdict
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_candidate_learning_dev16 import DATA,RUN,verify,protection
from build_candidates_dev16 import upstream
from candidate_features_dev16 import Context
from formulaguard.workbook import WorkbookModel
from run_selector_dev5 import read,save,sha

def decisions(rows):
    return sorted((r['cell'],r['suggested_formula'],r.get('probability')) for r in rows)

def main():
    verify();active,allowed,accesses,reads=protection()
    names=read(DATA/'feature_schema.json')['names'];count=0;wall=time.perf_counter();cpu=time.process_time()
    index=read(DATA/'public_index.json');cached={}
    for item in index:
        payload=read(DATA/'features'/(item['case'].replace('/','__')+'.json.gz'))
        cached[item['case']]=payload
        model=WorkbookModel.from_xlsx(ROOT/item['input'])
        models,obs=upstream(item);base={r['cell']:r for r in models['dev11']['rows']}
        context=Context(model,item['parallel_sheets'])
        for candidate in payload['candidates']:
            s,a=candidate['cell'].rsplit('!',1)
            f=context.features(s,a,candidate['formula'],candidate['origins'],base[candidate['cell']])
            assert [f[n] for n in names]==candidate['features'],(item['case'],candidate['cell'])
            count+=1
    foldindex=read(RUN/'fold_index.json')
    duplicate_comparisons=0
    for members in foldindex['semantic_duplicate_groups']:
        values=[]
        for case in members:
            payload=cached[case]
            values.append(sorted((c['cell'],c['formula'],tuple(c['origins']),tuple(c['features'])) for c in payload['candidates']))
        assert all(v==values[0] for v in values)
        for scheme in ['family','source']:
            relevant=[f for f in foldindex['folds'] if f['scheme']==scheme and members[0] in f['test_cases']]
            assert len(relevant)==1
            fold=relevant[0]
            predictions=[read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz')) for case in members]
            for mode in ['dev11','learned_only','keep_base_plus_learned']:
                ds=[decisions(p[mode]) for p in predictions]
                assert all(d==ds[0] for d in ds),(members,mode)
                duplicate_comparisons+=1
    active[0]=False;assert not reads
    out=ROOT/'qa/CANDIDATE_LEARNING_DEV16_FEATURE_REPLAY_20261018.json';assert not out.exists()
    save(out,{'cases':len(index),'candidate_vectors_rebuilt':count,'all_vectors_identical':True,
              'semantic_duplicate_groups':len(foldindex['semantic_duplicate_groups']),
              'duplicate_scheme_method_checks':duplicate_comparisons,'duplicate_predictions_identical':True,
              'training_labels_read':[],'heldout_labels_read':[],'accesses':sorted(accesses),
              'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
              'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'audit_script_sha256':sha(Path(__file__))})
    print('rebuilt feature vectors',count,'duplicate checks',duplicate_comparisons,flush=True)
if __name__=='__main__':main()
