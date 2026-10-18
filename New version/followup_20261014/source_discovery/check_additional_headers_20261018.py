"""Check publisher's public download links without reading workbook bodies."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from check_candidate_headers_20261018 import check

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / 'RESERVED_ADDITIONAL_CANDIDATES_20261018.json'
OUT = ROOT / 'ADDITIONAL_HEADER_RECEIPT_20261018.json'

if __name__ == '__main__':
    if OUT.exists():
        raise SystemExit('Preserve evidence')
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(check, json.loads(INDEX.read_text())['items']))
    OUT.write_text(json.dumps({'method': 'HEAD only', 'workbook_bodies_acquired': 0,
                               'index_sha256': hashlib.sha256(INDEX.read_bytes()).hexdigest(),
                               'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                 for p in [Path(__file__), ROOT / 'check_candidate_headers_20261018.py']},
                               'results': rows}, indent=2)+'\n')
    for row in rows:
        print(row['id'], row.get('status'), row.get('content_type'), row.get('resolved_url'), flush=True)
