"""Fetch author-master ODF versions for post-prediction provenance audit."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/natural_hobyah_dev26_v1'
VERSIONS = [('before', '6169e5061a9d225317871511dbc17a7a7a78c1cf'),
            ('after', '76a6c72277d064b6e59331e33659e9ce43344df2')]


def fetch(item):
    name, expected = item
    url = 'https://api.github.com/repos/ECB2020/Hobyah/git/blobs/' + expected
    result = dict(version=name, url=url, expected_git_blob=expected)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={
                'User-Agent': 'HybridGuard-development/1.0', 'Accept': 'application/vnd.github+json'}), timeout=20) as response:
            body = response.read(2_000_001); status = response.status
        assert len(body) <= 2_000_000
        data = json.loads(body); raw = base64.b64decode(data['content'])
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert actual == expected
        path = RUN / 'raw' / (name + '.ods'); assert not path.exists(); path.write_bytes(raw)
        result.update(ok=True, status=status, bytes=len(raw), git_blob=actual,
                      sha256=hashlib.sha256(raw).hexdigest(), path=str(path.relative_to(ROOT)))
    except Exception as error:
        result.update(ok=False, error=type(error).__name__ + ': ' + str(error))
    print(name, result, flush=True)
    return result


def main():
    assert (RUN / 'prediction_lock.json').exists()
    target = RUN / 'odf_acquisition.json'; assert not target.exists()
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(fetch, VERSIONS))
    receipt = dict(records=rows, purpose='Author-master cross-check after XLSX prediction lock',
                   final_validation_eligible=False, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__': main()
