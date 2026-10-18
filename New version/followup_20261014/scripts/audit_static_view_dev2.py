"""Independently compare source/view packages and openpyxl cell snapshots."""
from pathlib import Path
import datetime
import json
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_static_view_dev2 import verify, RUN
from run_selector_dev5 import read, save, sha
from openpyxl import load_workbook
from structuralguard.workbook import WorkbookSnapshot


def cells(path):
    wb=load_workbook(path,data_only=False,read_only=False,keep_links=False)
    result={}
    for sheet in wb:
        snapshot={}
        for row in sheet:
            for cell in row:
                if cell.value is not None:
                    value=cell.value
                    if not isinstance(value,(str,int,float,bool,type(None))):
                        value={'type':type(value).__name__,'text':getattr(value,'text',str(value)),
                               'ref':getattr(value,'ref',None)}
                    snapshot[cell.coordinate]={'type':cell.data_type,'value':value}
        result[sheet.title]={'state':sheet.sheet_state,'cells':snapshot,
            'hidden_rows':sorted(k for k,v in sheet.row_dimensions.items() if v.hidden),
            'hidden_columns':sorted(k for k,v in sheet.column_dimensions.items() if v.hidden)}
    wb.close()
    return result


def audit():
    verify();cases=[]
    for item in read(RUN/'public_index.json'):
        source=REPO/item['relative_path'];before=sha(source)
        pred=read(RUN/'predictions'/(item['id']+'.json.gz'))
        entry={'id':item['id'],'status':pred['status'],'source_sha256':before}
        if pred['status']=='input_rejected':
            assert item['id']=='public05' and 'answer/label' in pred['error']
            assert not (RUN/'views'/(item['id']+'.xlsx')).exists()
            entry.update(formula_bodies_read_by_audit=False,protected_manifest_rejection_retained=True)
        else:
            assert pred['status']=='static_inference_complete_unscored'
            view=RUN/'views'/(item['id']+'.xlsx');receipt=pred['view_receipt']
            assert sha(view)==receipt['view_sha256'] and before==receipt['source_sha256']
            with zipfile.ZipFile(source) as a,zipfile.ZipFile(view) as b:
                original=set(a.namelist());published=set(b.namelist())
                assert original-published==set(receipt['removed_parts'])
                assert not (published-original)
                altered=[];declarations=0
                for name in sorted(published):
                    if a.read(name)!=b.read(name):altered.append(name)
                    if name.startswith('xl/worksheets/') and name.endswith('.xml'):
                        assert a.read(name)==b.read(name)
                        declarations+=len(ET.fromstring(a.read(name)).findall('.//{*}c/{*}f'))
                assert altered==receipt['modified_package_metadata']
                assert all(n=='[Content_Types].xml' or n.endswith('.rels') for n in altered)
                assert a.read('xl/workbook.xml')==b.read('xl/workbook.xml')
                assert 'xl/vbaProject.bin' not in published
            original_cells,view_cells=cells(source),cells(view)
            assert original_cells==view_cells
            formulas={s+'!'+addr:v['value'] for s,data in original_cells.items()
                      for addr,v in data['cells'].items() if v['type']=='f'}
            assert formulas==pred['observed_formulas']
            assert declarations==pred['declaration_count']
            assert not pred['declarations_absent_from_prediction']
            counts={name:sum(bool(r.get('suggested_formula')) and
                              r['suggested_formula']!=formulas[r['cell']] and
                              (name=='paper' or r['status']=='propose') for r in pred[name]['rows'])
                    for name in ['paper','dev11']}
            assert all(counts[n]==pred['summaries'][n]['actual_modification_suggestions'] for n in counts)
            raw_rejected=None
            if source.suffix=='.xlsm':
                try:WorkbookSnapshot.load(source)
                except ValueError as error:
                    assert '.xlsx only' in str(error);raw_rejected=True
                else:raise AssertionError('Raw original SG should reject xlsm')
            entry.update(raw_formula_declarations=declarations,loaded_formula_cells=len(formulas),
                all_cell_values_and_types_equal=True,worksheet_bytes_equal=True,
                hidden_sheet_row_column_states_equal=True,
                original_sg_extension_rejection_confirmed=raw_rejected,
                evaluation_errors=len(pred['evaluation_errors']),proposals=counts,
                worker_cpu_seconds=pred['cpu_seconds'],worker_wall_seconds=pred['wall_seconds'],
                peak_rss_kib=pred['peak_rss_kib'],control=pred['control'])
        assert sha(source)==before==item['sha256']
        entry['original_input_unchanged']=True
        cases.append(entry)
    result={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cases':cases,
       'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'auditor_sha256':sha(Path(__file__)),
       'business_labels_available':False,'precision':None,'coverage':None,
       'new_final_sources':0,'new_final_families':0,'final_validation_eligible':False}
    save(ROOT/'qa/STATIC_VIEW_DEV2_INDEPENDENT_AUDIT_20261018.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':audit()
