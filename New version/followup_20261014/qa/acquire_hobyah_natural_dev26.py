"""Acquire two pinned versions of an explicitly excluded development source."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import datetime
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'development/natural_hobyah_dev26_v1'
VERSIONS = [
    ('before', '7fd04102210d9d830ff23b497b8ce20f8e5dc215', 'ad8314387ae589ad7186296db29b32ac9ccd943c'),
    ('after', 'a6c7cd441ff1aca4915e8bc2b61d719643927cac', '0e36540c9817f565ae5c00c17d8b94c438db7d65'),
]


def acquire(item):
    name, commit, expected = item
    url = f'https://raw.githubusercontent.com/ECB2020/Hobyah/{commit}/slug-flow-quadratics.xlsx'
    row = dict(version=name, url=url, commit=commit, expected_git_blob=expected)
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'HybridGuard-development/1.0'})
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(2_000_001); status = response.status
        assert len(raw) <= 2_000_000 and raw[:2] == b'PK'
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert actual == expected, (name, actual, expected)
        path = OUT / 'raw' / (name + '.xlsx'); path.write_bytes(raw)
        row.update(ok=True, status=status, bytes=len(raw), git_blob=actual,
                   sha256=hashlib.sha256(raw).hexdigest(), path=str(path.relative_to(ROOT)))
    except Exception as error:
        row.update(ok=False, error=type(error).__name__ + ': ' + str(error))
    print(name, row.get('ok'), row.get('error', ''), flush=True)
    return row


def main():
    if OUT.exists():
        raise SystemExit('Preserve Hobyah acquisition evidence')
    docs = ROOT / 'source_discovery/hobyah_docs_dev26_20261018'
    receipt = json.loads((docs / 'RECEIPT.json').read_text())
    for row in receipt['records']:
        assert hashlib.sha256((docs / row['name']).read_bytes()).hexdigest() == row['sha256']
    # Scope is reviewed in the saved license-review note, never guessed merely
    # from a public GitHub URL. Raw originals stay local to this research run.
    review = ROOT / 'source_discovery/HOBYAH_LICENSE_REVIEW_DEV26_20261018.md'
    assert review.exists()
    (OUT / 'raw').mkdir(parents=True)
    (OUT / '.gitignore').write_text('raw/\n')
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(acquire, VERSIONS))
    result = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), records=rows,
                  role='Excluded-origin natural-error development acquisition',
                  final_validation_eligible=False, accepted_sources=0, accepted_families=0,
                  prior_metadata_truth_exposure=True,
                  preregistration_sha256=hashlib.sha256((ROOT / 'HOBYAH_NATURAL_DEV26_PREREGISTRATION_20261018.md').read_bytes()).hexdigest(),
                  license_review_sha256=hashlib.sha256(review.read_bytes()).hexdigest(),
                  acquisition_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT / 'acquisition.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
