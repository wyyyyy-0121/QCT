#!/usr/bin/env python3
"""Acquire original author evidence without redistributing third-party files."""
from __future__ import annotations
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / 'source_evidence' / 'enron_info1'
RAW = OUT / 'private'

def main():
    RAW.mkdir(parents=True, exist_ok=True)
    (OUT / '.gitignore').write_text('private/\n')
    urls = {
        'enron_author_index.html': 'https://ls13-www.cs.tu-dortmund.de/homepage/spreadsheets/enron-errors-files/sheet001.htm',
        'enron_author.zip': 'https://ls13-www.cs.tu-dortmund.de/homepage/spreadsheets/enron-errors.zip',
        'info1_thesis.pdf': 'https://spreadsheets.sai.tugraz.at/wp-content/uploads/sites/3/2015/05/DA_Final.pdf',
    }
    receipts = []
    for name, url in urls.items():
        target = RAW / name
        row = {'url': url, 'path': str(target.relative_to(ROOT)),
               'acquired_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'final_validation_eligible': False, 'redistribution_authorized': False}
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                data = response.read()
                row.update(http_status=response.status, resolved_url=response.url,
                           last_modified=response.headers.get('Last-Modified'))
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError('Refusing to overwrite different prior evidence')
            target.write_bytes(data)
            row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), ok=True)
        except Exception as error:
            row.update(ok=False, error=repr(error))
        receipts.append(row)
    (OUT / 'ACQUISITION.json').write_text(json.dumps(receipts, indent=2) + '\n')
    if not all(r['ok'] for r in receipts):
        raise SystemExit('Acquisition incomplete; inspect receipt')
    with zipfile.ZipFile(RAW / 'enron_author.zip') as z:
        if z.testzip() is not None:
            raise ValueError('ZIP CRC failure')
        for name in z.namelist():
            dest = (RAW / 'enron' / name).resolve()
            if not dest.is_relative_to((RAW / 'enron').resolve()):
                raise ValueError('Unsafe zip member')
        z.extractall(RAW / 'enron')
        inventory = [{'name': x.filename, 'bytes': x.file_size,
                      'sha256': hashlib.sha256(z.read(x)).hexdigest()}
                     for x in z.infolist() if not x.is_dir()]
    (OUT / 'AUTHOR_ARCHIVE_INVENTORY.json').write_text(json.dumps(inventory, indent=2) + '\n')
    subprocess.run(['pdftotext', '-layout', str(RAW / 'info1_thesis.pdf'),
                    str(RAW / 'info1_thesis.txt')], check=True)
    info_zip = REPO / 'New version/20261014_dataset_review/archives/Info1.zip'
    with zipfile.ZipFile(info_zip) as z:
        if z.testzip() is not None:
            raise ValueError('Info1 CRC failure')
        for name in z.namelist():
            if not (RAW / 'info1' / name).resolve().is_relative_to((RAW / 'info1').resolve()):
                raise ValueError('Unsafe zip member')
        z.extractall(RAW / 'info1')
    print(json.dumps({'acquired': len(receipts), 'author_archive_files': len(inventory),
                      'raw': str(RAW)}, indent=2))

if __name__ == '__main__':
    main()
