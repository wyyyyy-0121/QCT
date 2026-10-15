"""Reconcile a public-development audit with raw OOXML and locked outputs."""
from pathlib import Path
from collections import Counter
import datetime
import json
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from openpyxl.utils.cell import range_boundaries, coordinate_from_string, column_index_from_string

from run_selector_dev5 import ROOT, sha, read, save, verify_files

RUN = ROOT / 'development/public_pycel_dev1'
NS = {'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def verify():
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'acquisition_receipt.json') == lock['acquisition_receipt_sha256']
    assert sha(RUN / 'registration.json') == lock['registration_sha256']
    verify_files(ROOT,read(RUN / 'source_lock.json')['files'])
    verify_files(RUN,lock['files']); verify_files(RUN,lock['inputs'])
    registration = read(RUN / 'registration.json')
    assert not registration['final_validation_eligible']
    audit = read(RUN / 'audit.json'); assert audit['precision'] is audit['coverage'] is None
    assert len(audit['cases']) == len(registration['selected_files']) == 14
    totals = Counter(); cases = []
    for case in audit['cases']:
        raw = RUN / 'raw' / case['source_path']
        if not raw.exists():
            assert case['status'] == 'acquisition_failed'
            cases.append({'id':case['id'],'status':case['status']});continue
        # Count every <f> cell directly, including unsupported/array/shared forms.
        with zipfile.ZipFile(raw) as archive:
            relations = {node.attrib['Id']:node.attrib['Target'] for node in
                ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
            raw_formulas = {}
            for sheet in ET.fromstring(archive.read('xl/workbook.xml')).findall('x:sheets/x:sheet',NS):
                target = relations[sheet.attrib[REL]]
                target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
                for cell in ET.fromstring(archive.read(target)).findall('x:sheetData/x:row/x:c',NS):
                    formula = cell.find('x:f',NS)
                    if formula is not None:
                        raw_formulas[sheet.attrib['name']+'!'+cell.attrib['r']] = {
                            'text':formula.text, 'attributes':formula.attrib}
            formula_count = len(raw_formulas)
        assert case['status']=='inference_complete_unscored'
        pred = read(RUN / 'predictions' / (case['id']+'.json.gz'))
        observed = pred['observed_formulas']; assert len(observed)==case['formula_cells']
        assert set(observed)<=set(raw_formulas)
        omissions = {cell:raw_formulas[cell] for cell in sorted(set(raw_formulas)-set(observed))}
        arrays = []
        for label, declaration in raw_formulas.items():
            attrs = declaration['attributes']
            if attrs.get('t')=='array' and 'ref' in attrs:
                sheet, address = label.rsplit('!',1)
                arrays.append((sheet,address,range_boundaries(attrs['ref'])))
        for label, declaration in omissions.items():
            sheet, address = label.rsplit('!',1)
            col, row = coordinate_from_string(address);col=column_index_from_string(col)
            owners = [s+'!'+a for s,a,(c1,r1,c2,r2) in arrays
                      if sheet==s and c1<=col<=c2 and r1<=row<=r2]
            declaration['array_anchors']=owners
            declaration['classification']=('empty_array_result_declaration' if owners and not declaration['text']
                                            else 'unresolved_formula_declaration')
            totals[declaration['classification']]+=1
        for name in ['paper','dev4','dev5']:
            rows = pred[name]['rows']
            assert len(rows)==len({r['cell'] for r in rows})==len(observed)
            assert {r['cell'] for r in rows}==set(observed)
            proposals = [{'cell':r['cell'],'formula':r['suggested_formula']} for r in rows
                if r.get('suggested_formula') and r['suggested_formula']!=observed[r['cell']]
                and (name=='paper' or r['status']=='propose')]
            assert proposals==case['change_suggestions'][name]
            totals[name+'_suggestions']+=len(proposals)
        errors = case['evaluation_errors']; assert set(errors)<=set(observed)
        totals['ooxml_formula_cells']+=formula_count
        totals['loaded_formula_cells']+=len(observed)
        totals['omitted_formula_cells']+=len(omissions)
        totals['evaluation_errors']+=len(errors)
        totals['evaluated_without_error']+=case['evaluated_without_error']
        totals['cache_comparable_numeric']+=len(case['cache_comparisons'])
        totals['cache_numeric_agreements']+=sum(r['numeric_agreement'] for r in case['cache_comparisons'])
        cases.append({'id':case['id'],'ooxml_formula_count':formula_count,
                      'loaded_formula_count':len(observed),'omitted_formula_cells':omissions,
                      'all_raw_formula_cells_retained':not omissions,
                      'all_loaded_output_cells_retained':True,
                      'input_sha256':sha(raw)})
    assert totals['loaded_formula_cells']==totals['evaluation_errors']+totals['evaluated_without_error']
    assert totals['ooxml_formula_cells']==totals['loaded_formula_cells']+totals['omitted_formula_cells']
    result = {'cases':cases,'totals':dict(totals),'all_locks_verified':True,
        'precision':None,'coverage':None,'business_repair_truth_available':False,
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'audit_sha256':sha(RUN / 'audit.json'), 'prediction_lock_sha256':sha(RUN / 'prediction_lock.json'),
        'scope':'software-fixture compatibility only; all formula cells counted independently from OOXML'}
    save(ROOT / 'qa/PUBLIC_PYCEL_VERIFICATION_20261015.json',result)
    print(json.dumps(result['totals'],indent=2))


if __name__=='__main__':verify()
