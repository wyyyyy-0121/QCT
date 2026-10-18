#!/usr/bin/env python3
"""Original-first ODS candidate audit, preserving conversion and failure evidence."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'source_evidence/stampz'
RAW = ROOT / 'source_evidence/raw/stampz'
BLOBS = {'before': 'a0061f2d21ba782736ed3d7c5c5939ac619cfdf3',
         'after': '85bbe870e31390d4c57ea0ed6236fe8caadb6cca'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open('x') as handle:
        json.dump(data, handle, indent=2)
        handle.write('\n')


def acquire(version):
    if version == 'after':
        lock = json.loads((OUT / 'prediction_lock.json').read_text())
        for relative, digest in lock['files'].items():
            assert sha(ROOT / relative) == digest
    blob = BLOBS[version]
    url = 'https://api.github.com/repos/Stainlessbrown/StampZ-III-Binary/git/blobs/' + blob
    req = urllib.request.Request(url, headers={'User-Agent': 'HybridGuard-original-first-development/1.0'})
    with urllib.request.urlopen(req, timeout=25) as response:
        body = response.read(1000000)
    data = json.loads(body)
    raw = base64.b64decode(data['content'])
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob
    path = RAW / (version + '.ods')
    with path.open('xb') as handle:
        handle.write(raw)
    save(OUT / (version + '_acquisition.json'), dict(url=url, git_blob=blob, bytes=len(raw),
        sha256=sha(path), preregistration_sha256=sha(ROOT / 'STAMPZ_PREREGISTRATION.md'),
        final_validation_eligible=False))
    return path


def original():
    OUT.mkdir(parents=True, exist_ok=False)
    RAW.mkdir(parents=True, exist_ok=False)
    source = acquire('before')
    before = sha(source)
    with tempfile.TemporaryDirectory(prefix='hg-stampz-profile-') as profile:
        command = ['/usr/bin/libreoffice', '-env:UserInstallation=' + Path(profile).as_uri(),
                   '--headless', '--convert-to', 'xlsx:Calc MS Excel 2007 XML',
                   '--outdir', str(RAW), str(source)]
        conversion = subprocess.run(command, capture_output=True, text=True, timeout=60)
    save(OUT / 'conversion.json', dict(command=command, returncode=conversion.returncode,
         stdout=conversion.stdout, stderr=conversion.stderr,
         version=subprocess.check_output(['/usr/bin/libreoffice', '--version'], text=True).strip(),
         original_ods_sha256=before, original_unchanged=sha(source) == before,
         native_ods_model_support=False, conversion_fidelity_verified=False))
    converted = RAW / 'before.xlsx'
    output = RAW / 'prediction.json'
    record = dict(status='conversion_failed', final_validation_eligible=False)
    if conversion.returncode == 0 and converted.exists():
        command = [sys.executable, str(ROOT / 'tools/predict_workbook.py'), str(converted), '--output', str(output)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            record.update(status='complete' if result.returncode == 0 else 'failed',
                          returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        except subprocess.TimeoutExpired as error:
            record.update(status='timeout', stdout=str(error.stdout), stderr=str(error.stderr))
    save(OUT / 'prediction_runtime.json', record)
    files = [source, OUT / 'conversion.json', OUT / 'prediction_runtime.json']
    files += [path for path in [converted, output] if path.exists()]
    save(OUT / 'prediction_lock.json', dict(status=record['status'],
        files={str(path.relative_to(ROOT)): sha(path) for path in files}, labels_read=[],
        correction_acquired=False, conversion_fidelity_verified=False, final_validation_eligible=False))
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['original', 'after'])
    args = parser.parse_args()
    original() if args.stage == 'original' else acquire('after')
