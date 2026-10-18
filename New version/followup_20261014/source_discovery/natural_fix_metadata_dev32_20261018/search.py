from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import datetime, hashlib, json, urllib.parse, urllib.request
OUT=Path(__file__).resolve().parent
QUERIES=['"wrong formula" "xlsx" committer-date:<2024-01-01',
         '"fix formula" "xlsm" committer-date:<2024-01-01',
         '"formula error" "spreadsheet" committer-date:<2024-01-01',
         '"correct formula" "xlsx" committer-date:<2024-01-01']
def one(pair):
 n,q=pair;url='https://api.github.com/search/commits?'+urllib.parse.urlencode(dict(q=q,per_page=25))
 row=dict(query=q,url=url,workbook_bodies_acquired=False)
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'HybridGuard-natural-provenance/1.0','Accept':'application/vnd.github+json'})
  with urllib.request.urlopen(req,timeout=25) as r:
   raw=r.read(3000001);row.update(status=r.status,remaining=r.headers.get('X-RateLimit-Remaining'))
  assert len(raw)<=3000000
  data=json.loads(raw)
  saved=dict(total_count=data['total_count'],incomplete_results=data['incomplete_results'],candidates=[dict(repo=x['repository']['full_name'],sha=x['sha'],url=x['html_url'],message=x['commit']['message'],parents=[p['sha'] for p in x['parents']]) for x in data['items']])
  path=OUT/f'search_{n}.json';assert not path.exists();path.write_text(json.dumps(saved,indent=2)+'\n')
  row.update(ok=True,response_bytes=len(raw),result_path=path.name,result_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),total_count=saved['total_count'],returned=len(saved['candidates']))
 except Exception as e:row.update(ok=False,error=type(e).__name__+': '+str(e))
 print(n,row,flush=True);return row
with ThreadPoolExecutor(max_workers=2) as pool: rows=list(pool.map(one,enumerate(QUERIES,1)))
receipt=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),method='commit provenance metadata only; commit messages are not verified formula labels',queries=rows,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),workbook_bodies_acquired=0,accepted_final_sources=0,accepted_final_families=0)
(OUT/'RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
