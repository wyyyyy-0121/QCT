"""Local read-only acquisition of immutable public correction candidate files."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import json
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'development/natural_cv500_dev27_v1'
TARGETS=[('before','d8f73fa99176ec227cf91c14adf70db4c2d5c9b7'),('after','b3eb6b881b1f6506e1c009ff5b26299a370fbf66')]


def fetch(item):
    name,expected=item;url='https://api.github.com/repos/mirontoli/cv-500/git/blobs/'+expected
    row=dict(version=name,url=url,expected_git_blob=expected)
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'HybridGuard-research/1.0','Accept':'application/vnd.github+json'}),timeout=20) as response:
            body=response.read(2_000_001);status=response.status
        assert len(body)<=2_000_000
        raw=base64.b64decode(json.loads(body)['content'])
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==expected
        path=RUN/'raw'/(name+'.xlsx');path.write_bytes(raw)
        row.update(ok=True,status=status,path=str(path.relative_to(ROOT)),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    except Exception as error:row.update(ok=False,error=type(error).__name__+': '+str(error))
    print(name,row.get('ok'),row.get('error',''),flush=True);return row


def main():
    assert not RUN.exists();(RUN/'raw').mkdir(parents=True);(RUN/'.gitignore').write_text('raw/\n')
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(fetch,TARGETS))
    result=dict(records=rows,final_validation_eligible=False,role='Excluded natural-formula development evidence',
                redistribution_license_not_established=True,original_workbooks_kept_local=True,
                prior_readme_formula_mechanism_exposed=True,
                preregistration_sha256=hashlib.sha256((ROOT/'CV500_NATURAL_DEV27_PREREGISTRATION_20261018.md').read_bytes()).hexdigest(),
                script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (RUN/'acquisition.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
