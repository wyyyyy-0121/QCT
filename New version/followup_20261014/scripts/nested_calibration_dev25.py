"""One-dimensional calibration of repair success on genuinely heldout origins."""
from collections import defaultdict
import numpy as np
from sklearn.isotonic import IsotonicRegression
from candidate_features_dev16 import MARGIN,THRESHOLD
from run_candidate_learning_dev18 import weights


def validate_folds(index):
    from itertools import combinations
    groups=index['case_groups'];origins=set(index['origins']);cases=set(groups)
    assert len(origins)==5 and {v['origin_group'] for v in groups.values()}==origins
    pairs=index['pairs'];outer=index['outer']
    assert len(pairs)==10 and len({p['id'] for p in pairs})==10
    assert {tuple(sorted(p['excluded_origins'])) for p in pairs}==set(combinations(sorted(origins),2))
    for p in pairs:
        excluded=set(p['excluded_origins']);assert len(excluded)==2
        train={c for c in cases if groups[c]['origin_group'] not in excluded}
        assert set(p['train_cases'])==train and set(p['test_cases'])==cases-train
        assert len(p['train_cases'])+len(p['test_cases'])==len(cases)
    assert len(outer)==5 and {f['origin'] for f in outer}==origins
    for f in outer:
        test={c for c in cases if groups[c]['origin_group']==f['origin']}
        assert set(f['test_cases'])==test and set(f['train_cases'])==cases-test
        assert len(f['test_cases'])+len(f['train_cases'])==len(cases)
        expected={p['id'] for p in pairs if f['origin'] in p['excluded_origins']}
        assert len(f['inner_pairs'])==4 and set(f['inner_pairs'])==expected


def top_rows(payload,scores,x,unit_names):
    if len(scores)!=len(payload['candidates']) or len(x)!=len(scores):raise ValueError('candidate order/length')
    groups=defaultdict(list)
    for n,(row,p) in enumerate(zip(payload['candidates'],scores)):
        if not np.isfinite(p):raise ValueError('nonfinite raw score')
        if row['eligible']:groups[row['cell']].append((n,row,float(p)))
    selected=[];unit_column=x.shape[1]-len(unit_names)+unit_names.index('unit_new_incompatible')
    for cell,values in sorted(groups.items()):
        values.sort(key=lambda r:(-r[2],r[1]['formula']))
        n,best,p=values[0];runner=values[1][2] if len(values)>1 else 0.
        reason='raw_margin' if p-runner<MARGIN else ('unit_incompatible' if x[n,unit_column] else None)
        selected.append(dict(cell=cell,candidate_id=best['id'],suggested_formula=best['formula'],
            raw_probability=p,raw_runner_up_probability=runner,gate_reason=reason))
    return selected


def fit_calibrator(rows):
    if any(r['label'] not in (0,1) for r in rows):raise ValueError('known repair-success labels required')
    if len({r['label'] for r in rows})<2 or len({r['source'] for r in rows})<2:
        return None,dict(status='insufficient_labels_or_origins',rows=len(rows),positive=sum(r['label'] for r in rows),negative=sum(r['label']==0 for r in rows))
    w=weights(rows);scores=np.asarray([r['raw_probability'] for r in rows],dtype=np.float64)
    labels=np.asarray([r['label'] for r in rows],dtype=np.int8)
    if not np.isfinite(scores).all():raise ValueError('nonfinite calibration input')
    model=IsotonicRegression(increasing=True,y_min=0,y_max=1,out_of_bounds='nan')
    model.fit(scores,labels,sample_weight=w)
    sources={s:float(w[[n for n,r in enumerate(rows) if r['source']==s]].sum()) for s in sorted({r['source'] for r in rows})}
    assert max(sources.values())-min(sources.values())<1e-6
    return model,dict(status='fitted',rows=len(rows),positive=int(labels.sum()),negative=int((labels==0).sum()),
        source_weight_sums=sources,class_weight_sums=[float(w[labels==v].sum()) for v in [0,1]],
        x_thresholds=model.X_thresholds_.tolist(),y_thresholds=model.y_thresholds_.tolist())


def select(top,calibrator):
    if not top:return [],[]
    values=calibrator.predict([r['raw_probability'] for r in top]) if calibrator is not None else np.full(len(top),np.nan)
    diagnostics=[];selected=[]
    for row,p in zip(top,values):
        reason=row['gate_reason']
        if reason is None:
            reason='calibration_unavailable' if not np.isfinite(p) else ('calibrated_threshold' if p<THRESHOLD else None)
        value=float(p) if np.isfinite(p) else None
        diagnostics.append(dict(row,calibrated_probability=value,rejection_reason=reason))
        if reason is None:
            selected.append(dict(cell=row['cell'],candidate_id=row['candidate_id'],suggested_formula=row['suggested_formula'],
                probability=value,raw_probability=row['raw_probability'],raw_runner_up_probability=row['raw_runner_up_probability'],status='propose'))
    return selected,diagnostics
