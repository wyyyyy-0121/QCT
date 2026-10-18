"""Label-free feature availability audit, not a correctness or repair score."""
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from build_candidates_dev18 import DATA,protection
from run_selector_dev5 import read,save,sha
from signed_roles_dev19 import RoleContext
from formulaguard.workbook import WorkbookModel

def main():
    output=ROOT/'qa/SIGNED_ROLES_DEV19_AVAILABILITY_V2_20261018.json'
    assert not output.exists()
    active,accesses=protection();rows=[];wall=time.perf_counter()
    for item in read(DATA/'public_index.json'):
        assert sha(ROOT/item['input'])==item['input_sha256']
        model=WorkbookModel.from_xlsx(ROOT/item['input']);context=RoleContext(model)
        roles=[context.roles(s,a) for s,a in model.formulas]
        rows.append({'case':item['case'],'origin':item['origin_group'],'formulas':len(roles),
                     'targets_with_any_role':sum(bool(r) for r in roles),
                     'targets_with_multiple_roles':sum(len(r)>1 for r in roles)})
        print('availability',item['case'],rows[-1]['targets_with_any_role'],len(roles),flush=True)
    active[0]=False
    save(output,{'cases':rows,'labels_read':[],'accesses':sorted(accesses),'wall_seconds':time.perf_counter()-wall,
         'feature_source_sha256':sha(ROOT/'scripts/signed_roles_dev19.py'),'audit_source_sha256':sha(Path(__file__)),
         'model_trained':False,'repair_metrics':None,'final_validation_eligible':False,
         'scope':'observable target-text lexical availability only; no semantic-correctness validation'})

if __name__=='__main__':main()
