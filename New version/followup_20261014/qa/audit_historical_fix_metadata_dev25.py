"""Reconstruct pinned workbook-path changes from saved historical Git trees."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
SEARCH = ROOT / 'source_discovery/historical_fix_search_dev25_20261018'
LINEAGE = ROOT / 'source_discovery/historical_fix_lineage_dev25_20261018'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    search = read(SEARCH / 'RECEIPT.json')
    assert search['script_sha256'] == sha(ROOT / 'qa/search_historical_workbook_fixes_dev25.py')
    assert not search['workbook_bodies_acquired']
    discovered = set(); incomplete_queries = []
    for row in search['records']:
        if row['ok']:
            path = ROOT / row['saved_path']
            assert sha(path) == row['saved_sha256']
            data = read(path)
            # Search completeness is not required to verify an individually
            # pinned hit. Preserve this limitation rather than treating the
            # first page as an exhaustive historical census.
            if data['incomplete_results']:
                incomplete_queries.append(row['query'])
            assert len(data['candidates']) == row['returned_candidates']
            discovered.update((r['repo'], r['sha']) for r in data['candidates'])
    lineage = read(LINEAGE / 'RECEIPT.json')
    assert lineage['search_receipt_sha256'] == sha(SEARCH / 'RECEIPT.json')
    assert lineage['script_sha256'] == sha(ROOT / 'qa/trace_historical_fix_lineage_dev25.py')
    assert lineage['lineage_client_sha256'] == sha(ROOT / 'qa/trace_natural_commit_trees_dev25.py')
    changes = []; requests = 0
    for row in lineage['records']:
        assert (row['repo'], row['commit_sha']) in discovered
        assert not row['workbook_blobs_acquired'] and not row['truth_pair_verified']
        for evidence in row['evidence']:
            assert evidence['status'] == 200
            assert '/git/commits/' in evidence['url'] or '/git/trees/' in evidence['url']
            path = ROOT / evidence['saved_path']
            assert sha(path) == evidence['saved_sha256'] and path.stat().st_size == evidence['saved_bytes']
            requests += 1
        if not row['metadata_complete']:
            continue
        folder = LINEAGE / row['repo'].replace('/', '__')
        commit = read(folder / 'commit.json'); parent = read(folder / 'parent.json')
        assert len(commit['parents']) == 1
        assert commit['sha'] == row['commit_sha']
        assert commit['parents'][0]['sha'] == parent['sha'] == row['parent_sha']
        trees = []
        for label, expected in [('before', parent['tree']['sha']), ('after', commit['tree']['sha'])]:
            tree = read(folder / (label + '.json'))
            assert not tree['truncated'] and tree['sha'] == expected
            trees.append({r['path']: r for r in tree['tree'] if r['type'] == 'blob'
                          and Path(r['path']).suffix.lower() in ('.xlsx', '.xlsm', '.xls', '.ods')})
        before, after = trees
        rebuilt = [dict(path=p, before_sha=before[p]['sha'], after_sha=after[p]['sha'],
                        before_bytes=before[p].get('size'), after_bytes=after[p].get('size'))
                   for p in sorted(before.keys() & after.keys()) if before[p]['sha'] != after[p]['sha']]
        assert rebuilt == row['changed_workbook_paths']
        assert len(before) == row['before_workbooks'] and len(after) == row['after_workbooks']
        assert sorted(after.keys() - before.keys()) == row['added_workbook_paths']
        assert sorted(before.keys() - after.keys()) == row['removed_workbook_paths']
        changes.append(dict(repo=row['repo'], changed_workbooks=len(rebuilt),
                            before_workbooks=len(before), after_workbooks=len(after)))
    for receipt in [search, lineage]:
        assert receipt['accepted_sources'] == receipt['accepted_families'] == receipt['verified_natural_truth_pairs'] == 0
    target = ROOT / 'qa/NESTED_CALIBRATION_DEV25_HISTORICAL_METADATA_AUDIT_20261018.json'
    assert not target.exists()
    result = dict(all_saved_metadata_hashes_and_lineage_verified=True,
                  independent_workbook_path_changes=changes, successful_lineage_requests=requests,
                  incomplete_search_queries=incomplete_queries, exhaustive_search_claimed=False,
                  search_receipt_sha256=sha(SEARCH / 'RECEIPT.json'),
                  lineage_receipt_sha256=sha(LINEAGE / 'RECEIPT.json'),
                  auditor_sha256=sha(Path(__file__)), workbook_bodies_acquired=False,
                  accepted_sources=0, accepted_families=0, verified_natural_truth_pairs=0)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('Historical metadata independently verified', changes, flush=True)


if __name__ == '__main__':
    main()
