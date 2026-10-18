"""HEAD-only availability checks for unresolved RR original input provenance."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import datetime
import json
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'source_discovery/rr_original_headers_dev25_20261018'
URLS={
    'dropbox_original_download':'https://www.dropbox.com/s/aw3yb8u2mvr599p/Reinhart%20and%20Rogoff.xlsx?dl=1',
    'dropbox_content_original':'https://dl.dropboxusercontent.com/s/aw3yb8u2mvr599p/Reinhart%20and%20Rogoff.xlsx',
    'pinned_science_replication':'https://raw.githubusercontent.com/scienceetonnante/Reinhart-Rogoff/658bfafcfe19878cf13ffa748d3e5ab8c1969f6b/RR.xlsx',
}


def probe(item):
    key,url=item;record=dict(id=key,url=url,method='HEAD',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),body_bytes_read=0)
    try:
        req=urllib.request.Request(url,method='HEAD',headers={'User-Agent':'HybridGuard-provenance-metadata/1.0'})
        with urllib.request.urlopen(req,timeout=18) as response:
            record.update(status=response.status,final_url=response.url,
                headers={k:response.headers.get(k) for k in ['Content-Type','Content-Length','ETag','Last-Modified','Content-Disposition']})
    except Exception as e:record.update(error=type(e).__name__+': '+str(e))
    return record


def main():
    if OUT.exists():raise SystemExit('Preserve metadata receipt')
    OUT.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=3) as pool:records=list(pool.map(probe,URLS.items()))
    result=dict(role='HEAD-only provenance availability; not workbook acquisition, truth pairing or source acceptance',
        origin='Reinhart Rogoff historical case; Dropbox and mirrors one origin',records=records,
        original_and_correction_pair_verified=False,workbook_bodies_acquired=False,accepted_sources=0,accepted_families=0)
    (OUT/'RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for row in records:print(row['id'],row.get('status'),row.get('error',''),flush=True)


if __name__=='__main__':main()
