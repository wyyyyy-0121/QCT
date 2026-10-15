"""Discover provenance and potential natural bug-fix pairs, metadata only.

Do not download workbooks, patches or correct formulas before model freeze.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'source_discovery/metadata_v3'
TASKS={
 '18f_readme':'https://raw.githubusercontent.com/18F/financial-models/d86e8f89145bb0e29cd7268e1497de45ddbae0c8/README.md',
 'packt_license':'https://raw.githubusercontent.com/PacktPublishing/Project-Finance-and-Excel---Build-Financial-Models-from-Scratch/618787e67a7ee0e6643f60ef447a9c35d6ee9301/LICENSE',
 'renewables_readme':'https://raw.githubusercontent.com/RenewablesPro/rvi-sample-models/1e49ec79613c77c3fa6f8532b4e303b473f85506/README.md',
 'damodaran_directory':'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/spreadsh.htm',
 'epa_cost_manual':'https://www.epa.gov/economic-and-cost-analysis-air-pollution-regulations/cost-reports-and-guidance-air-pollution',
 'uk_greenbook_supplement':'https://www.gov.uk/government/publications/green-book-supplementary-guidance-discounting',
}
QUERIES=['"fix formula" xlsx','"incorrect formula" excel',
         '"fix spreadsheet" xlsx','"formula error" workbook',
         '"fix" "xlsx" "calculation"','"spreadsheet" "wrong formula"']


def fetch(task):
    name,url=task;record={'name':name,'url':url,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'HybridGuard-provenance-audit','Accept':'application/vnd.github+json' if 'api.github.com' in url else '*/*'})
        with urllib.request.urlopen(req,timeout=18) as response:
            body=response.read(3_000_001);record.update(status=response.status,final_url=response.url)
        if len(body)>3_000_000:raise ValueError('metadata size limit')
        suffix='.json' if 'api.github.com' in url else '.txt'
        path=OUT/(name+suffix);path.write_bytes(body)
        record.update(ok=True,bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),path=str(path.relative_to(ROOT)))
        if name.startswith('commits_'):
            result=json.loads(body)
            record['total_count']=result.get('total_count')
            record['candidates']=[{'repo':r['repository']['full_name'],'sha':r['sha'],
                'url':r['html_url'],'message':r['commit']['message'][:1800]} for r in result.get('items',[])]
    except Exception as e:record.update(ok=False,error=str(e))
    return record


def main():
    if OUT.exists():raise SystemExit('metadata_v3 already exists; preserve old receipts')
    OUT.mkdir(parents=True)
    tasks=list(TASKS.items())+[(f'commits_{i}','https://api.github.com/search/commits?q='+urllib.parse.quote(q)+'&per_page=15') for i,q in enumerate(QUERIES)]
    records=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for record in pool.map(fetch,tasks):
            records.append(record)
            print(record['name'],record['ok'],record.get('error',''),flush=True)
            for item in record.get('candidates',[]):print(item['repo'],item['sha'][:10],item['message'].splitlines()[0],flush=True)
    (OUT/'RECEIPT.json').write_text(json.dumps({'role':'metadata discovery only; no accepted final source or truth pair',
        'workbooks_downloaded':False,'records':records},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
