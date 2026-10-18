"""Retry only failed pinned blob transfers, preserving the initial receipt."""
from pathlib import Path
import base64
import hashlib
import json
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'development/natural_cv500_dev27_v1'


def main():
    assert not (RUN/'prediction_lock.json').exists()
    target=RUN/'acquisition.json';initial=RUN/'acquisition_initial_transfer_failure.json'
    assert not initial.exists();initial.write_bytes(target.read_bytes());receipt=json.loads(target.read_text())
    for row in receipt['records']:
        if row['ok']:continue
        row['initial_error']=row.pop('error')
        try:
            with urllib.request.urlopen(urllib.request.Request(row['url'],headers={'User-Agent':'HybridGuard-research/1.0','Accept':'application/vnd.github+json'}),timeout=20) as response:
                body=response.read(2_000_001);status=response.status
            assert len(body)<=2_000_000
            raw=base64.b64decode(json.loads(body)['content'])
            assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==row['expected_git_blob']
            path=RUN/'raw'/(row['version']+'.xlsx');assert not path.exists();path.write_bytes(raw)
            row.update(ok=True,status=status,path=str(path.relative_to(ROOT)),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        except Exception as error:row.update(ok=False,error=type(error).__name__+': '+str(error))
        print(row['version'],row['ok'],row.get('error',''),flush=True)
    receipt['initial_receipt_sha256']=hashlib.sha256(initial.read_bytes()).hexdigest()
    receipt['recovery_script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
