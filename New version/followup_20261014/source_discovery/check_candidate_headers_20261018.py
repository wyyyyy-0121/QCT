"""Check reserved workbook URLs with HEAD only; download no workbook bodies."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import hashlib
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / 'RESERVED_SOURCE_CANDIDATES_20261018.json'
OUT = ROOT / 'CANDIDATE_HEADER_RECEIPT_20261018.json'


def check(item):
    row = {'id': item['id'], 'origin': item['origin'], 'url': item['url'],
           'method': 'HEAD', 'workbook_body_bytes_read': 0,
           'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        with requests.head(item['url'], allow_redirects=True, timeout=(12, 25)) as response:
            assert response.request.method == 'HEAD'
            assert all(x.request.method == 'HEAD' for x in response.history)
            assert not response.content
            row.update(status=response.status_code, resolved_url=response.url,
                       content_type=response.headers.get('Content-Type'),
                       content_length=response.headers.get('Content-Length'),
                       content_disposition=response.headers.get('Content-Disposition'),
                       etag=response.headers.get('ETag'),
                       last_modified=response.headers.get('Last-Modified'))
    except Exception as error:
        row['error'] = type(error).__name__ + ': ' + str(error)
    return row


if __name__ == '__main__':
    if OUT.exists():
        raise SystemExit('Preserve existing receipt')
    items = json.loads(INDEX.read_text())['items']
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for future in as_completed([pool.submit(check, x) for x in items]):
            row = future.result()
            results.append(row)
            print(row['id'], row.get('status'), row.get('content_type'), row.get('error', ''), flush=True)
    OUT.write_text(json.dumps({'index_sha256': hashlib.sha256(INDEX.read_bytes()).hexdigest(),
                               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                               'method': 'HEAD only', 'workbook_bodies_acquired': 0,
                               'accepted_final_sources': 0,
                               'results': sorted(results, key=lambda x: x['id'])}, indent=2)+'\n')
