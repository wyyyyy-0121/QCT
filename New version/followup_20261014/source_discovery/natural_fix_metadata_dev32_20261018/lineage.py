from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import urllib.request,json,hashlib,datetime
OUT=Path(__file__).resolve().parent
specs=[('micro-solution/BPA','bc9918fa2947b5c3823fc782809dc67f68e5b16b','5d462b8ffa4e03a2eefe441b879bd23d52558e09','BPA/Business planning.xlsm'),('drjlevi6/Data-Scientist','c071cf71a81a7ba43a1cf4712c67a6925bfa52bf','6f52de87c8f30a46bc4be36b9cdc9206036d88a3','Linear Regression/Weights.xlsx')]
jobs=[]
for repo,after,before,file in specs:
 jobs.append((repo,'repo','https://api.github.com/repos/'+repo))
 for role,rev in [('before_tree',before),('after_tree',after)]:jobs.append((repo,role,'https://api.github.com/repos/'+repo+'/git/trees/'+rev+'?recursive=1'))
def fetch(job):
 repo,role,url=job;row=dict(repo=repo,role=role,url=url)
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'HybridGuard-provenance/1.0','Accept':'application/vnd.github+json'})
  with urllib.request.urlopen(req,timeout=25) as r:raw=r.read(5000001);row['status']=r.status
  assert len(raw)<=5000000
  dest=OUT/(repo.replace('/','__')+'_'+role+'.json');assert not dest.exists();dest.write_bytes(raw)
  row.update(path=dest.name,sha256=hashlib.sha256(raw).hexdigest())
 except Exception as e:row['error']=type(e).__name__+': '+str(e)
 print(row,flush=True);return row
with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(fetch,jobs))
candidates=[]
for repo,after,before,file in specs:
 prefix=repo.replace('/','__');row=dict(origin=repo,file=file,before_commit=before,after_commit=after,body_acquired=False,accepted=False)
 try:
  metadata=json.loads((OUT/(prefix+'_repo.json')).read_text());row.update(fork=metadata['fork'],parent=metadata.get('parent',{}).get('full_name'),license=(metadata.get('license') or {}).get('spdx_id'))
  for role in ['before','after']:
   tree=json.loads((OUT/(prefix+'_'+role+'_tree.json')).read_text());assert not tree.get('truncated')
   match=[x for x in tree['tree'] if x['path']==file];assert len(match)==1
   row[role+'_blob']=match[0]['sha'];row[role+'_bytes']=match[0].get('size')
  row['distinct_binary_versions']=row['before_blob']!=row['after_blob']
  row['remaining_gates']=['whole-origin historical overlap and related-template audit','freeze model and evaluation protocol before workbook/answer bodies','predict original and lock before correction version','literal OOXML formula/input diff and semantic certification','all proposals adjudicable and family deduplication']
 except Exception as e:row['error']=type(e).__name__+': '+str(e)
 candidates.append(row)
(OUT/'LINEAGE_RECEIPT.json').write_text(json.dumps(dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),records=records,candidates=candidates,workbook_bodies_acquired=0,labels_verified=False,accepted_final_sources=0,accepted_final_families=0),indent=2)+'\n')
print(candidates,flush=True)
