import sys
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
ROOT=Path('/home/ayaka/hybridguard/New version/followup_20261014')
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from build_unit_features_dev20 import BASE,DATA,load,verify
from build_candidates_dev18 import protection
from run_selector_dev5 import read,save,sha
verify();active,accesses=protection();names=read(DATA/'feature_schema.json')['names'];counts=defaultdict(Counter)
for item in read(BASE/'public_index.json'):
    payload=read(BASE/'features'/(item['case'].replace('/','__')+'.json.gz'));x=load(item,payload)
    for prefix in ['unit_old_','unit_new_']:
        columns=[names.index(prefix+s) for s in ['compatible','incompatible','unknown']]
        assert np.isin(x[:,columns],[0,1]).all()
        assert (x[:,columns].sum(axis=1)==1).all()
    for s in ['compatible','incompatible','unknown']:
        assert np.array_equal(x[:,names.index('unit_delta_'+s)],x[:,names.index('unit_new_'+s)]-x[:,names.index('unit_old_'+s)])
        counts[item['origin_group']]['candidate_'+s]+=int(x[:,names.index('unit_new_'+s)].sum())
    counts[item['origin_group']]['cases']+=1
    counts[item['origin_group']]['candidates']+=len(x)
active[0]=False
p=ROOT/'qa/UNIT_FEATURE_AVAILABILITY_DEV20_20261018.json';assert not p.exists()
save(p,{'origin_group':dict(counts),'labels_read':[],'accesses':sorted(accesses),
        'one_hot_and_delta_checks_all_passed':True,'feature_lock_sha256':sha(DATA/'feature_lock.json'),
        'audit_source_sha256':sha(Path(__file__)),'repair_metrics':None})
print(dict(counts))
