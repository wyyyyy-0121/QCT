"""Offline verification of metadata-only tree lineage and failed HEAD receipts."""
from pathlib import Path
import hashlib
import json
ROOT=Path(__file__).resolve().parents[1]


def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    natural=ROOT/'source_discovery/natural_commit_trees_dev25_20261018/RECEIPT.json'
    rr=ROOT/'source_discovery/rr_original_headers_dev25_20261018/RECEIPT.json'
    data=read(natural);assert data['prior_search_sha256']==sha(ROOT/'source_discovery/metadata_v3/RECEIPT.json')
    files=0
    for row in data['records']:
        assert row['metadata_complete'] and not row['workbook_blobs_acquired'] and not row['truth_pair_verified']
        assert len(row['evidence'])==4
        values={}
        for item in row['evidence']:
            path=ROOT/item['saved_path'];assert path.resolve().is_relative_to(ROOT)
            assert sha(path)==item['saved_sha256'] and path.stat().st_size==item['saved_bytes']
            assert item['status']==200 and '/git/' in item['url'] and '/blobs/' not in item['url']
            values[path.stem]=read(path);files+=1
        assert values['commit']['sha']==row['commit_sha'] and values['parent']['sha']==row['parent_sha']
        assert values['commit']['parents'][0]['sha']==row['parent_sha']
        assert values['commit']['tree']['sha']==values['after']['sha'] and values['parent']['tree']['sha']==values['before']['sha']
        for key in ['commit','parent']:assert set(values[key])=={'sha','tree','parents'}
        trees=[]
        for name in ['before','after']:
            assert not values[name]['truncated'] and set(values[name])=={'sha','tree','truncated'}
            trees.append({r['path']:r for r in values[name]['tree'] if r['type']=='blob' and Path(r['path']).suffix.lower() in ['.xlsx','.xlsm','.xls','.ods']})
        before,after=trees
        assert row['before_workbooks']==len(before) and row['after_workbooks']==len(after)
        assert row['added_workbook_paths']==sorted(after.keys()-before.keys()) and row['removed_workbook_paths']==sorted(before.keys()-after.keys())
        assert row['changed_workbook_paths']==[]
        assert all(before[p]['sha']==after[p]['sha'] for p in before.keys()&after.keys())
    head=read(rr);assert len(head['records'])==3 and not head['workbook_bodies_acquired']
    assert all(r['method']=='HEAD' and r['body_bytes_read']==0 and 'error' in r for r in head['records'])
    assert len(data['records'])==6 and files==24
    target=ROOT/'qa/NESTED_CALIBRATION_DEV25_SOURCE_METADATA_AUDIT_20261018.json';assert not target.exists()
    target.write_text(json.dumps(dict(metadata_files_verified=24,complete_revision_pairs=6,changed_same_path_workbooks=0,
        failed_HEAD_requests=3,workbook_bodies_acquired=False,natural_truth_pairs_verified=0,
        natural_receipt_sha256=sha(natural),head_receipt_sha256=sha(rr),auditor_sha256=sha(Path(__file__)),
        accepted_final_sources=0,accepted_final_families=0),ensure_ascii=False,indent=2)+'\n')
    print('Natural metadata verified: 24 files, 6 revision trees, 3 failed HEAD, no accepted truth pair',flush=True)


if __name__=='__main__':main()
