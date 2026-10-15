"""Receipt-backed index audit only; never download workbooks or formula labels.

No linked documents are fetched. A linked URL proves discoverability only, not
license, formula presence, historical correctness, independence or family count.
"""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
import datetime
import hashlib
import json
import re
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'source_discovery/index_audit_20261015'
PAGES={
    'iowa_index':('iowa_state_agdm','https://www.extension.iastate.edu/agdm/decisiontools.html'),
    'nlr_index':('nlr_jedi','https://www.nlr.gov/analysis/jedi'),
    'nlr_models':('nlr_jedi','https://www.nlr.gov/analysis/jedi/models'),
    'damodaran_index':('damodaran','https://pages.stern.nyu.edu/~adamodar/New_Home_Page/spreadsh.htm'),
    'epa_index':('epa','https://www.epa.gov/economic-and-cost-analysis-air-pollution-regulations/cost-reports-and-guidance-air-pollution'),
    'epa_terms':('epa','https://www.epa.gov/web-policies-and-procedures/epa-disclaimers'),
    'uk_tag_index':('uk_government','https://www.gov.uk/government/publications/tag-data-book'),
    'uk_lcoe_index':('uk_government','https://www.gov.uk/government/publications/electricity-generation-costs-2023'),
    '18f_pinned_tree':('18f','https://api.github.com/repos/18F/financial-models/git/trees/d86e8f89145bb0e29cd7268e1497de45ddbae0c8?recursive=1'),
    'packt_pinned_tree':('packt','https://api.github.com/repos/PacktPublishing/Project-Finance-and-Excel---Build-Financial-Models-from-Scratch/git/trees/618787e67a7ee0e6643f60ef447a9c35d6ee9301?recursive=1'),
    'renewables_pinned_tree':('renewables','https://api.github.com/repos/RenewablesPro/rvi-sample-models/git/trees/1e49ec79613c77c3fa6f8532b4e303b473f85506?recursive=1'),
}


def workbook_url(url):
    return bool(re.search(r'\.(xlsx|xlsm|xls|xlsb|ods)$', unquote(urlsplit(url).path),re.I))


class Links(HTMLParser):
    def __init__(self,base):
        super().__init__(convert_charrefs=True);self.base=base;self.links=[];self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            attr=dict(attrs)
            if attr.get('href'):self.current={'url':urljoin(self.base,attr['href']),'text':''}
    def handle_data(self,data):
        if self.current is not None:self.current['text']+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:
            self.current['text']=' '.join(self.current['text'].split())
            self.links.append(self.current);self.current=None


def fetch(item):
    name,(origin,url)=item
    assert not workbook_url(url)
    row={'name':name,'origin':origin,'url':url,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'linked_documents_fetched':False,'business_labels_read':False}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'HybridGuardResearchMetadataAudit/1.0','Accept':'text/html, application/json'})
        with urllib.request.urlopen(req,timeout=20) as response:
            final=response.geturl();ctype=response.headers.get('Content-Type','')
            # Reject redirects to binary downloads before reading their body.
            if workbook_url(final) or not any(v in ctype.lower() for v in ['text/','json']):
                row.update(status='rejected_non_index_response',final_url=final,content_type=ctype);return row
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('index_response_too_large')
            if raw.startswith((b'PK\x03\x04',b'\xd0\xcf\x11\xe0')):raise ValueError('index_response_is_binary')
            row.update(status=response.status,final_url=final,content_type=ctype,
                       bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        target=OUT/'pages'/(name+'.source');target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw);row['path']=str(target.relative_to(ROOT))
        if 'json' in ctype:
            tree=json.loads(raw);row['tree_truncated']=tree.get('truncated',False)
            row['workbook_paths']=[{'path':v['path'],'git_blob_sha':v['sha'],'bytes':v.get('size')}
                for v in tree.get('tree',[]) if v.get('type')=='blob' and workbook_url(v['path'])]
            row['workbook_link_count']=len(row['workbook_paths'])
        else:
            parser=Links(final);parser.feed(raw.decode('utf-8',errors='replace'))
            unique={v['url']:v for v in parser.links}
            row['workbook_links']=[v for k,v in sorted(unique.items()) if workbook_url(k)]
            row['workbook_link_count']=len(row['workbook_links'])
            row['terms_links']=[v for k,v in sorted(unique.items())
                if re.search(r'copyright|licen[cs]|terms|disclaimer|reuse',k+' '+v['text'],re.I)]
            row['revision_or_model_index_links']=[v for k,v in sorted(unique.items())
                if re.search(r'revision|errat|archive|correction|jedi/models',k+' '+v['text'],re.I)
                and not workbook_url(k)]
    except Exception as exc:
        row.update(status='fetch_failed',error=type(exc).__name__+': '+str(exc))
    return row


def main():
    if OUT.exists():raise SystemExit('Preserve receipt; choose a new audit directory')
    OUT.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(fetch,PAGES.items()))
    groups={}
    for row in rows:
        g=groups.setdefault(row['origin'],{'index_pages':[],'linked_workbook_urls_or_paths':0,'accepted':False})
        g['index_pages'].append(row['name']);g['linked_workbook_urls_or_paths']+=row.get('workbook_link_count',0)
    result={'role':'source metadata only; not final data acquisition or acceptance',
            'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'pages':rows,'origin_groups':groups,'final_workbook_bodies_acquired':False,
            'correct_formula_answers_acquired':False,'accepted_sources':0,'accepted_template_families':0,
            'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'limits':['URL/path counts are not independent family counts.',
                      'Origin history/ancestry, license scope and complete proposal truth remain unverified.',
                      'Old erroneous and corrected versions must still be paired after model freeze.',
                      'No linked workbook or erratum document body is downloaded.']}
    (OUT/'RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for row in rows:print(row['name'],row['status'],'linked_workbooks',row.get('workbook_link_count',0),row.get('error',''))
    print('Metadata origin groups with links:',sum(v['linked_workbook_urls_or_paths']>0 for v in groups.values()))


if __name__=='__main__':main()
