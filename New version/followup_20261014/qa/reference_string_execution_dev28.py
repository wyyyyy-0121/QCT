"""Compare every natural text result to a fresh isolated LibreOffice run."""
from pathlib import Path
import hashlib
import subprocess
import sys
import time
import openpyxl

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'qa'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_string_execution_dev28 import RUN,CASES


def main():
    lock=read(RUN/'execution_lock.json')
    for rel,digest in lock['files'].items():assert sha(RUN/rel)==digest
    assert sha(RUN/'local/executed_text.json.gz')==lock['local_text_sha256']
    original=CASES[0][1];digest=sha(original)
    target=RUN/'independent_reference.json';assert not target.exists()
    out=RUN/'local/reference';out.mkdir(parents=True)
    profile=RUN/'local/lo-profile'
    command=['/usr/bin/libreoffice','-env:UserInstallation='+profile.resolve().as_uri(),
             '--headless','--convert-to','xlsx','--outdir',str(out),str(original)]
    started=time.perf_counter()
    try:
        p=subprocess.run(command,capture_output=True,text=True,timeout=60)
        status=dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,wall_seconds=time.perf_counter()-started)
    except subprocess.TimeoutExpired as error:
        status=dict(timeout_seconds=60,stdout=str(error.stdout),stderr=str(error.stderr),wall_seconds=time.perf_counter()-started)
    save(RUN/'reference_command.json',dict(command=command,status=status,source_sha256=digest))
    assert sha(original)==digest
    output=out/original.name
    assert status.get('returncode')==0 and output.exists(),status
    book=openpyxl.load_workbook(output,data_only=True);local=read(RUN/'local/executed_text.json.gz')['rows']
    rows=[]
    for r in local:
        if r['case']!='cv500':continue
        sheet,cell=r['cell'].rsplit('!',1);ref=book[sheet][cell]
        match=ref.data_type!='e' and isinstance(ref.value,str) and ref.value==r['value']
        rows.append(dict(cell=r['cell'],exact_agreement=match,reference_type=ref.data_type,
                         reference_text_sha256=hashlib.sha256(ref.value.encode()).hexdigest() if isinstance(ref.value,str) else None))
    assert len(rows)==505
    save(target,dict(rows=rows,compared=505,exact_text_agreements=sum(r['exact_agreement'] for r in rows),
          original_input_unchanged=sha(original)==digest,reference_output_sha256=sha(output),
          execution_lock_sha256=sha(RUN/'execution_lock.json'),command_receipt_sha256=sha(RUN/'reference_command.json'),
          auditor_sha256=sha(Path(__file__)),business_truth_claimed=False,repair_suggestions_generated=False,
          libreoffice_version=subprocess.check_output(['/usr/bin/libreoffice','--version'],text=True).strip()))
    print('DEV28 independent LibreOffice exact text agreement',sum(r['exact_agreement'] for r in rows),'/',len(rows),flush=True)


if __name__=='__main__':main()
