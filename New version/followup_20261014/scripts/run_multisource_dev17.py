"""Complete public development pipeline, peer hypotheses and frozen learner transfer."""
from pathlib import Path
from collections import defaultdict
from copy import deepcopy
import argparse
import platform
import resource
import sys
import time
import joblib
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_annotation_dev15 import prediction as original_pipeline
from run_selector_dev5 import read,save,sha
from run_selector_dev8 import guard_prediction
from formulaguard.workbook import WorkbookModel
from candidate_features_dev16 import Context
from train_candidate_dev16 import infer
from peer_pool_dev17 import candidates
DATA=ROOT/'development/multisource_dev17_inputs_v1'
RUN=ROOT/'development/multisource_dev17_v1'
LEARNED=ROOT/'development/candidate_learning_dev16_v1'
MODEL=LEARNED/'models/source__uk_government.joblib.gz'
NAMES=['paper','dev11','note_only','dev11_plus_note','frozen_dev16','dev11_plus_frozen_dev16']

def protections():
    accesses,active=set(),[True];guard_prediction(accesses,active)
    def guard(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)):
            name=str(args[0])
            if any(x in name for x in ['prepare_multisource_dev17','product_sum_oracle_dev17',
                                      '/heldout_truth','/training_labels/']):
                raise PermissionError('Prediction cannot read author/oracle/labels')
    sys.addaudithook(guard)
    for p in [DATA/'truth.json',ROOT/'scripts/prepare_multisource_dev17.py',
              ROOT/'scripts/product_sum_oracle_dev17.py']:
        try:p.read_bytes()
        except PermissionError:pass
        else:raise AssertionError('oracle_guard')
    return active,accesses

def selection(rows,observed,paper=False):
    return [r for r in rows if r.get('suggested_formula') and r['suggested_formula']!=observed[r['cell']]
            and (paper or r.get('status')=='propose')]

def prediction(item,learner):
    base=original_pipeline(item)
    model=WorkbookModel.from_xlsx(ROOT/item['input'])
    observed=base['observed_formulas'];rows={r['cell']:r for r in base['dev11']['rows']}
    pool=defaultdict(set);peers={}
    for name,result in [('paper',base['paper']),('dev11',base['dev11']),('dev15',base['note_only'])]:
        for r in selection(result['rows'],observed,name=='paper'):
            pool[r['cell'],r['suggested_formula']].add(name)
    for sheet,address in model.formulas:
        for formula,why in candidates(model,sheet,address).items():
            label=sheet+'!'+address
            pool[label,formula].add('peer')
            peers[label,formula]=why
    context=Context(model,[]);schema=read(ROOT/'development/candidate_learning_dev16_data_v1/feature_schema.json')['names']
    records=[]
    for n,((cell,formula),origins) in enumerate(sorted(pool.items())):
        s,a=cell.rsplit('!',1)
        features=context.features(s,a,formula,origins,rows[cell])
        assert sorted(features)==schema
        records.append({'id':str(n),'cell':cell,'formula':formula,'origins':sorted(origins),
                        'eligible':bool(features['complete_ast_pair'] and features['target_visible']),
                        'features':[features[k] for k in schema],
                        'peer_evidence':peers.get((cell,formula),[])})
    payload={'candidates':records,'baseline':selection(base['dev11']['rows'],observed)}
    learned=infer(learner,payload)
    return {**base,'frozen_dev16':{'rows':learned['learned_only']},
            'dev11_plus_frozen_dev16':{'rows':learned['keep_base_plus_learned']},
            'candidate_pool':records,'candidate_probabilities':learned['candidate_probabilities'],
            'formula_count':len(model.formulas),'automatic_edit_applied':False,
            'learned_model_sha256':sha(MODEL),'final_validation_eligible':False}

def predict():
    if RUN.exists():raise SystemExit('Preserve run')
    from run_candidate_learning_dev16 import verify as verify16
    verify16()
    sources=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources+=sorted((ROOT/'baseline/source').rglob('*.py'))
    sources+=[ROOT/'baseline/scripts/predict.py',ROOT/'MULTISOURCE_DEV17_PLAN_20261018.md']
    save(RUN/'source_lock.json',{'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    index=read(DATA/'public_index.json');save(RUN/'public_index.json',index)
    active,accesses=protections()
    learner=joblib.load(MODEL);files={};inputs={str(MODEL.relative_to(ROOT)):sha(MODEL)}
    inputs[str((DATA/'public_index.json').relative_to(ROOT))]=sha(DATA/'public_index.json')
    wall,cpu=time.perf_counter(),time.process_time();timings=[]
    for item in index:
        assert sha(ROOT/item['input'])==item['input_sha256']
        inputs[item['input']]=item['input_sha256']
        t,c=time.perf_counter(),time.process_time()
        pred=prediction(item,learner)
        path=RUN/'predictions'/(item['id']+'.json.gz')
        save(path,pred);files[str(path.relative_to(RUN))]=sha(path)
        timings.append({'id':item['id'],'wall_seconds':time.perf_counter()-t,'cpu_seconds':time.process_time()-c,
                        'formulas':pred['formula_count'],'candidates':len(pred['candidate_pool'])})
        print(item['id'],item['origin'],'pool',len(pred['candidate_pool']),
              {n:len(selection(pred[n]['rows'],pred['observed_formulas'],n=='paper')) for n in NAMES},flush=True)
    active[0]=False
    save(RUN/'runtime.json',{'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
         'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         'scope':'full paper SG/FG, dev11/dev15, peer pool, features and locked learner inference on 30 whole files',
         'gpu_used':False,'model_retrained':False,'cases':timings,'python':platform.python_version()})
    for name in ['runtime.json','public_index.json']:files[name]=sha(RUN/name)
    save(RUN/'prediction_lock.json',{'source_lock_sha256':sha(RUN/'source_lock.json'),'files':files,'inputs':inputs,
        'labels_read':[],'accesses':sorted(accesses),'oracle_guard_exercised':True,'final_validation_eligible':False})
    print('DEV17 PREDICTIONS LOCKED',flush=True)

def verify():
    lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for rel,v in read(RUN/'source_lock.json')['files'].items():assert sha(ROOT/rel)==v,rel
    for rel,v in lock['files'].items():assert sha(RUN/rel)==v,rel
    for rel,v in lock['inputs'].items():assert sha(ROOT/rel)==v,rel
    assert lock['labels_read']==[] and not lock['final_validation_eligible']
    return lock

def totals(rows,name):
    keys=['suggestions','correct','wrong','unknown','errors','correct_errors','unnecessary']
    m={k:sum(r[name][k] for r in rows) for k in keys}
    m['precision_confirmed_lower_bound']=m['correct']/m['suggestions'] if m['suggestions'] else None
    m['coverage']=m['correct_errors']/m['errors'] if m['errors'] else None
    return m

def score():
    verify()
    from product_sum_oracle_dev17 import equivalent,symbolic
    from openpyxl import load_workbook
    truth=read(DATA/'truth.json');index=read(RUN/'public_index.json');cases=[]
    for rel,v in read(DATA/'preparation_lock.json')['files'].items():assert sha(DATA/rel)==v
    for item,t in zip(index,truth['cases']):
        assert item['id']==t['id']
        pred=read(RUN/'predictions'/(item['id']+'.json.gz'))
        w=load_workbook(ROOT/item['input'])
        actual={ws.title+'!'+c.coordinate:c.value for ws in w for row in ws for c in row if c.data_type=='f'}
        assert actual==pred['observed_formulas']==t['observed_formulas']
        errors=set(t['errors']);expected=t['expected_formulas']
        assert errors=={k for k,f in expected.items() if not equivalent(actual[k],f,k.rsplit('!',1)[0],w)}
        row={'id':t['id'],'origin':item['origin'],'source_id':item['source_id'],'scenario':t['scenario']}
        for name in NAMES:
            out=selection(pred[name]['rows'],actual,name=='paper')
            correct=[];wrong=[];unknown=[];unnecessary=[]
            for r in out:
                label=r['cell'];s,a=label.rsplit('!',1)
                if label not in expected:unknown.append(label)
                elif label not in errors:
                    unnecessary.append(label);wrong.append(label)
                elif equivalent(r['suggested_formula'],expected[label],s,w):correct.append(label)
                else:wrong.append(label)
            assert len(out)==len(correct)+len(wrong)+len(unknown)
            m={'suggestions':len(out),'correct':len(correct),'wrong':len(wrong),'unknown':len(unknown),
               'errors':len(errors),'correct_errors':len(correct),'unnecessary':len(unnecessary),
               'correct_cells':correct,'wrong_cells':wrong,'unknown_cells':unknown,'unnecessary_cells':unnecessary}
            m['precision_confirmed_lower_bound']=len(correct)/len(out) if out else None
            m['coverage']=len(correct)/len(errors) if errors else None
            row[name]=m
        coverable=set();by_source=defaultdict(set)
        for c in pred['candidate_pool']:
            label=c['cell'];s,a=label.rsplit('!',1)
            if c['eligible'] and label in errors and equivalent(c['formula'],expected[label],s,w):
                coverable.add(label)
                for source in c['origins']:by_source[source].add(label)
        row['candidate_pool_correct_error_ceiling']=len(coverable)
        row['candidate_pool_missing_error_cells']=sorted(errors-coverable)
        row['candidate_origins_correct_error_ceiling']={k:len(v) for k,v in by_source.items()}
        cases.append(row);w.close()
    report={'cases':cases,'all':{name:totals(cases,name) for name in NAMES},
            'by_origin':{origin:{name:totals([r for r in cases if r['origin']==origin],name) for name in NAMES}
                         for origin in sorted({r['origin'] for r in cases})},
            'candidate_pool_correct_error_ceiling':sum(r['candidate_pool_correct_error_ceiling'] for r in cases),
            'known_errors':sum(len(t['errors']) for t in truth['cases']),
            'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'main_candidate_adopted':False,
            'unknown_suggestions_kept_in_denominator':True,'unnecessary_edits_not_counted_as_correct_repairs':True,
            'final_validation_eligible':False,'accepted_final_sources':0,'accepted_final_families':0,
            'role':'three already-excluded public development origins; frozen learner transfer diagnostic'}
    path=RUN/'score.json';assert not path.exists();save(path,report)
    print(report['all'],flush=True)

def replay():
    verify();active,accesses=protections();learner=joblib.load(MODEL);wall=time.perf_counter();count=0
    for item in read(RUN/'public_index.json'):
        assert prediction(item,learner)==read(RUN/'predictions'/(item['id']+'.json.gz')),item['id']
        count+=1;print('replayed',item['id'],flush=True)
    active[0]=False
    path=ROOT/'qa/MULTISOURCE_DEV17_REPLAY_20261018.json';assert not path.exists()
    save(path,{'cases':count,'full_pipeline_predictions_identical':True,'labels_read':[],
               'wall_seconds':time.perf_counter()-wall,'accesses':sorted(accesses),
               'prediction_lock_sha256':sha(RUN/'prediction_lock.json')})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['predict','score','replay','verify'])
    a=p.parse_args();{'predict':predict,'score':score,'replay':replay,'verify':verify}[a.mode]()
