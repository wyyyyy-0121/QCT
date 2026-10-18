"""Post-score candidate availability and rejection diagnostic; predictions untouched."""
from pathlib import Path
from collections import defaultdict
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_multisource_dev17 import RUN,DATA,verify
from run_selector_dev5 import read,save,sha
from product_sum_oracle_dev17 import equivalent
from openpyxl import load_workbook

def main():
    verify();truth=read(DATA/'truth.json')
    report=[];total=defaultdict(int)
    for item,t in zip(read(RUN/'public_index.json'),truth['cases']):
        w=load_workbook(ROOT/item['input']);pred=read(RUN/'predictions'/(item['id']+'.json.gz'))
        errors=set(t['errors']);choices=defaultdict(list);correct_candidates=defaultdict(list)
        for c in pred['candidate_pool']:
            if c['cell'] not in errors:continue
            choices[c['cell']].append(c)
            s,a=c['cell'].rsplit('!',1)
            if equivalent(c['formula'],t['expected_formulas'][c['cell']],s,w):
                correct_candidates[c['cell']].append(c)
        rows=[]
        for label in sorted(errors):
            valid=[c for c in correct_candidates[label] if c['eligible']]
            if valid:reason='eligible_correct_candidate_rejected_by_frozen_model'
            elif correct_candidates[label]:reason='correct_candidate_present_but_not_eligible'
            else:reason='correct_candidate_absent'
            total[reason]+=1
            rows.append({'cell':label,'reason':reason,
                         'candidate_count':len(choices[label]),'eligible_correct_candidate_count':len(valid),
                         'maximum_correct_candidate_probability':max(
                             (pred['candidate_probabilities'][c['id']] for c in valid),default=None),
                         'correct_candidate_origins':sorted({o for c in correct_candidates[label] for o in c['origins']})})
        report.append({'id':item['id'],'origin':item['origin'],'scenario':t['scenario'],'errors':rows})
        w.close()
    out=ROOT/'qa/MULTISOURCE_DEV17_MISS_DIAGNOSIS_20261018.json';assert not out.exists()
    save(out,{'totals':dict(total),'cases':report,'predictions_unchanged':True,
              'post_hoc_labels_deliberately_read':True,
              'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'audit_script_sha256':sha(Path(__file__)),
              'final_validation_eligible':False})
    print(dict(total),flush=True)
if __name__=='__main__':main()
