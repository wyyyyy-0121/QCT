"""Offline evidence checks for metadata discovery; not formula/label validation."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    pages = 0
    redactions = read(ROOT / 'PUBLICATION_REDACTIONS_20261018.json')['files']
    for row in redactions:
        assert sha(PROJECT / row['path']) == row['published_sha256']
    for version in range(2, 9):
        receipt = read(ROOT / f'expansion_20261018_v{version}/RECEIPT.json')
        index_version = 1 if version == 2 else version
        assert receipt['index_sha256'] == sha(ROOT / f'expansion_index_20261018_v{index_version}.json')
        assert receipt['script_sha256'] == sha(ROOT / 'expand_sources_20261018.py')
        for row in receipt['results']:
            assert row['workbook_acquired'] is False and row['accepted'] is False
            assert row['accepted_template_families'] == 0
            if 'sha256' in row:
                path = PROJECT / row['path']
                assert path.is_relative_to(ROOT) and sha(path) == row['sha256']
                data = path.read_bytes()
                assert not data.startswith((b'PK\x03\x04', b'\xd0\xcf\x11\xe0'))
                assert not re.search(rb'\b(?:sk|pk)\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}', data)
                pages += 1
    indexes = ['RESERVED_SOURCE_CANDIDATES_20261018.json',
               'RESERVED_ADDITIONAL_CANDIDATES_20261018.json',
               'RESERVED_TENNESSEE_CANDIDATES_20261018.json']
    files = [row for name in indexes for row in read(ROOT / name)['items']]
    assert len(files) == len({row['url'] for row in files}) == 45
    assert len({row['origin'] for row in files}) == 9
    by_id = {row['id']: row for row in files}
    assert len(by_id) == len(files)
    headers = []
    for name, index in zip(['CANDIDATE_HEADER_RECEIPT_20261018.json',
                            'ADDITIONAL_HEADER_RECEIPT_20261018.json',
                            'TENNESSEE_HEADER_RECEIPT_20261018.json'], indexes):
        receipt = read(ROOT / name)
        assert receipt['workbook_bodies_acquired'] == 0
        assert receipt['index_sha256'] == sha(ROOT / index)
        if 'script_sha256' in receipt:
            assert receipt['script_sha256'] == sha(ROOT / 'check_candidate_headers_20261018.py')
        if 'source_sha256' in receipt:
            for rel, expected in receipt['source_sha256'].items():
                assert sha(ROOT / rel) == expected
        if 'header_check_source_sha256' in receipt:
            assert receipt['header_check_source_sha256'] == sha(ROOT / 'check_candidate_headers_20261018.py')
        for row in receipt['results']:
            assert row['method'] == 'HEAD' and row['workbook_body_bytes_read'] == 0
            assert row['url'] == by_id[row['id']]['url']
        headers.extend(receipt['results'])
    fallback = read(ROOT / 'GET_HEADER_FALLBACK_RECEIPT_20261018.json')
    assert fallback['workbook_bodies_acquired'] == 0
    for row in fallback['results']:
        assert row['workbook_body_bytes_processed'] == 0
        assert row['url'] == by_id[row['id']]['url']
    successful = {row['origin'] for row in headers + fallback['results'] if row.get('status') == 200}
    six = {'Ohio State University', 'Washington State University', 'University of Arkansas',
           'Purdue University', 'Kansas State University', 'University of Tennessee'}
    assert six <= successful and len(successful) == 7
    ledger = read(ROOT / 'SOURCE_READINESS.json')
    assert ledger['accepted_sources'] == ledger['accepted_template_families'] == 0
    assert ledger['final_workbooks_acquired'] is False
    excluded = [x for x in ledger['priority_origin_groups'] if x.get('workbook_acquired')]
    assert len(excluded) == 7 and all(not x['final_validation_eligible'] for x in excluded)
    return {'metadata_pages_hashed_and_verified': pages,
            'public_site_token_redactions_verified': len(redactions),
            'reserved_unique_file_links': len(files), 'preliminary_origin_labels': 9,
            'head_requests': len(headers), 'get_header_only_requests': len(fallback['results']),
            'university_calculation_origins_with_successful_headers': sorted(six),
            'additional_successful_header_origin_formula_presence_unknown': 'IPCC TFI',
            'workbook_bodies_acquired': 0, 'previous_development_origins_still_excluded': 7,
            'final_sources_accepted': 0, 'final_template_families_accepted': 0,
            'business_labels_verified': False,
            'scope_limit': 'Checks stored metadata evidence and retrieval code; does not inspect formula bodies or prove independent template lineage'}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
