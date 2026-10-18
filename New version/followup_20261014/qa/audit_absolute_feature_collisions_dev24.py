"""Post-lock feature identifiability audit; not a repair-accuracy bound."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_absolute_selection_dev24 import RUN,BASE,LABELS,verify,case_path,case_data


def main():
    verify();assert (RUN/'score.json').exists()
    buckets={};examples={};source_buckets=defaultdict(dict);option_count=Counter()
    for item in read(BASE/'public_index.json'):
        case=item['case'];payload,x,k,positions=case_data(item)
        lookup={c['id']:n for n,c in enumerate(payload['candidates'])}
        cells={c['cell']:positions[n] for n,c in enumerate(payload['candidates'])}
        states=read(LABELS/'author_case_options'/(case_path(case)+'.json.gz'))['alternatives']
        for row in states:
            if row['label'] is None:continue
            values=k[cells[row['cell']]] if row['kind']=='keep' else x[lookup[row['id']]]
            # Float32 -0 and +0 are indistinguishable to this model.
            values=np.where(values==0,np.float32(0),values).astype('<f4',copy=False)
            key=hashlib.sha256(values.tobytes()).digest();y=row['label'];source=row['source']
            if key not in buckets:buckets[key]=[0,0]
            buckets[key][y]+=1;option_count[source]+=1
            local=source_buckets[source].setdefault(key,[0,0]);local[y]+=1
            if (key,y) not in examples:examples[key,y]={a:row[a] for a in ['case','cell','id','kind','label','source']}
    def summarize(groups):
        conflicts=[v for v in groups.values() if v[0] and v[1]]
        return dict(options=sum(sum(v) for v in groups.values()),unique_vectors=len(groups),
            contradictory_vectors=len(conflicts),options_in_contradictory_vectors=sum(sum(v) for v in conflicts),
            minimum_option_classification_errors=sum(min(v) for v in groups.values()))
    summary=summarize(buckets);assert summary['options']==813899
    examples_out=[]
    for key,counts in sorted(buckets.items(),key=lambda kv:(-min(kv[1]),kv[0])):
        if all(counts):examples_out.append(dict(feature_sha256=key.hex(),counts=counts,negative=examples[key,0],positive=examples[key,1]))
        if len(examples_out)==50:break
    target=ROOT/'qa/ABSOLUTE_SELECTION_DEV24_FEATURE_COLLISIONS_20261018.json';assert not target.exists()
    save(target,dict(all=summary,by_source={s:summarize(v) for s,v in source_buckets.items()},examples=examples_out,
        scope='exact pointwise 356-dimensional feature identity on selected certified development options; no repair-performance bound',
        minimum_error_scope='unweighted option classification on this revealed finite pool only',
        heldout_labels_used_for_model=False,prediction_lock_sha256=sha(RUN/'prediction_lock.json'),
        auditor_sha256=sha(Path(__file__)),final_validation_eligible=False))
    print('DEV24 FEATURE COLLISIONS',summary,flush=True)


if __name__=='__main__':main()
