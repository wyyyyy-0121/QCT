"""Search older workbook correction provenance without fetching workbook bodies."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'source_discovery/historical_fix_search_dev25_20261018'
QUERIES = [
    '"fix formula" "xlsx" committer-date:<2024-01-01',
    '"corrected" "spreadsheet" committer-date:<2024-01-01',
    '"formula error" "xls" committer-date:<2024-01-01',
    '"wrong formula" "excel" committer-date:<2024-01-01',
]


def search(item):
    n, query = item
    url = 'https://api.github.com/search/commits?' + urllib.parse.urlencode(
        {'q': query, 'per_page': 15})
    row = dict(query=query, url=url, workbook_bodies_acquired=False)
    try:
        request = urllib.request.Request(url, headers={
            'User-Agent': 'HybridGuard-provenance-metadata/1.0',
            'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(3_000_001)
            row.update(status=response.status,
                       rate_limit_remaining=response.headers.get('X-RateLimit-Remaining'))
        assert len(raw) <= 3_000_000
        data = json.loads(raw)
        saved = dict(total_count=data['total_count'],
                     incomplete_results=data['incomplete_results'],
                     candidates=[dict(repo=x['repository']['full_name'], sha=x['sha'],
                                      url=x['html_url'], message=x['commit']['message'],
                                      parents=[p['sha'] for p in x['parents']])
                                 for x in data['items']])
        path = OUT / f'search_{n:02d}.json'
        path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + '\n')
        row.update(ok=True, response_bytes=len(raw), saved_path=str(path.relative_to(ROOT)),
                   saved_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   returned_candidates=len(saved['candidates']), total_count=saved['total_count'])
    except Exception as error:
        row.update(ok=False, error=type(error).__name__ + ': ' + str(error))
    print(n, row.get('ok'), row.get('total_count'), row.get('error', ''), flush=True)
    return row


def main():
    if OUT.exists():
        raise SystemExit('Preserve historical correction search evidence')
    OUT.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(search, enumerate(QUERIES, 1)))
    receipt = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   role='Correction provenance metadata only; messages are not formula truth',
                   records=rows, workbook_bodies_acquired=False,
                   verified_natural_truth_pairs=0, accepted_sources=0, accepted_families=0,
                   script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT / 'RECEIPT.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
