"""Acquire immutable, explicitly excluded LDAS natural-correction versions."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import base64
import hashlib
import json
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'development/natural_ldas_dev27_v1'
TARGETS=[('before','a7130e0b7efcabf8f8698e1c4bc4dc6432e5c585'),
         ('after','7d20714a0868d40abc804669c4a9d82ebc3891f7')]


def acquire(item):
    name,expected=item;url='https://api.github.com/repos/Gh0st0ne/LDAS/git/blobs/'+expected
    row=dict(version=name,url=url,expected_git_blob=expected)
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'HybridGuard-development/1.0','Accept':'application/vnd.github+json'}),timeout=20) as r:
            payload=r.read(2_000_001);status=r.status
        assert len(payload)<=2_000_000
        raw=base64.b64decode(json.loads(payload)['content'])
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==expected
        path=RUN/'raw'/(name+'.xlsx');path.write_bytes(raw)
        row.update(ok=True,status=status,path=str(path.relative_to(ROOT)),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    except Exception as error:row.update(ok=False,error=type(error).__name__+': '+str(error))
    print(name,row.get('ok'),row.get('error',''),flush=True);return row


def main():
    assert not RUN.exists()
    docs=ROOT/'source_discovery/natural_pair_docs_dev27_20261018'
    license_row=next(r for r in json.loads((docs/'RECEIPT.json').read_text())['records'] if r['name']=='ldas_license')
    assert license_row['ok'] and hashlib.sha256((ROOT/license_row['path']).read_bytes()).hexdigest()==license_row['sha256']
    (RUN/'raw').mkdir(parents=True);(RUN/'.gitignore').write_text('raw/\n')
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(acquire,TARGETS))
    receipt=dict(records=rows,role='Explicitly excluded natural-error development source',
                 final_validation_eligible=False,prior_correction_mechanism_metadata_exposed=True,
                 preregistration_sha256=hashlib.sha256((ROOT/'LDAS_NATURAL_DEV27_PREREGISTRATION_20261018.md').read_bytes()).hexdigest(),
                 license_sha256=license_row['sha256'],script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (RUN/'acquisition.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
