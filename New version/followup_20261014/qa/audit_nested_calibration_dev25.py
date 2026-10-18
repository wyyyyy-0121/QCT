"""Independent OOF selection, old repair labels, weights and weighted PAVA."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
import joblib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src'),str(ROOT/'qa')]
from run_selector_dev5 import read,save,sha
from run_nested_calibration_dev25 import RUN,INNER,OUTER,LABELS,BASE,verify,case_path,case_data
from audit_absolute_training_dev24 import digest


def pava(scores,labels,weights):
    values=defaultdict(lambda:[0.,0.])
    for score,label,weight in zip(scores,labels,weights):
        values[score][0]+=weight;values[score][1]+=label*weight
    xs=sorted(values);blocks=[]
    for n,x in enumerate(xs):
        w,y=values[x];blocks.append([n,n,w,y])
        while len(blocks)>1 and blocks[-2][3]/blocks[-2][2]>blocks[-1][3]/blocks[-1][2]:
            right=blocks.pop();left=blocks.pop()
            blocks.append([left[0],right[1],left[2]+right[2],left[3]+right[3]])
    ys=np.empty(len(xs))
    for start,end,w,y in blocks:ys[start:end+1]=y/w
    return np.asarray(xs),ys


def independent_weights(rows):
    cases=Counter(r['case'] for r in rows);families=defaultdict(set);sources=defaultdict(set)
    for r in rows:
        families[r['source'],r['family']].add(r['case']);sources[r['source']].add(r['family'])
    result=np.asarray([1/(len(sources[r['source']])*len(families[r['source'],r['family']])*cases[r['case']]) for r in rows])
    return result*len(result)/result.sum()


def independent_top(payload,x,scores,unit_names):
    groups=defaultdict(list)
    for n,c in enumerate(payload['candidates']):
        if c['eligible']:groups[c['cell']].append((n,c))
    top=[]
    for cell,values in sorted(groups.items()):
        values.sort(key=lambda pair:(-float(scores[pair[0]]),pair[1]['formula']))
        n,c=values[0];p=float(scores[n]);runner=float(scores[values[1][0]]) if len(values)>1 else 0.
        reason='raw_margin' if p-runner<.05 else ('unit_incompatible' if x[n,x.shape[1]-len(unit_names)+unit_names.index('unit_new_incompatible')] else None)
        top.append(dict(cell=cell,candidate_id=c['id'],suggested_formula=c['formula'],raw_probability=p,raw_runner_up_probability=runner,gate_reason=reason))
    return top


def main():
    verify();index=read(LABELS/'fold_index.json');pairs={p['id']:p for p in index['pairs']}
    public={r['case']:r for r in read(BASE/'public_index.json')}
    truth=read(BASE/'heldout_truth.json.gz')['cases']
    unit_names=read(ROOT/'development/unit_features_dev20_v1/feature_schema.json')['names']
    runtime={r['fold']:r for r in read(OUTER/'runtime.json')['folds']};results=[]
    # Cache each independent (pair, case) top list; four OOF appearances per
    # case are genuinely different trained models, never collapsed together.
    cache={}
    for pair in index['pairs']:
        for case in pair['test_cases']:
            payload,x,k,positions=case_data(public[case]);labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            with np.load(INNER/'probabilities'/pair['id']/(case_path(case)+'.npz'),allow_pickle=False) as saved:scores=saved['probabilities']
            top=independent_top(payload,x,scores,unit_names)
            assert top==read(INNER/'top'/pair['id']/(case_path(case)+'.json.gz'))['rows']
            # Explicitly check known clean-cell labels are unsuccessful repair,
            # even if a formula relation might be numerically equivalent.
            for c in payload['candidates']:
                if c['cell'] in truth[case]['expected_formulas'] and c['cell'] not in truth[case]['errors']:assert labels[c['id']]==0
            cache[pair['id'],case]=(top,{r['candidate_id']:labels[r['candidate_id']] for r in top})
        print('independent nested tops',pair['id'],flush=True)
    for outer in index['outer']:
        selected=[];counts=Counter();seen=[]
        for pair_id in outer['inner_pairs']:
            pair=pairs[pair_id];excluded=set(pair['excluded_origins'])
            assert outer['origin'] in excluded
            for case in pair['test_cases']:
                meta=index['case_groups'][case]
                if meta['origin_group']==outer['origin']:continue
                assert meta['origin_group'] in excluded and case in outer['train_cases'] and case not in pair['train_cases']
                seen.append(case);tops,labels=cache[pair_id,case]
                for r in tops:
                    counts['top_candidates']+=1
                    if r['gate_reason'] is not None:counts[r['gate_reason']]+=1;continue
                    y=labels[r['candidate_id']]
                    if y is None:counts['unknown_excluded']+=1;continue
                    selected.append(dict(r,case=case,label=y,source=meta['origin_group'],family=meta['family']));counts['known']+=1
        assert set(seen)==set(outer['train_cases']) and len(seen)==len(set(seen))
        old=runtime[outer['id']];assert dict(counts)==old['counts']
        assert digest(selected,['case','cell','candidate_id','raw_probability','label'])==old['selection_sha256']
        assert len(selected)==old['rows'] and sum(r['label'] for r in selected)==old['positive']
        model=joblib.load(OUTER/'calibrators'/(outer['id']+'.joblib.gz'))
        if len({r['label'] for r in selected})<2 or len({r['source'] for r in selected})<2:
            assert model is None and old['status']=='insufficient_labels_or_origins';error=None;xs=ys=None
        else:
            assert old['status']=='fitted';w=independent_weights(selected)
            scores=[r['raw_probability'] for r in selected];labels=[r['label'] for r in selected]
            xs,ys=pava(scores,labels,w);actual=model.predict(xs)
            error=float(np.max(np.abs(actual-ys)));assert error<1e-10,(outer['id'],error)
            assert np.all(np.diff(ys)>=-1e-12)
            assert np.isnan(model.predict([np.nextafter(xs[0],-np.inf),np.nextafter(xs[-1],np.inf)])).all()
            for source,value in old['source_weight_sums'].items():
                measured=float(w[[n for n,r in enumerate(selected) if r['source']==source]].sum());assert abs(measured-value)<1e-5
            for v in [0,1]:assert abs(float(w[np.asarray(labels)==v].sum())-old['class_weight_sums'][v])<1e-5
        outer_top_count=0
        for case in outer['test_cases']:
            payload,x,k,positions=case_data(public[case])
            with np.load(OUTER/'probabilities'/outer['id']/(case_path(case)+'.npz'),allow_pickle=False) as saved:scores=saved['probabilities']
            top=independent_top(payload,x,scores,unit_names)
            saved=read(OUTER/'top'/outer['id']/(case_path(case)+'.json.gz'))['rows'];assert len(top)==len(saved)
            selected_cells=[]
            for r,actual in zip(top,saved):
                for key,value in r.items():assert actual[key]==value,(case,key)
                p=np.nan if xs is None else float(np.interp(r['raw_probability'],xs,ys,left=np.nan,right=np.nan))
                score=actual['calibrated_probability']
                if np.isfinite(p):assert score is not None and abs(score-p)<1e-10
                else:assert score is None
                # Audit exact threshold decisions on saved float64 scores;
                # the independent PAVA above checks those scores numerically.
                reason=r['gate_reason']
                if reason is None:reason='calibration_unavailable' if score is None else ('calibrated_threshold' if score<.90 else None)
                assert actual['rejection_reason']==reason
                if reason is None:selected_cells.append(r['cell'])
                outer_top_count+=1
            pred=read(OUTER/'predictions'/outer['id']/(case_path(case)+'.json.gz'))
            assert selected_cells==[r['cell'] for r in pred['calibrated_only']]
        results.append(dict(fold=outer['id'],counts=dict(counts),rows=len(selected),pava_maximum_error=error,
            independently_checked_outer_tops=outer_top_count,all_original_clean_labels_zero=True))
        print('independent isotonic and repair labels verified',outer['id'],len(selected),error,flush=True)
    target=ROOT/'qa/NESTED_CALIBRATION_DEV25_CALIBRATION_AUDIT_20261018.json';assert not target.exists()
    save(target,dict(folds=results,all_nested_top_rows_reconstructed=True,all_training_only_repair_labels_verified=True,
        independent_pava_matches=True,prediction_lock_sha256=sha(OUTER/'prediction_lock.json'),auditor_sha256=sha(Path(__file__)),final_validation_eligible=False))


if __name__=='__main__':main()
