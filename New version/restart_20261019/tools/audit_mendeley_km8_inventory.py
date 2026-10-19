#!/usr/bin/env python3
"""Download fixed CC BY source; inspect formula counts only, never formula text."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import posixpath
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from spreadsheetbench2_scoring import sha256

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'source_evidence/raw/mendeley_km8_source'
META=ROOT/'source_evidence/MENDELEY_KM8_FILES_20261019.json'
OUT=ROOT/'source_evidence/MENDELEY_KM8_INVENTORY_20261019.json'
MAIN='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def main():
    if OUT.exists() or RAW.exists():
        raise SystemExit('Preserve acquisition evidence')
    metadata=json.loads(META.read_text())
    if metadata['snapshot']['licence']['short_name']!='CC BY 4.0' or metadata['snapshot']['version']!=1:
        raise SystemExit('Source version/license changed')
    files=next(r['metadata'] for r in metadata['requests'] if '/files?' in r['url'] and r['ok'])
    books=[r for r in files if r['filename'].endswith('.xlsx')]
    if {r['filename'] for r in books}!={'farmers_income_panel_Sichuan.xlsx','policy_effect_DiD_rural_revitalization.xlsx'}:
        raise SystemExit('Source scope changed')
    locked=[META,ROOT/'MENDELEY_KM8_SOURCE_PLAN.md',Path(__file__),ROOT/'tools/spreadsheetbench2_scoring.py']
    RAW.mkdir()
    lock=dict(files_sha256={str(p):sha256(p) for p in locked},
              source_files=books,created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
              body_policy='Formula element counts and sheet names only; no formula/value inspection')
    with (RAW/'input_lock.json').open('x') as handle:
        json.dump(lock,handle,ensure_ascii=False,indent=2);handle.write('\n')

    def fetch(item):
        details=item['content_details']
        req=urllib.request.Request(details['download_url'],headers={'User-Agent':'HybridGuard-source-inventory/1.0'})
        with urllib.request.urlopen(req,timeout=25) as response:
            body=response.read(details['size']+1)
            if response.status!=200:
                raise ValueError('Download unsuccessful')
        path=RAW/item['filename']
        with path.open('xb') as handle:
            handle.write(body)
        if len(body)!=details['size'] or sha256(path)!=details['sha256_hash']:
            raise ValueError('Official file size/hash differs')
        rows=[]
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist())>50_000_000:
                raise ValueError('Archive size bound exceeded')
            workbook=ET.fromstring(archive.read('xl/workbook.xml'))
            rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
            for sheet in workbook.find(MAIN+'sheets'):
                target=rels[sheet.attrib[REL+'id']]
                member=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl',target))
                xml=ET.fromstring(archive.read(member))
                rows.append(dict(sheet=sheet.attrib['name'],state=sheet.attrib.get('state','visible'),
                                 formula_elements=sum(1 for _ in xml.iter(MAIN+'f'))))
            links=sum(name.startswith('xl/externalLinks/') and name.endswith('.xml') for name in archive.namelist())
        return dict(filename=item['filename'],sha256=sha256(path),bytes=len(body),sheets=rows,
                    formula_elements=sum(r['formula_elements'] for r in rows),external_link_xml_files=links)

    with ThreadPoolExecutor(max_workers=20) as pool:
        rows=list(pool.map(fetch,books))
    for name,digest in lock['files_sha256'].items():
        if sha256(Path(name))!=digest:
            raise SystemExit('Inventory implementation/metadata changed')
    count=sum(s['formula_elements'] for r in rows for s in r['sheets'] if s['sheet'] in {'Panel_data','DiD_panel'})
    result=dict(source_doi='10.17632/km8rkfgcpb.1',license='CC BY 4.0',records=rows,
                preregistration_input_lock_sha256=sha256(RAW/'input_lock.json'),
                target_data_sheet_formula_elements=count,formula_texts_inspected=False,cell_values_inspected=False,
                model_run=False,truth_certified=False,accepted_natural_sources=0,accepted_final_sources=0,
                accepted_final_families=0,final_validation_eligible=False,
                decision='stop_no_target_formula_in_public_data_sheets' if count==0 else 'requires_separate_baseline_lock_and_truth_audit')
    with OUT.open('x') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
