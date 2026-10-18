"""Build only new role features; immutable dev18 owns candidates and labels."""
from pathlib import Path
import hashlib
import sys
import time
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from build_candidates_dev18 import DATA as BASE,protection
from run_selector_dev5 import read,save,sha
from run_candidate_learning_dev18 import verify as verify18
from signed_roles_dev19 import RoleContext
from formulaguard.workbook import WorkbookModel

DATA=ROOT/'development/signed_features_dev19_v1'

def order_digest(candidates):
    return hashlib.sha256('\n'.join(c['id'] for c in candidates).encode()).hexdigest()

def matrix(item,names=None):
    payload=read(BASE/'features'/(item['case'].replace('/','__')+'.json.gz'))
    model=WorkbookModel.from_xlsx(ROOT/item['input']);context=RoleContext(model)
    sheet,address=next(iter(model.formulas));f=model.formulas[sheet,address]
    schema=sorted(context.features(sheet,address,f,f))
    if names is not None:assert names==schema
    x=np.empty((len(payload['candidates']),len(schema)),dtype=np.float32)
    for n,c in enumerate(payload['candidates']):
        s,a=c['cell'].rsplit('!',1);features=context.features(s,a,model.formulas[s,a],c['formula'])
        assert sorted(features)==schema
        x[n]=[features[k] for k in schema]
    assert np.isfinite(x).all()
    return x,schema,order_digest(payload['candidates'])

def load(item,payload):
    p=DATA/'features'/(item['case'].replace('/','__')+'.npz')
    with np.load(p,allow_pickle=False) as data:
        assert str(data['order_digest'])==order_digest(payload['candidates']),'candidate order mismatch'
        x=data['x']
    assert x.shape==(len(payload['candidates']),len(read(DATA/'feature_schema.json')['names']))
    assert x.dtype==np.float32 and np.isfinite(x).all()
    return x

def verify():
    verify18();lock=read(DATA/'feature_lock.json')
    for rel,v in lock['files'].items():assert sha(DATA/rel)==v,rel
    for rel,v in lock['sources'].items():assert sha(ROOT/rel)==v,rel
    assert sha(BASE/'feature_lock.json')==lock['base_feature_lock_sha256']
    assert lock['labels_read']==[]

def build():
    if DATA.exists():raise SystemExit('Preserve signed features')
    verify18();active,accesses=protection();files={};cases=[];names=None;wall,cpu=time.perf_counter(),time.process_time()
    for item in read(BASE/'public_index.json'):
        assert sha(ROOT/item['input'])==item['input_sha256']
        x,schema,digest=matrix(item,names)
        if names is None:names=schema
        path=DATA/'features'/(item['case'].replace('/','__')+'.npz');path.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(path,x=x,order_digest=np.asarray(digest))
        files[str(path.relative_to(DATA))]=sha(path);cases.append({'case':item['case'],'rows':len(x)})
        print('roles locked',item['case'],len(x),flush=True)
    active[0]=False
    save(DATA/'feature_schema.json',{'names':names,'feature_count':len(names),'dtype':'float32'})
    save(DATA/'runtime.json',{'cases':cases,'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
         'scope':'role features only; base candidates/upstream costs excluded','gpu_used':False})
    for n in ['feature_schema.json','runtime.json']:files[n]=sha(DATA/n)
    sources=[Path(__file__),ROOT/'scripts/signed_roles_dev19.py',ROOT/'SIGNED_LEARNING_DEV19_PLAN_20261018.md']
    sources+=sorted((ROOT/'tests').glob('*dev19*.py'))
    save(DATA/'feature_lock.json',{'files':files,'sources':{str(p.relative_to(ROOT)):sha(p) for p in sources},
         'base_feature_lock_sha256':sha(BASE/'feature_lock.json'),'labels_read':[],'accesses':sorted(accesses),
         'final_validation_eligible':False})
    print('DEV19 ROLE FEATURES LOCKED',len(cases),len(names),flush=True)

if __name__=='__main__':build()
