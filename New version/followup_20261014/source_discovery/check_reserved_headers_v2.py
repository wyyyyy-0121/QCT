"""HEAD-only availability checks for a separately saved reserved-link index."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json

from check_candidate_headers_20261018 import check


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('index', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Preserve prior evidence; choose a new output')
    items = json.loads(args.index.read_text())['items']
    assert len({x['id'] for x in items}) == len(items)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(check, items))
    rows = [{**item, **row} for item, row in zip(items, rows)]
    receipt = {
        'method': 'HEAD only; no workbook, archive, or answer body read',
        'workbook_bodies_acquired': 0,
        'answer_bodies_acquired': 0,
        'accepted_final_sources': 0,
        'accepted_final_template_families': 0,
        'index_sha256': hashlib.sha256(args.index.read_bytes()).hexdigest(),
        'source_sha256': {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), Path(__file__).with_name('check_candidate_headers_20261018.py'))
        },
        'results': rows,
    }
    with args.output.open('x') as output:
        json.dump(receipt, output, indent=2)
        output.write('\n')
    for row in rows:
        print(row['id'], row.get('status'), row.get('content_type'),
              row.get('error', ''), flush=True)


if __name__ == '__main__':
    main()
