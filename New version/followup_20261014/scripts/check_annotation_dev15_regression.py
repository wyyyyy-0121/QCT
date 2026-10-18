"""Post-hoc label-free check on 167 locked legacy inputs; upstream SG/FG is reused."""
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_selector_dev8 import guard_prediction
from formulaguard.workbook import WorkbookModel
from annotation_evidence_dev15 import apply
OLD=ROOT/'development/selector_dev12_reconciliation_v1'

def main():
    out=ROOT/'qa/ANNOTATION_DEV15_LEGACY_REGRESSION_20261018.json'
    if out.exists():raise SystemExit('Preserve audit')
    index=read(OLD/'public_index.json')
    lock=read(OLD/'prediction_lock.json')
    accesses,active=set(),[True]; guard_prediction(accesses,active)
    results=[]; start=time.perf_counter(); cpu=time.process_time()
    for item in index:
        path=ROOT/item['input']
        upstream=OLD/'predictions'/item['group']/(item['id']+'.json.gz')
        rel=str(upstream.relative_to(OLD))
        assert sha(upstream)==lock['files'][rel]
        assert sha(path)==item['input_sha256']
        old=read(upstream); prior=old['dev11']
        m=WorkbookModel.from_xlsx(path)
        paper=old['paper']
        if paper is None:
            # For older cases paper candidates are unavailable here. Missing
            # annotation evidence must short-circuit before candidate generation.
            paper={'rows':[{'cell':r['cell'],'suggested_formula':None} for r in prior['rows']]}
        r=apply(m,prior,paper)
        evidence=sum('annotation_evidence' in v for v in r['note_only']['rows'])
        proposals=sum(v['status']=='propose' for v in r['note_only']['rows'])
        assert evidence==proposals==0,(item['id'],evidence,proposals)
        assert r['dev11_plus_note']['rows']==prior['rows'],item['id']
        results.append({'id':item['id'],'group':item['group'],'input_sha256':sha(path),
                        'prior_prediction_sha256':sha(upstream),'annotation_matches':evidence,
                        'new_suggestions':proposals,'prior_rows_unchanged':True,
                        'paper_candidates_available':old['paper'] is not None})
    active[0]=False
    save(out,{'cases':len(results),'details':results,'labels_read':[],
              'all_prior_rows_unchanged':True,'new_suggestions':0,'accesses':sorted(accesses),
              'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.process_time()-cpu,
              'upstream_prediction_lock_sha256':sha(OLD/'prediction_lock.json'),
              'selector_sha256':sha(ROOT/'scripts/annotation_evidence_dev15.py'),
              'audit_script_sha256':sha(Path(__file__)),
              'scope':'post-hoc selector regression with frozen upstream; SG/FG not rerun; no performance generalization',
              'final_validation_eligible':False})
    print('unchanged legacy decisions',len(results),flush=True)
if __name__=='__main__':main()
