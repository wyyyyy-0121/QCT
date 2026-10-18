#!/usr/bin/env python3
"""Acquire archived EPA originals, lock predictions, then acquire revisions."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'source_evidence/epa_pairs'
RAW = ROOT / 'source_evidence/raw/epa_pairs'
BOOKS = {
    'flares': {
        'before': 'https://19january2021snapshot.epa.gov/sites/static/files/2019-08/epa_flares_costcalculations_sheet_august2019vf.xlsm',
        'after': 'https://www.epa.gov/system/files/other-files/2022-09/EPA_Flares_CostCalc_Sheet_September%202022.xlsm'},
    'oxidizers': {
        'before': 'https://19january2021snapshot.epa.gov/sites/static/files/2018-01/oxidizers_calc_sheet_finalversion_1-16-2018.xlsm',
        'after': 'https://www.epa.gov/system/files/other-files/2024-12/us-epa_oaqps_incineratorsoxidizers_calc_sheet_december_2024v.xlsm'},
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open('x') as handle:
        json.dump(data, handle, indent=2)
        handle.write('\n')


def acquire(name, stage):
    url = BOOKS[name][stage]
    receipt = dict(url=url, acquired_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        preregistration_sha256=sha(ROOT / 'EPA_PAIR_PREREGISTRATION.md'),
        final_validation_eligible=False, certified_natural_errors=0)
    path = RAW / f'{name}_{stage}.xlsm'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'HybridGuard-original-first-research/1.0'})
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read(20_000_001)
            receipt.update(http_status=response.status, resolved_url=response.url)
        if len(body) > 20_000_000:
            raise ValueError('file size exceeds 20 MB bound')
        with path.open('xb') as handle:
            handle.write(body)
        with zipfile.ZipFile(path) as archive:
            assert 'xl/workbook.xml' in archive.namelist(), 'not an OOXML workbook'
        receipt.update(ok=True, bytes=len(body), sha256=sha(path))
    except Exception as error:
        receipt.update(ok=False, error=f'{type(error).__name__}: {error}')
    save(OUT / f'{name}_{stage}_acquisition.json', receipt)
    print(json.dumps(dict(name=name, stage=stage, **receipt)), flush=True)
    return path if receipt['ok'] else None


def verify_lock():
    lock = json.loads((OUT / 'prediction_lock.json').read_text())
    for relative, digest in lock['files'].items():
        assert sha(ROOT / relative) == digest, relative


def original():
    OUT.mkdir(parents=True, exist_ok=False)
    RAW.mkdir(parents=True, exist_ok=False)
    tasks = []
    for name in BOOKS:
        path = acquire(name, 'before')
        if path:
            tasks.append(dict(id=name, argv=[sys.executable, str(ROOT / 'tools/predict_workbook.py'),
                str(path), '--output', 'prediction.json'], outputs=['prediction.json']))
    manifest = OUT / 'manifest.jsonl'
    with manifest.open('x') as handle:
        for task in tasks:
            handle.write(json.dumps(task) + '\n')
    result = None
    if tasks:
        command = [sys.executable, str(ROOT / 'tools/batch_runner.py'), '--manifest', str(manifest),
                   '--output-dir', str(RAW / 'original_run'), '--workers', '8',
                   '--worker-memory-mib', '1024', '--timeout', '300']
        result = subprocess.run(command, capture_output=True, text=True, timeout=360)
        save(OUT / 'original_batch_invocation.json', dict(argv=command, returncode=result.returncode,
             stdout=result.stdout, stderr=result.stderr))
        runtime = RAW / 'original_run/runtime.json'
        if runtime.exists():
            save(OUT / 'original_runtime.json', json.loads(runtime.read_text()))
    files = [path for path in OUT.rglob('*') if path.is_file()]
    files += [path for path in RAW.rglob('*') if path.is_file()]
    save(OUT / 'prediction_lock.json', dict(files={str(path.relative_to(ROOT)): sha(path) for path in files},
        originals_acquired=len(tasks), labels_read=[], correction_acquired=False,
        final_validation_eligible=False, batch_returncode=result.returncode if result else None))
    print('Original evidence locked; revisions have not been acquired', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['original', 'after'])
    args = parser.parse_args()
    if args.stage == 'original':
        original()
    else:
        verify_lock()
        for name in BOOKS:
            receipt = json.loads((OUT / f'{name}_before_acquisition.json').read_text())
            if receipt['ok']:
                acquire(name, 'after')
            else:
                print(f'Skipped {name}: original was not acquired', flush=True)


if __name__ == '__main__':
    main()
