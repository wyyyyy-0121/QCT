"""Fixed learner, grouped weights and deterministic single-cell candidate choice."""
from collections import Counter,defaultdict
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from candidate_features_dev16 import PARAMETERS,choose

def fit(features,labels):
    assert labels and len({r['id'] for r in labels})==len(labels)
    cases=Counter(r['case'] for r in labels)
    families=defaultdict(set)
    for r in labels:families[r['family']].add(r['case'])
    x=np.asarray([features[r['id']]['features'] for r in labels],dtype=np.float64)
    y=np.asarray([r['label'] for r in labels],dtype=np.int8)
    weights=np.asarray([1/(len(families[r['family']])*cases[r['case']]) for r in labels],dtype=np.float64)
    weights*=len(weights)/weights.sum()
    if len(set(y))<2:raise ValueError('training requires both correctness classes')
    learner=HistGradientBoostingClassifier(**PARAMETERS)
    learner.fit(x,y,sample_weight=weights)
    return learner,{'rows':len(y),'positive':int(y.sum()),'negative':int((y==0).sum()),
                    'cases_with_candidates':len(cases),'families':len(families),
                    'sample_weight_sum':float(weights.sum()),'max_weight':float(weights.max())}

def infer(model,payload):
    candidates=payload['candidates']
    if not candidates:return {'candidate_probabilities':{},'learned_only':[],'keep_base_plus_learned':payload['baseline']}
    x=np.asarray([r['features'] for r in candidates],dtype=np.float64)
    p=model.predict_proba(x)[:,list(model.classes_).index(1)]
    by_cell=defaultdict(list)
    for r,prob in zip(candidates,p):by_cell[r['cell']].append((r,float(prob)))
    selected=[]
    for cell,rows in sorted(by_cell.items()):
        found=choose([r for r,prob in rows],[prob for r,prob in rows])
        if found:selected.append(found)
    old={r['cell']:r for r in payload['baseline']}
    added=[r for r in selected if r['cell'] not in old]
    return {'candidate_probabilities':{r['id']:float(prob) for r,prob in zip(candidates,p)},
            'learned_only':selected,'keep_base_plus_learned':payload['baseline']+added}
