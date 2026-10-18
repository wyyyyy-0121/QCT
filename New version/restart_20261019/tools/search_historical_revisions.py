#!/usr/bin/env python3
"""Bounded, metadata-only source search; never downloads workbook contents."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    '"formula error" xlsx committer-date:<2023-01-01',
    '"fix formula" ods committer-date:<2023-01-01',
    '"corrected formula" xls committer-date:<2023-01-01',
    '"formula bug" spreadsheet committer-date:<2023-01-01',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--query', action='append')
    parser.add_argument('--limit', type=int, default=24)
    args = parser.parse_args()
    if not args.name.replace('_', '').isalnum() or not 1 <= args.limit <= 40:
        parser.error('Use a simple receipt name and a detail limit from 1 to 40')
    raw = ROOT / 'source_evidence/raw' / args.name
    target = ROOT / 'source_evidence' / (args.name + '.json')
    if raw.exists() or target.exists():
        parser.error('Preserve existing search evidence; choose a new name')
    raw.mkdir(parents=True)

    def request(url, name):
        receipt = dict(url=url, acquired_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'HybridGuard-metadata-only-development-audit/1.0',
                'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(req, timeout=20) as response:
                body = response.read(5_000_001)
                receipt.update(http_status=response.status, resolved_url=response.url)
            if len(body) > 5_000_000:
                raise ValueError('metadata response exceeds size bound')
            with (raw / (name + '.json')).open('xb') as handle:
                handle.write(body)
            receipt.update(ok=True, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            return receipt, json.loads(body)
        except Exception as error:
            receipt.update(ok=False, error=f'{type(error).__name__}: {error}')
            return receipt, {}

    searches, candidates = [], {}
    for index, query in enumerate(args.query or QUERIES):
        receipt, payload = request('https://api.github.com/search/commits?' +
            urllib.parse.urlencode(dict(q=query, per_page=20)), f'query_{index}')
        receipt.update(query=query, total_count=payload.get('total_count'))
        searches.append(receipt)
        for item in payload.get('items', []):
            key = (item['repository']['full_name'], item['sha'])
            candidates[key] = dict(origin=key[0], sha=key[1], url=item['url'],
                                   message=item['commit']['message'])

    def detail(pair):
        index, row = pair
        receipt, payload = request(row['url'], f'commit_{index}')
        return dict(row, request=receipt,
            parents=[item['sha'] for item in payload.get('parents', [])],
            workbook_paths=[dict(path=item['filename'], status=item['status'],
                                 sha=item.get('sha'), previous_path=item.get('previous_filename'))
                for item in payload.get('files', [])
                if item['filename'].lower().endswith(('.xlsx', '.xlsm', '.xls', '.ods'))],
            workbook_bodies_acquired=False, truth_certified=False,
            final_validation_eligible=False)

    # Requests are I/O bound. This is not a model CPU scalability measurement.
    with ThreadPoolExecutor(max_workers=8) as pool:
        details = list(pool.map(detail, enumerate(list(candidates.values())[:args.limit])))
    result = dict(queries=searches, unique_search_hits=len(candidates), inspected=details,
        commits_with_workbook_changes=sum(bool(row['workbook_paths']) for row in details),
        accepted_natural_sources=0, accepted_final_sources=0,
        rule='Commit messages are leads only; all exposed origins are development-only. '
             'Pre-2023 filtering does not prove human authorship or correctness.')
    with target.open('x') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    print(json.dumps(dict(receipt=str(target), queries=len(searches),
        successful_queries=sum(row['ok'] for row in searches), unique_hits=len(candidates),
        inspected=len(details), commits_with_workbook_changes=result['commits_with_workbook_changes']), indent=2))
    for row in details:
        if row['workbook_paths']:
            print(json.dumps(dict(origin=row['origin'], sha=row['sha'],
                message=row['message'], workbook_paths=row['workbook_paths']), ensure_ascii=False))


if __name__ == '__main__':
    main()
