"""Verify metadata and HEAD receipts without opening reserved workbook bodies."""
from pathlib import Path
import base64
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def audit():
    files, pages, requests = set(), 0, 0
    for version in (11, 12, 13):
        index = ROOT/f'expansion_index_20261018_v{version}.json'
        receipt = ROOT/f'expansion_20261018_v{version}/RECEIPT.json'
        data = read(receipt)
        assert data['index_sha256'] == sha(index)
        assert data['script_sha256'] == sha(ROOT/'expand_sources_20261018.py')
        files.update((index,receipt))
        for row in data['results']:
            requests += 1
            assert row['workbook_acquired'] is False and row['accepted'] is False
            if 'path' in row:
                path = PROJECT/row['path']
                assert path.is_relative_to(ROOT)
                assert sha(path) == row['sha256']
                assert path.stat().st_size == row['bytes']
                assert not path.read_bytes().startswith((b'PK\x03\x04',b'\xd0\xcf\x11\xe0'))
                files.update((path,path.with_suffix('.txt')))
                pages += 1
    headers = []
    for index_name,receipt_name in [
            ('RESERVED_NEW_DOMAIN_NATURAL_LINKS_20261018.json','NEW_DOMAIN_NATURAL_HEADER_RECEIPT_20261018.json'),
            ('RESERVED_NSW_RR_PINNED_LINKS_20261018.json','NSW_RR_PINNED_HEADER_RECEIPT_20261018.json')]:
        index,receipt = ROOT/index_name,ROOT/receipt_name
        files.update((index,receipt))
        data = read(receipt)
        assert data['index_sha256'] == sha(index)
        assert data['workbook_bodies_acquired'] == data['answer_bodies_acquired'] == 0
        for name,expected in data['source_sha256'].items():
            assert sha(ROOT/name) == expected
            files.add(ROOT/name)
        links = {x['id']:x for x in read(index)['items']}
        assert len(links) == len(data['results'])
        for row in data['results']:
            assert row['method'] == 'HEAD' and row['workbook_body_bytes_read'] == 0
            assert row['url'] == links[row['id']]['url']
            headers.append(row)
    patterns = {
        'mapbox_like':rb'\b(?:sk|pk)\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}',
        'github_token':rb'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})',
        'aws_access_key':rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
        'openai_project_key':rb'\bsk-proj-[A-Za-z0-9_-]{20,}',
        'private_key':rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'}
    findings = []
    for path in sorted(files):
        raw = path.read_bytes()
        payloads = [raw]
        try:
            data = json.loads(raw)
            if isinstance(data,dict) and data.get('encoding') == 'base64':
                payloads.append(base64.b64decode(data['content']))
        except (ValueError,KeyError):
            pass
        for payload in payloads:
            for label,pattern in patterns.items():
                count = len(re.findall(pattern,payload))
                if count:
                    findings.append({'path':str(path.relative_to(PROJECT)),
                                     'pattern':label,'count':count})
    assert not findings, 'Potential credential patterns; values omitted'
    ledger = read(ROOT/'SOURCE_READINESS.json')
    assert ledger['accepted_sources'] == ledger['accepted_template_families'] == 0
    assert not ledger['final_workbooks_acquired']
    return {
        'role':'offline evidence integrity only; not formula, truth, or lineage acceptance',
        'metadata_requests':requests,'saved_response_hashes_verified':pages,
        'head_requests':len(headers),'successful_head_requests':sum(r.get('status')==200 for r in headers),
        'files_pattern_scanned':len(files),'credential_pattern_findings':findings,
        'reserved_workbook_bodies_acquired':0,'correction_answer_bodies_acquired':0,
        'accepted_final_sources':0,'accepted_final_template_families':0,
        'audit_script_sha256':sha(Path(__file__)),
        'files_sha256':{str(p.relative_to(PROJECT)):sha(p) for p in sorted(files)}}


if __name__ == '__main__':
    result = audit()
    output = PROJECT/'qa/SOURCE_EXPANSION_V11_V13_AUDIT_20261018.json'
    with output.open('x') as handle:
        json.dump(result,handle,indent=2)
        handle.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='files_sha256'},indent=2))
