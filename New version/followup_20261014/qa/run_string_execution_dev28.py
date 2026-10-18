"""Lock complete typed execution on three excluded natural-source originals."""
from pathlib import Path
from collections import Counter
import hashlib
import os
import sys
import time
import openpyxl

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from string_execution_dev28 import parse,execute,provenance,Unsupported,VERSION
from typed_execution_adapter import load_typed_inputs,ExcelError

RUN=ROOT/'development/string_execution_dev28_v1'
CASES=[('cv500',ROOT/'development/natural_cv500_dev27_v1/raw/before.xlsx'),
       ('ldas',ROOT/'development/natural_ldas_dev27_v1/raw/before.xlsx'),
       ('hobyah',ROOT/'development/natural_hobyah_dev26_v1/raw/before.xlsx')]


def value_record(value):
    if isinstance(value,ExcelError):return dict(kind='error',error=value.code)
    if isinstance(value,str):return dict(kind='text',sha256=hashlib.sha256(value.encode()).hexdigest(),characters=len(value))
    return dict(kind=type(value).__name__,value=value)


def main():
    assert not RUN.exists();RUN.mkdir(parents=True);(RUN/'.gitignore').write_text('local/\n')
    paths=[ROOT/'scripts/string_execution_dev28.py',ROOT/'scripts/typed_execution_adapter.py',Path(__file__),
           ROOT/'tests/test_string_execution_dev28.py',ROOT/'STRING_EXECUTION_DEV28_PREREGISTRATION_20261018.md']
    save(RUN/'source_lock.json',dict(files={str(p.relative_to(ROOT)):sha(p) for p in paths},
                                    inputs={name:sha(p) for name,p in CASES},version=VERSION))
    # No heldout/correction truth or author diffs may enter execution.
    accessed=set();active=[True]
    def guard(event,args):
        if not active[0] or event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
        name=os.fsdecode(args[0]);low=name.lower()
        if any(s in low for s in ['after.xlsx','natural_truth','natural_score','author_diff','role_alignment','certification','historical_fix','natural_pair_docs']):
            raise PermissionError('String executor cannot read correction evidence: '+name)
        if '/raw/' in name:accessed.add(name)
    sys.addaudithook(guard)
    rows=[];local=[];start=time.perf_counter()
    for case,path in CASES:
        book=openpyxl.load_workbook(path,data_only=False);typed=load_typed_inputs(path)
        formulas={(s.title,c.coordinate):c.value for s in book for row in s for c in row if c.data_type=='f'}
        counts=Counter();case_rows=[]
        for key,formula in sorted(formulas.items()):
            item=dict(cell=key[0]+'!'+key[1],formula_sha256=hashlib.sha256(formula.encode()).hexdigest())
            try:
                node=parse(formula);refs=provenance(node,key[0]);value=execute(node,key[0],typed,formula_cells=formulas,sheet_names=book.sheetnames)
                item.update(status='executed',value=value_record(value),references=refs)
                if isinstance(value,str):local.append(dict(case=case,cell=item['cell'],value=value))
                counts['executed']+=1
            except Unsupported as e:item.update(status='unsupported',reason=e.code);counts[e.code]+=1
            case_rows.append(item)
        assert sha(path)==read(RUN/'source_lock.json')['inputs'][case]
        rows.append(dict(case=case,formulas=len(formulas),counts=dict(counts),cells=case_rows))
        print('DEV28',case,len(formulas),dict(counts),flush=True)
    save(RUN/'local/executed_text.json.gz',dict(rows=local))
    save(RUN/'execution.json.gz',dict(cases=rows,wall_seconds=time.perf_counter()-start,
          labels_read=[],correction_versions_read=[],repair_suggestions_generated=False,final_validation_eligible=False,
          input_accesses=sorted(accessed),source_lock_sha256=sha(RUN/'source_lock.json')))
    active[0]=False
    save(RUN/'execution_lock.json',dict(files={'execution.json.gz':sha(RUN/'execution.json.gz')},
         local_text_sha256=sha(RUN/'local/executed_text.json.gz'),source_lock_sha256=sha(RUN/'source_lock.json'),
         final_validation_eligible=False,business_labels_read=[]))


if __name__=='__main__':main()
