"""Qualify reviewer evidence availability without changing frozen scores or review."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_signed_learning_dev19 import BASE
from formulaguard.workbook import WorkbookModel

def main():
    review=ROOT/'qa/SIGNED_LEARNING_DEV19_POSTHOC_BUSINESS_REVIEW_20261018.json'
    rows=read(review)['rows'];index={r['case']:r for r in read(BASE/'public_index.json')};models={}
    original=WorkbookModel.from_xlsx(ROOT/index['lcoe/annotation01']['input']);out=[]
    for r in rows:
        case=r['case'];s,a=r['cell'].rsplit('!',1)
        if case not in models:models[case]=WorkbookModel.from_xlsx(ROOT/index[case]['input'])
        model=models[case]
        evidence=['B42','C42','B43','C44','B45','C45','E45']
        assert all(model.cells.get((s,k))==original.cells.get((s,k)) for k in evidence)
        assert all(model.is_visible((s,k)) for k in evidence if k!='E45')
        assert original.is_visible((s,'E45'))
        out.append({'case':case,'cell':r['cell'],'current_note_visible':model.is_visible((s,'E45')),
                    'cost_titles_and_currency_units_visible':True,'original_reviewed_note_unchanged':True})
    hidden=[r for r in out if not r['current_note_visible']];assert len(hidden)==2
    p=ROOT/'qa/SIGNED_LEARNING_DEV19_EVIDENCE_VISIBILITY_ADDENDUM_20261018.json';assert not p.exists()
    save(p,{'rows':out,'current_hidden_note_outputs':hidden,'review_sha256':sha(review),
         'clarification':'Original review said visible description for all 80 outputs. For 2 annotation11 Offshore cells E45 is hidden; their relation label is inherited from the unchanged reviewed original, with current cost titles and currency units visible. This is reviewer evidence, not predictor permission to read hidden text.',
         'reviewed_harmful_outputs_unchanged':80,'frozen_scores_unchanged':True,'final_validation_eligible':False})

if __name__=='__main__':main()
