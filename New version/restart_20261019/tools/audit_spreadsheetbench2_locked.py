#!/usr/bin/env python3
"""Inspect golden differences only AFTER verifying all 100 locked predictions.

This audit produces candidate differences, never automatically certified labels.
All third-party contents remain in the ignored local evidence directory.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import zipfile

import openpyxl

from spreadsheetbench2_scoring import verify_prediction_lock, formula_differences
from resume_spreadsheetbench2_after_pilot import verify_frozen

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'source_evidence/raw/spreadsheetbench2'


def audit_input(args):
    row, golden_bytes, identifier, terminal = args
    before = openpyxl.load_workbook(row['local_path'], read_only=True, data_only=False)
    after = openpyxl.load_workbook(io.BytesIO(golden_bytes), read_only=True, data_only=False)
    try:
        result = formula_differences(before, after)
    finally:
        before.close()
        after.close()
    result.update(id=identifier, group=row['group'], archive_path=row['archive_path'],
                  terminal_status=terminal)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=20)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('workers must be positive')
    lock, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    target = EVIDENCE / 'scoring/candidate_differences.json'
    if target.exists():
        raise SystemExit('Preserving existing scoring audit')
    archive_path = Path(inputs['archive']['path'])
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != inputs['archive']['sha256']:
        raise SystemExit('Archive differs from prelock')
    terminal_by_id = {t['id']: t['status'] for t in lock['predictions']}
    goldens = {}
    metadata = {}
    with zipfile.ZipFile(archive_path) as archive:
        for golden in inputs['goldens_hash_only']:
            contents = archive.read(golden['archive_path'])
            if hashlib.sha256(contents).hexdigest() != golden['sha256']:
                raise SystemExit('Golden differs from prelock')
            group = Path(golden['archive_path']).parts[3]
            goldens[group] = contents
        for member in archive.namelist():
            if member.endswith('/dataset.json') or member == 'dataset.json':
                metadata[member] = json.loads(archive.read(member))
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = target.with_name('task_metadata.json')
    with metadata_path.open('x') as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    jobs = []
    for row in inputs['inputs']:
        # The locked tasks have an archive-path hash suffix; no model dependency.
        suffix = hashlib.sha256(row['archive_path'].encode()).hexdigest()[:10]
        matches = [identifier for identifier in terminal_by_id if identifier.endswith('_' + suffix)]
        if len(matches) != 1:
            raise SystemExit('Ambiguous input-to-task mapping')
        identifier = matches[0]
        jobs.append((row, goldens[row['group']], identifier, terminal_by_id[identifier]))
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(audit_input, jobs))
    payload = {'prediction_lock_sha256': hashlib.sha256((EVIDENCE/'prediction_lock.json').read_bytes()).hexdigest(),
               'role': 'Post-lock candidate formula differences; task relevance not certified',
               'workers': args.workers, 'tasks': results, 'task_metadata_archive_paths': list(metadata)}
    with target.open('x') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'tasks': len(results), 'candidate_formula_difference_counts':
                      {r['id']: len(r['formula_changes']) for r in results},
                      'metadata_files': list(metadata)}, indent=2))


if __name__ == '__main__':
    main()
