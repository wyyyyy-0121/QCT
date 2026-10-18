"""Capture public source metadata only; never acquire candidate workbooks.

No source/template is accepted by this discovery tool. HTTP 200 challenge pages
and directory titles are not evidence of usable datasets or formula labels.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

ROOT = Path(__file__).resolve().parent
LIMIT = 2_000_000
BINARY = re.compile(r'\.(?:xls[xmb]?|ods|zip|7z|rar|pdf)(?:$|[?#])', re.I)


def capture(item, out):
    entry = {**item, 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'workbook_acquired': False, 'accepted': False,
             'accepted_template_families': 0}
    if BINARY.search(item['url']):
        return {**entry, 'error': 'Binary URL rejected before request'}
    try:
        with requests.get(item['url'], timeout=(12, 30), stream=True,
                          headers={'User-Agent': 'HybridGuard-research/metadata-only'}) as response:
            kind = response.headers.get('Content-Type', '')
            entry.update(status=response.status_code, resolved_url=response.url,
                         content_type=kind)
            if BINARY.search(response.url) or not any(x in kind for x in ('html', 'text/plain', 'json')):
                return {**entry, 'body_read': False, 'error': 'Nonmetadata response body rejected'}
            chunks = bytearray()
            for part in response.iter_content(16384):
                chunks.extend(part)
                if len(chunks) > LIMIT:
                    return {**entry, 'body_read': False, 'error': 'Metadata size limit exceeded'}
        raw = bytes(chunks)
        path = out / 'pages' / (item['id'] + '.source')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        soup = BeautifulSoup(raw, 'html.parser')
        title = soup.title.get_text(' ', strip=True) if soup.title else None
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()
        text = soup.get_text(' ', strip=True)
        links = []
        seen = set()
        for anchor in soup.select('a[href]'):
            url = urljoin(response.url, anchor['href'])
            if url in seen or urlparse(url).scheme not in ('http', 'https'):
                continue
            seen.add(url)
            label = anchor.get_text(' ', strip=True)
            if (BINARY.search(url) or re.search(
                    r'budget|spreadsheet|excel|calculator|model|tool|errat|correct|revision|license|copyright|terms',
                    label + ' ' + url, re.I)):
                links.append({'text': label, 'url': url,
                              'workbook_link': bool(re.search(r'\.(?:xls[xmb]?|ods)(?:$|[?#])', url, re.I))})
        snippets = []
        for match in re.finditer(r'(?i)\b(?:formula|errata|corrected|correction|revision|spreadsheet|excel|copyright|license)\b', text):
            snippets.append(text[max(0, match.start()-140):match.end()+320])
        entry.update(body_read=True, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                     path=str(path.relative_to(ROOT.parent)), title=title,
                     text_characters=len(text), relevant_links=links,
                     snippets=snippets[:100],
                     challenge_suspected=bool(re.search(r'captcha|Incapsula|Access Denied|Just a moment|verify you are human',
                                                       raw.decode('utf-8', errors='replace'), re.I)))
        (out / 'pages' / (item['id'] + '.txt')).write_text(text)
    except Exception as error:
        entry.update(error=type(error).__name__ + ': ' + str(error))
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('index', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output.exists():
        raise SystemExit('Preserve existing discovery evidence; select a new output')
    items = json.loads(args.index.read_text())
    assert len({x['id'] for x in items}) == len(items)
    args.output.mkdir(parents=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(capture, item, args.output): item for item in items}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(result['id'], result.get('status'), result.get('title'),
                  'workbook links', sum(x['workbook_link'] for x in result.get('relevant_links', [])),
                  result.get('error', ''), flush=True)
    receipt = {'role': 'Metadata discovery only; no candidate workbook bodies or answer files fetched',
               'accepted_final_sources': 0, 'accepted_final_template_families': 0,
               'index_sha256': hashlib.sha256(args.index.read_bytes()).hexdigest(),
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'results': sorted(results, key=lambda x: x['id'])}
    (args.output / 'RECEIPT.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
