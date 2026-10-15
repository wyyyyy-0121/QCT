"""Official provenance/errata index discovery; do not read workbook fixes."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import datetime
import hashlib
import json
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'source_discovery/metadata_v4'
PAGES={
 'epa_manual':'https://www.epa.gov/economic-and-cost-analysis-air-pollution-regulations/cost-reports-and-guidance-air-pollution',
 'epa_disclaimers':'https://www.epa.gov/web-policies-and-procedures/epa-disclaimers',
 'renewables_license':'https://raw.githubusercontent.com/RenewablesPro/rvi-sample-models/1e49ec79613c77c3fa6f8532b4e303b473f85506/LICENSE',
 '18f_license':'https://api.github.com/repos/18F/financial-models/license?ref=d86e8f89145bb0e29cd7268e1497de45ddbae0c8',
 'nz_treasury_cba':'https://www.treasury.govt.nz/information-and-services/state-sector-leadership/investment-management/plan-investment-choices/cost-benefit-analysis-including-public-sector-discount-rates/treasurys-cbax-tool',
 'nz_treasury_copyright':'https://www.treasury.govt.nz/publications/copyright',
 'uk_aqua_book':'https://www.gov.uk/government/publications/the-aqua-book-guidance-on-producing-quality-analysis-for-government',
 'uk_webtag':'https://www.gov.uk/guidance/transport-analysis-guidance-tag',
 'nist_blcc':'https://www.nist.gov/services-resources/software/blcc',
 'uk_desnz_models':'https://www.gov.uk/government/publications/energy-generation-costs-2023',
 'doe_comcheck':'https://www.energycodes.gov/comcheck',
 'damodaran_terms':'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/biomission.htm',
}


class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.current={'href':dict(attrs).get('href',''),'text':''}
    def handle_data(self,data):
        if self.current:self.current['text']+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.current:
            self.links.append(self.current);self.current=None


def fetch(task):
    name,url=task;record={'name':name,'url':url,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'HybridGuard-provenance-audit/1.0'})
        with urllib.request.urlopen(req,timeout=18) as response:
            body=response.read(2_000_001);record.update(status=response.status,final_url=response.url)
        if len(body)>2_000_000:raise ValueError('page size limit')
        path=OUT/(name+'.source');path.write_bytes(body)
        record.update(ok=True,bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),path=str(path.relative_to(ROOT)))
        parser=Links();parser.feed(body.decode('utf-8',errors='replace'))
        record['potential_links']=[{'url':urllib.parse.urljoin(record['final_url'],x['href']),
            'text':' '.join(x['text'].split())} for x in parser.links
            if any(w in (x['href']+' '+x['text']).lower() for w in ['xls','spreadsheet','errat','copyright','licens','model','calculation'])]
    except Exception as e:record.update(ok=False,error=str(e))
    return record


def main():
    if OUT.exists():raise SystemExit('Preserve existing receipts')
    OUT.mkdir(parents=True)
    records=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row in pool.map(fetch,PAGES.items()):
            records.append(row);print(row['name'],row['ok'],row.get('error',''),len(row.get('potential_links',[])),flush=True)
    (OUT/'RECEIPT.json').write_text(json.dumps({'role':'metadata and terms only; no final workbooks or answers',
        'final_data_acquired':False,'records':records},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
