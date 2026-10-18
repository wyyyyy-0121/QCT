"""Post-lock paper control and candidate-pool ceilings; never input to learner."""
from collections import defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_candidate_learning_dev16 import RUN,DATA,verify
from run_selector_dev5 import read,save,sha

def main():
    verify(include_label_bodies=True);truth=read(DATA/'heldout_truth.json.gz')
    score=read(RUN/'score.json');cases=[]
    for item in read(DATA/'public_index.json'):
        case=item['case'];t=truth['cases'][case];errors=set(t['errors'])
        payload=read(DATA/'features'/(case.replace('/','__')+'.json.gz'))
        labels=truth['candidate_labels'][case]
        paper=[c for c in payload['candidates'] if 'paper' in c['origins']]
        assert len(paper)==len({c['cell'] for c in paper})
        correct=sum(labels[c['id']]==1 and c['cell'] in errors for c in paper)
        unknown=sum(labels[c['id']] is None for c in paper)
        coverable={c['cell'] for c in payload['candidates'] if c['eligible'] and labels[c['id']]==1}
        raw_coverable={c['cell'] for c in payload['candidates'] if labels[c['id']]==1}
        row={'case':case,'group':t['group'],'family':t['family'],'origin_group':t['origin_group'],
             'paper_suggestions':len(paper),'paper_correct':correct,'paper_unknown':unknown,
             'paper_confirmed_wrong':len(paper)-correct-unknown,'known_errors':len(errors),
             'eligible_pool_coverable_errors':len(coverable),'raw_pool_coverable_errors':len(raw_coverable),
             'missing_correct_candidates':sorted(errors-coverable)}
        cases.append(row)
    keys=['paper_suggestions','paper_correct','paper_unknown','paper_confirmed_wrong','known_errors',
          'eligible_pool_coverable_errors','raw_pool_coverable_errors']
    def total(rows):
        d={k:sum(r[k] for r in rows) for k in keys}
        d['paper_precision_confirmed_lower_bound']=d['paper_correct']/d['paper_suggestions'] if d['paper_suggestions'] else None
        d['paper_coverage']=d['paper_correct']/d['known_errors'] if d['known_errors'] else None
        d['eligible_pool_coverage_ceiling']=d['eligible_pool_coverable_errors']/d['known_errors'] if d['known_errors'] else None
        return d
    summary=total(cases)
    for scheme,d in score['schemes'].items():
        assert d['candidate_pool_correct_error_ceiling']==summary['eligible_pool_coverable_errors']
        for field in ['family','origin_group','group','fold']:
            for group,methods in d[field].items():
                rows=[r for r in d['cases'] if r[field]==group]
                for mode,m in methods.items():
                    for key in ['suggestions','correct','wrong','unknown','errors','correct_errors','wrong_clean_cells']:
                        assert m[key]==sum(r[mode][key] for r in rows)
                    assert m['precision_confirmed_lower_bound']==(m['correct']/m['suggestions'] if m['suggestions'] else None)
                    assert m['coverage']==(m['correct_errors']/m['errors'] if m['errors'] else None)
    out=ROOT/'qa/CANDIDATE_LEARNING_DEV16_PAPER_AND_CEILING_20261018.json';assert not out.exists()
    save(out,{'all':summary,'cases':cases,
              'by_group':{g:total([r for r in cases if r['group']==g]) for g in sorted({r['group'] for r in cases})},
              'by_origin':{g:total([r for r in cases if r['origin_group']==g]) for g in sorted({r['origin_group'] for r in cases})},
              'all_group_and_family_score_summaries_recounted':True,
              'paper_control':'all nonempty suggested formulas differing from observed, independent of status',
              'ceiling_is_oracle_not_model_performance':True,
              'audit_script_sha256':sha(Path(__file__)),'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
              'final_validation_eligible':False})
    print(summary,flush=True)
if __name__=='__main__':main()
