"""Acquire original first; correction is inaccessible until prediction lock."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_selector_dev5 import read, save, sha

RUN = ROOT / 'development/natural_weights_dev33_v1'
BLOBS = {'before': '86ed27f5c118084e9909a40fbb6edbd6b3ca9beb',
         'after': '1f17d094a4520fd8446d6853b3748890e4ad5a06'}


def acquire(version):
    if version == 'before':
        assert not RUN.exists()
        (RUN / 'raw').mkdir(parents=True)
        (RUN / '.gitignore').write_text('raw/\nauthor_diff.local.json.gz\n')
    else:
        lock = read(RUN / 'prediction_lock.json')
        for rel, digest in lock['files'].items():
            assert sha(RUN / rel) == digest
        assert not (RUN / 'raw/after.xlsx').exists()
    receipt = RUN / ('acquisition.json' if version == 'before' else 'correction_acquisition.json')
    assert not receipt.exists()
    blob = BLOBS[version]
    url = 'https://api.github.com/repos/drjlevi6/Data-Scientist/git/blobs/' + blob
    row = dict(version=version, url=url, expected_git_blob=blob)
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'HybridGuard-natural-development/1.0',
                                                       'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read(2000001); status = response.status
        assert len(body) <= 2000000
        payload = json.loads(body); assert payload['encoding'] == 'base64'
        raw = base64.b64decode(payload['content'])
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob
        path = RUN / 'raw' / (version + '.xlsx'); assert not path.exists(); path.write_bytes(raw)
        row.update(ok=True, status=status, bytes=len(raw), path=str(path.relative_to(ROOT)), sha256=sha(path))
    except Exception as error:
        row.update(ok=False, error=type(error).__name__ + ': ' + str(error))
    save(receipt, dict(records=[row], final_validation_eligible=False,
         role='Entire origin permanently excluded natural-correction development evidence',
         preregistration_sha256=sha(ROOT / 'WEIGHTS_NATURAL_DEV33_PREREGISTRATION_20261018.md'),
         script_sha256=sha(Path(__file__)),
         original_prediction_lock_sha256=sha(RUN / 'prediction_lock.json') if version == 'after' else None))
    print(row, flush=True)
    if not row['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('version', choices=['before', 'after'])
    acquire(parser.parse_args().version)
