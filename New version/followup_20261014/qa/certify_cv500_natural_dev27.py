"""Certify same-record meaning references with an independent string interpreter."""
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'qa')]
from run_selector_dev5 import read,save,sha
import run_cv500_natural_dev27 as runner
RUN=runner.RUN


def parse_concat(formula):
    assert formula.startswith('=CONCATENATE(') and formula.endswith(')')
    text=formula[len('=CONCATENATE('):-1];tokens=[];i=0
    while i<len(text):
        while i<len(text) and text[i].isspace():i+=1
        if text[i]=='"':
            i+=1;value=''
            while i<len(text):
                if text[i]=='"':
                    if i+1<len(text) and text[i+1]=='"':value+='"';i+=2;continue
                    i+=1;break
                value+=text[i];i+=1
            else:raise ValueError('unterminated Excel string')
            tokens.append(('text',value))
        else:
            match=re.match(r'[A-Z]+[1-9][0-9]*',text[i:]);assert match,text[i:]
            tokens.append(('ref',match.group()));i+=len(match.group())
        while i<len(text) and text[i].isspace():i+=1
        if i==len(text):break
        assert text[i]==',',text[i:];i+=1;assert i<len(text)
    return tokens


def evaluate(tokens,values):
    return ''.join(value if kind=='text' else ('' if values.get('Sheet1!'+value) is None else str(values['Sheet1!'+value])) for kind,value in tokens)


def main():
    runner.engine.verify();assert read(RUN/'replay.json')['all_predictions_identical']
    diff=read(RUN/'author_diff.json.gz');original=diff['before'];corrected=diff['after']
    assert original['sheets']==corrected['sheets']==['Sheet1']
    assert len(original['formulas'])==len(corrected['formulas'])==len(diff['formula_changes'])==505
    assert len(diff['all_value_changes'])==505
    assert {x['cell'] for x in diff['all_value_changes']}==set(original['formulas'])
    records=[];different_values=0
    for row in range(1,506):
        cell='Sheet1!E'+str(row);old=original['formulas'][cell];new=corrected['formulas'][cell]
        old_tokens=parse_concat(old);new_tokens=parse_concat(new)
        assert len(old_tokens)==len(new_tokens)
        references=[v for kind,v in old_tokens if kind=='ref']
        assert references==[f'A{row}',f'A{row}',f'A{row}',f'B{row}',f'C{row+1}',f'D{row}']
        assert [v for kind,v in new_tokens if kind=='ref']==[f'A{row}',f'A{row}',f'A{row}',f'B{row}',f'C{row}',f'D{row}']
        mismatches=[(a,b) for a,b in zip(old_tokens,new_tokens) if a!=b]
        assert mismatches==[(('ref',f'C{row+1}'),('ref',f'C{row}'))]
        start="<div class='meaning'>";end='</div></div>'
        index=old_tokens.index(('ref',f'C{row+1}'))
        assert old_tokens[index-1][0]=='text' and old_tokens[index-1][1].endswith(start)
        assert old_tokens[index+1][0]=='text' and old_tokens[index+1][1].startswith(end)
        # Independent rendering contract: one output record uses all four
        # columns from that record. This comes from source schema, not majority.
        values=original['values'];a=values[f'Sheet1!A{row}'];b=values[f'Sheet1!B{row}'];c=values[f'Sheet1!C{row}'];d=values[f'Sheet1!D{row}']
        expected=f"<div class='row entry' id='{a}'><div class='col-md-3'><div class='title'><a href='#{a}'>{a}</a></div><div class='sound'>{b}</div><div class='meaning'>{c}</div></div><div class='col-md-9 desc'>{d}</div></div>"
        old_html=evaluate(old_tokens,values);new_html=evaluate(new_tokens,values)
        assert new_html==expected
        changed_value=old_html!=expected;different_values+=changed_value
        # Check a row-specific, unambiguous witness independent of accidental
        # equality or absence of the corpus text in any particular row.
        witness=dict(values);witness[f'Sheet1!C{row}']='CURRENT_ROW_MEANING';witness[f'Sheet1!C{row+1}']='NEXT_ROW_MEANING'
        assert start+'NEXT_ROW_MEANING'+end in evaluate(old_tokens,witness)
        assert start+'CURRENT_ROW_MEANING'+end in evaluate(new_tokens,witness)
        assert isinstance(a,str) and isinstance(b,str) and isinstance(c,str) and isinstance(d,str)
        records.append(dict(cell=cell,original_formula=old,accepted_formula=new,
                            reason='Meaning field must reference column C of the same lexical record; old formula uses next record',
                            actual_output_differs=changed_value,wrong_reference=f'C{row+1}',expected_reference=f'C{row}'))
    truth=dict(role='Revealed public natural formula errors; entire origin excluded from final',
               cases=records,known_formula_cells=505,all_original_formula_cells_labelled=True,
               literal_formula_errors=505,actual_output_mismatch_count=different_values,
               input_data_unchanged=True,unknown_formula_regions=[],
               independent_current_row_rendering_verified=True,
               source_schema='data/README.md at pinned correction tree',
               source_schema_receipt_sha256=sha(ROOT/'source_discovery/natural_pair_docs_dev27_20261018/RECEIPT.json'),
               author_diff_sha256=sha(RUN/'author_diff.json.gz'),prediction_lock_sha256=sha(RUN/'prediction_lock.json'),
               certification_script_sha256=sha(Path(__file__)),final_validation_eligible=False)
    assert not (RUN/'natural_truth.json.gz').exists();save(RUN/'natural_truth.json.gz',truth)
    predictions=read(RUN/'prediction.json.gz');metrics={}
    accepted={r['cell']:r['accepted_formula'] for r in records}
    for mode in ['paper','dev11']:
        suggestions=[r for r in predictions[mode]['rows'] if r.get('status')=='propose' and r.get('suggested_formula')]
        outcomes=[]
        for item in suggestions:
            formula=accepted.get(item['cell'])
            outcome='unknown' if formula is None else ('correct' if formula==item['suggested_formula'] else 'wrong')
            outcomes.append(dict(cell=item['cell'],formula=item['suggested_formula'],outcome=outcome))
        correct=sum(r['outcome']=='correct' for r in outcomes)
        metrics[mode]=dict(suggestions=len(suggestions),correct=correct,errors=505,
                           precision=correct/len(suggestions) if suggestions else None,coverage=correct/505,outcomes=outcomes)
    target=RUN/'natural_score.json';assert not target.exists()
    save(target,dict(metrics=metrics,truth_sha256=sha(RUN/'natural_truth.json.gz'),prediction_lock_sha256=sha(RUN/'prediction_lock.json'),final_validation_eligible=False))
    print('CV500 NATURAL CERTIFIED',len(records),'wrong-row formulas;',different_values,'actual rendering mismatches;',metrics,flush=True)


if __name__=='__main__':main()
