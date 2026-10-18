"""Relative preferences with mirrored directions; not calibrated repair certainty."""
from collections import defaultdict
import numpy as np
from candidate_features_dev16 import PARAMETERS,THRESHOLD,MARGIN,choose
MAX_NEGATIVES_PER_CELL=32

def selected_rows(rows):
    groups=defaultdict(list)
    for r in rows:
        assert r['label'] in [0,1]
        groups[r['case'],r['cell']].append(r)
    result=[]
    for key,values in sorted(groups.items()):
        positive=sorted([r for r in values if r['label']==1],key=lambda r:r['id'])
        negative=sorted([r for r in values if r['label']==0],key=lambda r:r['id'])[:MAX_NEGATIVES_PER_CELL]
        result.extend(positive+negative)
    return result

def representation(candidate,keep,reverse=False):
    assert candidate.shape==keep.shape and candidate.ndim==2
    delta=keep-candidate if reverse else candidate-keep
    return np.concatenate([keep,delta],axis=1)

def preference(model,candidate,keep):
    if not len(candidate):return np.empty(0,dtype=np.float64)
    column=list(model.classes_).index(1)
    forward=model.predict_proba(representation(candidate,keep))[:,column]
    reverse=model.predict_proba(representation(candidate,keep,reverse=True))[:,column]
    return (1.+(forward-reverse))/2.

def infer(model,payload,x,k,positions,unit_names):
    from run_unit_learning_dev20 import unit_filter
    candidates=payload['candidates'];probs=preference(model,x,k[positions]);groups=defaultdict(list)
    for c,p in zip(candidates,probs):groups[c['cell']].append((c,float(p)))
    raw=[]
    for cell,rows in sorted(groups.items()):
        r=choose([c for c,p in rows],[p for c,p in rows])
        if r:raw.append(r)
    selected=unit_filter(raw,candidates,x[:,-len(unit_names):],unit_names)
    old={r['cell'] for r in payload['baseline']}
    return probs,{'dev11':payload['baseline'],'learned_only':selected,'learned_unfiltered':raw,
                  'keep_base_plus_learned':payload['baseline']+[r for r in selected if r['cell'] not in old]}
