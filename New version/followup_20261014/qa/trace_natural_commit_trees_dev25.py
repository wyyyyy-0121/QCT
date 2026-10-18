"""Trace candidate bug-fix revisions through Git metadata, never workbook blobs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import datetime
import hashlib
import json
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'source_discovery/natural_commit_trees_dev25_20261018'
TARGETS=[
    ('mightyoung/software-cost-calculator','ce9fd3f00fa2819630e0bd9d7129889211aea525'),
    ('zbynekdrlik/vyuctovanie','a1c874b3bba1d2703adb9523617f572b1c848ea4'),
    ('reckak/statistics-for-psychology','00e3b5d2e27600fd33b6fbc5034be38e79564368'),
    ('Pradeepgdeepu/Data_Cleaning_with_excel','f784663dad6c0ced6a403bad5c33f73789e504af'),
    ('alvenyuka/Stock-Portfolio-Tracker-Analytics-Engine','07d43c117259ce611d0fad1062a2785f6896ca96'),
    ('OpenSourceRisk/QuantLibAddIn','ce2e7a11793e98010d8d2603e71c584500ebdfaa'),
]


def fetch(repo,kind,sha,folder,name):
    assert kind in ('commits','trees')
    url='https://api.github.com/repos/'+repo+'/git/'+kind+'/'+sha+('?recursive=1' if kind=='trees' else '')
    req=urllib.request.Request(url,headers={'User-Agent':'HybridGuard-provenance-metadata/1.0','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=18) as response:
        raw=response.read(5_000_001);status=response.status
    if len(raw)>5_000_000:raise ValueError('metadata size budget exceeded')
    value=json.loads(raw)
    # Discard commit messages and authors: lineage needs only immutable tree
    # and parent IDs, never correction text or workbook contents.
    if kind=='commits':filtered={k:value[k] for k in ['sha','tree','parents']}
    else:filtered={k:value[k] for k in ['sha','tree','truncated']}
    path=folder/(name+'.json');path.write_text(json.dumps(filtered,ensure_ascii=False,indent=2)+'\n')
    return filtered,dict(url=url,status=status,response_bytes=len(raw),saved_path=str(path.relative_to(ROOT)),
        saved_bytes=path.stat().st_size,saved_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def trace(target):
    repo,sha=target;folder=OUT/repo.replace('/','__');folder.mkdir()
    result=dict(repo=repo,commit_sha=sha,evidence=[],workbook_blobs_acquired=False,truth_pair_verified=False)
    try:
        commit,receipt=fetch(repo,'commits',sha,folder,'commit');result['evidence'].append(receipt)
        if len(commit['parents'])!=1:raise ValueError('single-parent correction candidate required')
        parent,receipt=fetch(repo,'commits',commit['parents'][0]['sha'],folder,'parent');result['evidence'].append(receipt)
        result['parent_sha']=parent['sha']
        trees=[]
        for label,tree_sha in [('before',parent['tree']['sha']),('after',commit['tree']['sha'])]:
            tree,receipt=fetch(repo,'trees',tree_sha,folder,label);result['evidence'].append(receipt)
            if tree['truncated']:raise ValueError('truncated tree cannot establish complete candidate list')
            trees.append({r['path']:r for r in tree['tree'] if r['type']=='blob' and Path(r['path']).suffix.lower() in ('.xlsx','.xlsm','.xls','.ods')})
        before,after=trees
        result.update(before_workbooks=len(before),after_workbooks=len(after),
            changed_workbook_paths=[dict(path=p,before_sha=before[p]['sha'],after_sha=after[p]['sha'],
                before_bytes=before[p].get('size'),after_bytes=after[p].get('size')) for p in sorted(before.keys()&after.keys()) if before[p]['sha']!=after[p]['sha']],
            added_workbook_paths=sorted(after.keys()-before.keys()),removed_workbook_paths=sorted(before.keys()-after.keys()),metadata_complete=True)
    except Exception as e:result.update(metadata_complete=False,error=type(e).__name__+': '+str(e))
    print(repo,result.get('metadata_complete'),len(result.get('changed_workbook_paths',[])),result.get('error',''),flush=True)
    return result


def main():
    if OUT.exists():raise SystemExit('Preserve natural revision metadata')
    OUT.mkdir(parents=True)
    old=ROOT/'source_discovery/metadata_v3/RECEIPT.json';discovered=json.loads(old.read_text())
    prior={(r['repo'],r['sha']) for b in discovered['records'] for r in b.get('candidates',[])}
    assert set(TARGETS)<=prior
    with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(trace,TARGETS))
    receipt=dict(role='Pinned lineage metadata from earlier search; no workbook, patch or cell-answer acquisition',
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),prior_search_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),
        records=rows,accepted_sources=0,accepted_families=0,natural_truth_pairs_verified=0)
    (OUT/'RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
