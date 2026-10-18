"""Pin five domain-workbook correction candidates found by historical search."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import datetime
import hashlib
import json
import trace_natural_commit_trees_dev25 as lineage

ROOT = Path(__file__).resolve().parents[1]
SEARCH = ROOT / 'source_discovery/historical_fix_search_dev25_20261018'
OUT = ROOT / 'source_discovery/historical_fix_lineage_dev25_20261018'
TARGETS = [
    ('ECB2020/Hobyah', 'a6c7cd441ff1aca4915e8bc2b61d719643927cac'),
    ('CASPER-Baylor/VDRIAD', '220061c408beb0b2b9c7d686d4431a36e1d7bc56'),
    ('mirontoli/cv-500', '48a359e080afb4d793994be3da225d509a683b73'),
    ('Gh0st0ne/LDAS', 'f15063f13cbbaab00cd77414a11a1e8f8a6756ed'),
    ('New-College-of-Florida/Planned-Parenthood-Drug-Inventory',
     'd7f90d19dc8dd65e3fd352acee7406453af413a3'),
]


def main():
    if OUT.exists():
        raise SystemExit('Preserve historical lineage evidence')
    receipt = json.loads((SEARCH / 'RECEIPT.json').read_text())
    discovered = set()
    for row in receipt['records']:
        if not row['ok']:
            continue
        path = ROOT / row['saved_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['saved_sha256']
        discovered.update((r['repo'], r['sha']) for r in json.loads(path.read_text())['candidates'])
    assert set(TARGETS) <= discovered
    OUT.mkdir(parents=True)
    # Reuse the body-free /git/commits and /git/trees client, not the API
    # endpoint returning file patches. Save evidence in this separate run.
    lineage.OUT = OUT
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lineage.trace, TARGETS))
    data = dict(role='Pinned historical correction lineage; no workbook or patch acquisition',
                utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), records=rows,
                search_receipt_sha256=hashlib.sha256((SEARCH / 'RECEIPT.json').read_bytes()).hexdigest(),
                script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                lineage_client_sha256=hashlib.sha256(Path(lineage.__file__).read_bytes()).hexdigest(),
                accepted_sources=0, accepted_families=0, verified_natural_truth_pairs=0)
    (OUT / 'RECEIPT.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
