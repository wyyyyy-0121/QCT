"""Construct and lock candidate features without label access."""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_selector_dev8 import guard_prediction
from formulaguard.workbook import WorkbookModel
from candidate_features_dev16 import Context,VERSION,ORIGINS

DATA=ROOT/'development/candidate_learning_dev16_data_v1'
OLD=ROOT/'development/selector_dev12_reconciliation_v1'
NINE=ROOT/'development/selector_dev9_peer_scalar_v1'
NOTE=ROOT/'development/annotation_dev15_v1'

def uid(case,cell,formula):
    return hashlib.sha256(json.dumps([case,cell,formula],ensure_ascii=False).encode()).hexdigest()

def items():
    index=[]
    for item in read(OLD/'public_index.json'):
        g,i=item['group'],item['id']
        p12=OLD/'predictions'/g/(i+'.json.gz')
        upstream={'dev12_pack':str(p12.relative_to(ROOT))}
        p9=NINE/'predictions'/g/(i+'.json.gz')
        if p9.exists():upstream['dev9']=str(p9.relative_to(ROOT))
        if g=='regression':paper=ROOT/'baseline/predictions'/i/'full.json.gz'
        elif g=='stress':paper=ROOT/'development/semantic_stress_dev1/predictions'/(i+'.json')
        elif g=='tradeoff':paper=ROOT/'development/policy_tradeoff_dev1/predictions'/(i+'.json')
        elif g in ['crossdomain','adversarial']:paper=ROOT/item['upstream']
        else:paper=None
        if paper:upstream['paper_pack']=str(paper.relative_to(ROOT))
        index.append({'case':g+'/'+i,'id':i,'group':g,'input':item['input'],
                      'input_sha256':item['input_sha256'],'parallel_sheets':item['parallel_sheets'],
                      'upstream':upstream,'origin_group':'authored_development'})
    for item in read(NOTE/'public_index.json'):
        index.append({'case':'lcoe/'+item['id'],'id':item['id'],'group':'lcoe','input':item['input'],
                      'input_sha256':item['input_sha256'],'parallel_sheets':[],
                      'upstream':{'note_pack':str((NOTE/'predictions'/(item['id']+'.json.gz')).relative_to(ROOT))},
                      'origin_group':'uk_government'})
    assert len(index)==183
    return index

def upstream(item):
    if item['group']=='lcoe':
        p=read(ROOT/item['upstream']['note_pack'])
        return {'paper':p['paper'],'dev11':p['dev11'],'dev15':p['note_only']},p['observed_formulas']
    p=read(ROOT/item['upstream']['dev12_pack'])
    result={'dev11':p['dev11'],'dev12':p['dev12']}
    if p['paper'] is not None:result['paper']=p['paper']
    else:
        raw=read(ROOT/item['upstream']['paper_pack'])
        result['paper']=raw if item['group']=='regression' else raw['paper']
    if 'dev9' in item['upstream']:result['dev9']=read(ROOT/item['upstream']['dev9'])
    return result,p['observed_formulas']

def build():
    if DATA.exists():raise SystemExit('Preserve feature dataset')
    # Existing lock verification may hash source code, but not derive features.
    from run_selector_dev12 import verify as verify12
    from run_annotation_dev15 import verify as verify15
    from run_selector_dev9 import verify_inputs as verify9
    verify12();verify15();verify9(read(NINE/'prediction_lock.json'))
    index=items();save(DATA/'public_index.json',index)
    input_hashes={}; files={}; records=[]; names=None
    accesses,active=set(),[True];guard_prediction(accesses,active)
    def forbid_author(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)):
            name=str(args[0])
            if 'prepare_candidate_learning_dev16' in name or '/heldout_truth' in name or '/training_labels/' in name:
                raise PermissionError('Feature extraction may not read labels/oracle')
    sys.addaudithook(forbid_author)
    wall,cpu=time.perf_counter(),time.process_time()
    for item in index:
        path=ROOT/item['input'];assert sha(path)==item['input_sha256']
        input_hashes[item['input']]=sha(path)
        for rel in item['upstream'].values():input_hashes[rel]=sha(ROOT/rel)
        models,observed=upstream(item)
        model=WorkbookModel.from_xlsx(path)
        assert {s+'!'+a:v for (s,a),v in model.formulas.items()}==observed
        context=Context(model,item['parallel_sheets'])
        base={r['cell']:r for r in models['dev11']['rows']}
        pool=defaultdict(set)
        for name,pred in models.items():
            for row in pred['rows']:
                cell=row['cell'];f=row.get('suggested_formula')
                if f and f!=observed[cell] and (name=='paper' or row.get('status')=='propose'):
                    pool[cell,f].add(name)
        candidates=[]
        for (cell,formula),origins in sorted(pool.items()):
            s,a=cell.rsplit('!',1)
            f=context.features(s,a,formula,origins,base[cell])
            if names is None:names=sorted(f)
            assert sorted(f)==names
            candidates.append({'id':uid(item['case'],cell,formula),'cell':cell,'formula':formula,
                               'origins':sorted(origins),'eligible':bool(f['complete_ast_pair']),
                               'features':[f[n] for n in names]})
        payload={'case':item['case'],'candidates':candidates,
                 'baseline':[{'cell':r['cell'],'suggested_formula':r['suggested_formula'],'status':'propose'}
                             for r in models['dev11']['rows'] if r.get('status')=='propose'
                             and r.get('suggested_formula') and r['suggested_formula']!=observed[r['cell']]],
                 'formula_count':len(observed)}
        path=DATA/'features'/(item['case'].replace('/','__')+'.json.gz')
        save(path,payload);files[str(path.relative_to(DATA))]=sha(path)
        records.append({'case':item['case'],'candidate_count':len(candidates),
                        'complete_ast_candidates':sum(c['eligible'] for c in candidates)})
        print(item['case'],len(candidates),flush=True)
    active[0]=False
    save(DATA/'feature_schema.json',{'names':names,'version':VERSION,'feature_count':len(names),
                                    'excluded_identity_features':True,'labels_read':[]})
    save(DATA/'feature_runtime.json',{'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
         'cases':records,'scope':'feature extraction from frozen candidates, original SG/FG costs excluded',
         'labels_read':[],'accesses':sorted(accesses)})
    for name in ['public_index.json','feature_schema.json','feature_runtime.json']:files[name]=sha(DATA/name)
    sources=[Path(__file__),ROOT/'scripts/candidate_features_dev16.py',ROOT/'CANDIDATE_LEARNING_DEV16_PLAN_20261018.md']
    sources+=sorted((ROOT/'tests').glob('test_candidate*dev16.py'))
    save(DATA/'feature_lock.json',{'files':files,'inputs':input_hashes,
          'sources':{str(p.relative_to(ROOT)):sha(p) for p in sources},
          'labels_read':[],'final_validation_eligible':False})
    print('FEATURES LOCKED',len(index),sum(x['candidate_count'] for x in records),flush=True)
if __name__=='__main__':build()
