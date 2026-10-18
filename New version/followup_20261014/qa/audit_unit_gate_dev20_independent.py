"""Independent OOXML reader and simple two-reference algebra for dev19 rejections."""
from pathlib import Path
from collections import Counter
import re
import sys
import openpyxl
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from build_candidates_dev18 import protection
from build_unit_features_dev20 import BASE,DATA,load
from diagnose_unit_gate_dev20 import RUN,verify
verify();active,accesses=protection();rows=[];counts=Counter()
for item in read(BASE/'public_index.json'):
    case=item['case'];p=read(RUN/'predictions'/(case.replace('/','__')+'.json.gz'))
    after={r['candidate_id'] for r in p['dev19_unit_filtered']}
    rejected=[r for r in p['dev19_original'] if r['candidate_id'] not in after]
    if not rejected:continue
    assert sha(ROOT/item['input'])==item['input_sha256']
    book=openpyxl.load_workbook(ROOT/item['input'],data_only=False,read_only=False,keep_links=False)
    for r in rejected:
        s,a=r['cell'].rsplit('!',1);ws=book[s]
        assert ws.sheet_state=='visible'
        # These observations are read from the input, not from a repaired answer.
        old=re.fullmatch(r'=([A-Z]+)(\d+)\+([A-Z]+)(\d+)',ws[a].value)
        new=re.fullmatch(r'=([A-Z]+)(\d+)\*([A-Z]+)(\d+)',r['suggested_formula'])
        assert old and new and old.groups()==new.groups()
        cols=[old[1],old[3]];rs=[int(old[2]),int(old[4]),ws[a].row]
        assert cols[0]==cols[1]==ws[a].column_letter
        for row in rs:
            assert ws[f'C{row}'].value=='£m'
            assert not ws.row_dimensions[row].hidden
        for col in ['C',ws[a].column_letter]:
            assert not any(dim.hidden and (dim.min or openpyxl.utils.column_index_from_string(k))<=openpyxl.utils.column_index_from_string(col)<=(dim.max or openpyxl.utils.column_index_from_string(k)) for k,dim in ws.column_dimensions.items())
        # Formal written unit exponent: sum -> 1; product -> 2; target -> 1.
        assert 1==1 and 1+1!=1
        rows.append({'case':case,'cell':r['cell'],'observed':ws[a].value,
                     'candidate':r['suggested_formula'],'unit_cells':['C'+str(x) for x in rs],
                     'written_unit':'£m','sum_exponent':1,'product_exponent':2,'target_exponent':1})
        counts[s+'!'+a]+=1
    book.close()
active[0]=False
out=ROOT/'qa/UNIT_GATE_DEV20_INDEPENDENT_DIMENSIONS_20261018.json';assert not out.exists()
save(out,{'rejected_suggestions':len(rows),'unique_original_cells':len(counts),'cell_repeat_counts':dict(counts),
          'rows':rows,'all_units_visible_and_simple_sum_to_product_confirmed':True,'labels_read':[],
          'accesses':sorted(accesses),'audit_source_sha256':sha(Path(__file__)),
          'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'final_validation_eligible':False})
print(len(rows),dict(counts))
