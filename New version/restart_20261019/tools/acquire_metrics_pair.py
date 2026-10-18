#!/usr/bin/env python3
"""Original-first acquisition and locked inference for the software metrics lead."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'source_evidence/metrics_pair'
RAW = ROOT / 'source_evidence/raw/metrics_pair'
GIT_DIR = ROOT / 'source_evidence/raw/metrics_git'
REPO = 'Tuxprogrammer/msu_ece4723'
PATH = 'lab_6/docs/team_sw_metric.xlsx'
VERSIONS = {
    'before': ('57dd06e17074babe14c3201de9730f1355c1981a', 'd723e25b1d399534d4b9516e8ff69c9980b9c69d'),
    'after': ('fd7989d612307a970c638d7d5a926058d916667b', 'f90b46de946b7a0e08e67a56ce683cc2b4bb13f5')}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, payload):
    with path.open('x') as handle:
        json.dump(payload, handle, indent=2)
        handle.write('\n')


def acquire(stage):
    commit, blob = VERSIONS[stage]
    url = f'https://raw.githubusercontent.com/{REPO}/{commit}/{PATH}'
    transport = 'verified_local_git_object'
    try:
        body = subprocess.run(['git', f'--git-dir={GIT_DIR}', 'cat-file', 'blob', blob],
            check=True, capture_output=True, timeout=30).stdout
        status = None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        transport = 'commit_pinned_raw_github_stream'
        request = urllib.request.Request(url, headers={
            'User-Agent': 'HybridGuard-original-first-development/1.0'})
        chunks = []
        total = 0
        with urllib.request.urlopen(request, timeout=120) as response:
            status = response.status
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                assert total <= 10_000_000
                chunks.append(chunk)
        body = b''.join(chunks)
    assert len(body) <= 10_000_000
    assert hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == blob
    path = RAW / f'{stage}.xlsx'
    with path.open('xb') as handle:
        handle.write(body)
    save(OUT / f'{stage}_acquisition.json', dict(url=url, http_status=status,
        acquired_utc=dt.datetime.now(dt.timezone.utc).isoformat(), commit=commit, git_blob=blob,
        sha256=sha(path), bytes=len(body), transport=transport,
        local_git_dir=str(GIT_DIR.relative_to(ROOT)) if transport == 'verified_local_git_object' else None,
        final_validation_eligible=False,
        preregistration_sha256=sha(ROOT / 'METRICS_PAIR_PREREGISTRATION.md')))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['original', 'after'])
    args = parser.parse_args()
    if args.stage == 'after':
        lock = json.loads((OUT / 'prediction_lock.json').read_text())
        for relative, digest in lock['files'].items():
            assert sha(ROOT / relative) == digest
        acquire('after')
        print('Revision acquired after original lock')
        return
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    assert not any(OUT.iterdir()) and not any(RAW.iterdir()), 'refusing to overwrite an existing attempt'
    source = acquire('before')
    manifest = OUT / 'manifest.jsonl'
    with manifest.open('x') as handle:
        handle.write(json.dumps(dict(id='metrics', argv=[sys.executable,
            str(ROOT / 'tools/predict_workbook.py'), str(source), '--output', 'prediction.json'],
            outputs=['prediction.json'])) + '\n')
    command = [sys.executable, str(ROOT / 'tools/batch_runner.py'), '--manifest', str(manifest),
        '--output-dir', str(RAW / 'original_run'), '--workers', '8', '--worker-memory-mib', '1024', '--timeout', '300']
    run = subprocess.run(command, capture_output=True, text=True, timeout=360)
    save(OUT / 'batch_invocation.json', dict(argv=command, returncode=run.returncode,
         stdout=run.stdout, stderr=run.stderr))
    runtime = RAW / 'original_run/runtime.json'
    if runtime.exists():
        save(OUT / 'runtime.json', json.loads(runtime.read_text()))
    files = [path for parent in (RAW, OUT) for path in parent.rglob('*') if path.is_file()]
    save(OUT / 'prediction_lock.json', dict(files={str(path.relative_to(ROOT)): sha(path) for path in files},
        correction_acquired=False, labels_read=[], final_validation_eligible=False))
    print(run.stdout, run.stderr, flush=True)


if __name__ == '__main__':
    main()
