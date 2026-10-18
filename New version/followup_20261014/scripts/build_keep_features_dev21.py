"""Label-free observed-formula comparator vectors on frozen dev20 feature schema."""
from pathlib import Path
import sys
import time
import hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_unit_learning_dev20 import verify as verify20,case_data as candidate_data
from build_candidates_dev18 import DATA as BASE,protection,upstream_data
from build_signed_features_dev19 import order_digest
from candidate_features_dev16 import Context
from candidate_expansion_dev18 import extra_features
from signed_roles_dev19 import RoleContext
from unit_features_dev20 import VisibleUnits
from formulaguard.workbook import WorkbookModel
DATA=ROOT/'development/keep_features_dev21_v1'

def case_path(case):return case.replace('/','__')
def digest_cells(cells):return hashlib.sha256('\n'.join(cells).encode()).hexdigest()
def names():
    return (read(BASE/'feature_schema.json')['names']+
            read(ROOT/'development/signed_features_dev19_v1/feature_schema.json')['names']+
            read(ROOT/'development/unit_features_dev20_v1/feature_schema.json')['names'])

def matrix(item):
    payload=read(BASE/'features'/(case_path(item['case'])+'.json.gz'))
    model=WorkbookModel.from_xlsx(ROOT/item['input'])
    _,base_rows,observed=upstream_data(item);prior={r['cell']:r for r in base_rows}
    context=Context(model,item['parallel_sheets']);roles=RoleContext(model);units=VisibleUnits(model)
    cells=sorted({r['cell'] for r in payload['candidates']});schema=names()
    k=np.empty((len(cells),len(schema)),dtype=np.float32)
    for n,cell in enumerate(cells):
        s,a=cell.rsplit('!',1);f=model.formulas[s,a];assert observed[cell]==f
        values={**context.features(s,a,f,set(),prior[cell]),**extra_features(model,s,a,f,f,set()),
                **roles.features(s,a,f,f),**units.features(s,a,f,f)}
        assert set(values)==set(schema)
        k[n]=[values[key] for key in schema]
    assert np.isfinite(k).all()
    return payload,cells,k

def load(item,payload):
    p=DATA/'features'/(case_path(item['case'])+'.npz')
    cells=sorted({r['cell'] for r in payload['candidates']})
    with np.load(p,allow_pickle=False) as data:
        assert str(data['order_digest'])==order_digest(payload['candidates']),'candidate order mismatch'
        assert str(data['cell_digest'])==digest_cells(cells),'target order mismatch'
        k=data['k']
    assert k.shape==(len(cells),len(names())) and k.dtype==np.float32 and np.isfinite(k).all()
    return cells,k

def case_data(item):
    payload,x=candidate_data(item);cells,k=load(item,payload);index={cell:n for n,cell in enumerate(cells)}
    row_index=np.asarray([index[c['cell']] for c in payload['candidates']],dtype=np.int64)
    return payload,x,k,row_index

def verify():
    verify20();lock=read(DATA/'feature_lock.json')
    for rel,v in lock['files'].items():assert sha(DATA/rel)==v,rel
    for rel,v in lock['sources'].items():assert sha(ROOT/rel)==v,rel
    assert sha(ROOT/'development/unit_learning_dev20_v1/prediction_lock.json')==lock['control_prediction_lock_sha256']
    assert lock['labels_read']==[]

def build():
    if DATA.exists():raise SystemExit('Preserve comparator features')
    verify20();active,accesses=protection();files={};cases=[];wall,cpu=time.perf_counter(),time.process_time()
    for item in read(BASE/'public_index.json'):
        assert sha(ROOT/item['input'])==item['input_sha256']
        payload,cells,k=matrix(item);p=DATA/'features'/(case_path(item['case'])+'.npz');p.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(p,k=k,order_digest=np.asarray(order_digest(payload['candidates'])),cell_digest=np.asarray(digest_cells(cells)))
        files[str(p.relative_to(DATA))]=sha(p);cases.append({'case':item['case'],'targets':len(cells),'candidates':len(payload['candidates'])})
        print('keep comparator',item['case'],len(cells),flush=True)
    active[0]=False
    save(DATA/'feature_schema.json',{'base_names':names(),'comparison_names':['context_'+n for n in names()]+['difference_'+n for n in names()],
                                   'base_width':len(names()),'comparison_width':2*len(names()),'dtype':'float32'})
    save(DATA/'runtime.json',{'cases':cases,'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
                            'scope':'observed comparator features only; existing candidate/upstream costs excluded','gpu_used':False})
    for n in ['feature_schema.json','runtime.json']:files[n]=sha(DATA/n)
    sources=[Path(__file__),ROOT/'RELATIVE_LEARNING_DEV21_PLAN_20261018.md']+sorted((ROOT/'tests').glob('*dev21.py'))
    save(DATA/'feature_lock.json',{'files':files,'sources':{str(p.relative_to(ROOT)):sha(p) for p in sources},
         'control_prediction_lock_sha256':sha(ROOT/'development/unit_learning_dev20_v1/prediction_lock.json'),
         'labels_read':[],'accesses':sorted(accesses),'final_validation_eligible':False})
    print('DEV21 COMPARATOR FEATURES LOCKED',flush=True)
if __name__=='__main__':build()
