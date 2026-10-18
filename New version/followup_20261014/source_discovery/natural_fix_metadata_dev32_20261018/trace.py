from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import urllib.request,json,hashlib,datetime
OUT=Path(__file__).resolve().parent
wanted={'micro-solution/BPA','drjlevi6/Data-Scientist','alexandredesousa/everis_python_exercise','ajohns30/ECS101PROJ2'}
items={}
for path in OUT.glob('search_*.json'):
 for row in json.loads(path.read_text())['candidates']:
  if row['repo'] in wanted:items[row['repo'],row['sha']]=row
def trace(row):
 url='https://api.github.com/repos/'+row['repo']+'/commits/'+row['sha']
 result=dict(repo=row['repo'],sha=row['sha'],url=url,workbook_bodies_acquired=False)
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'HybridGuard-provenance/1.0','Accept':'application/vnd.github+json'})
  with urllib.request.urlopen(req,timeout=25) as r:raw=r.read(3000001);result['status']=r.status
  assert len(raw)<=3000000
  obj=json.loads(raw)
  # Store commit metadata including text patches; never retrieve linked binaries.
  dest=OUT/('commit_'+row['repo'].replace('/','__')+'.json');assert not dest.exists();dest.write_bytes(raw)
  result.update(path=dest.name,sha256=hashlib.sha256(raw).hexdigest(),date=obj['commit']['committer']['date'],parents=[p['sha'] for p in obj['parents']],files=[dict(filename=f['filename'],status=f['status'],previous_filename=f.get('previous_filename'),raw_url=f.get('raw_url'),changes=f.get('changes')) for f in obj.get('files',[])])
 except Exception as e:result['error']=type(e).__name__+': '+str(e)
 print(result,flush=True);return result
with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(trace,items.values()))
(OUT/'TRACE_RECEIPT.json').write_text(json.dumps(dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),records=rows,workbook_bodies_acquired=0,labels_verified=False,accepted_final_sources=0,accepted_final_families=0),indent=2)+'\n')
