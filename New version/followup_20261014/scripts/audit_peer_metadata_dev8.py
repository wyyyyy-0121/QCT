"""Audit revealed regression misses and runner metadata; never a predictor."""
from collections import Counter
from pathlib import Path
import datetime
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_selector_dev5 import read, save, sha

RUN = ROOT / 'development/peer_metadata_audit_dev8'


def main():
    if RUN.exists():
        raise SystemExit('Preserve existing audit evidence')
    old_index = read(ROOT / 'development/selector_dev6_contract_v2/public_index.json')
    totals = Counter()
    cases = []
    for entry in old_index:
        if entry['group'] != 'regression':
            continue
        case = entry['id']
        observed = read(ROOT / f'baseline/predictions/{case}/input_formulas.json.gz')
        public_path = ROOT / f'baseline/data/{case}/public.json'
        public = read(public_path)
        truth = read(ROOT / f'baseline/data/{case}/truth.json')
        pred = read(ROOT / f'development/selector_dev6_contract_v2/predictions/regression/{case}.json.gz')
        rows = {r['cell']: r for r in pred['rows']}
        counts = Counter()
        misses = []
        real_sheets = sorted({c.rsplit('!', 1)[0] for c in observed})
        declared = entry['parallel_sheets']
        declared_absent = sorted(set(declared) - set(real_sheets))
        if declared_absent:
            totals['cases_with_absent_declared_sheets'] += 1
        for cell in truth['errors']:
            row = rows[cell]
            expected = truth['expected_formulas'][cell]
            if row['status'] == 'propose' and row.get('suggested_formula') == expected:
                continue
            sheet, address = cell.rsplit('!', 1)
            peers = {s: observed[s+'!'+address] for s in public['parallel_sheets']
                     if s != sheet and s+'!'+address in observed}
            matches = sorted(s for s, f in peers.items() if f == expected)
            counts['misses'] += 1
            counts['misses_with_exact_same_position_peer'] += bool(matches)
            counts['misses_with_three_exact_peers'] += len(matches) >= 3
            counts['legacy_suggestion_source:' + str(row.get('suggestion_source'))] += 1
            counts['reason:' + str(row.get('reason'))] += 1
            misses.append({'cell': cell, 'observed': observed[cell], 'expected': expected,
                           'matching_peer_sheets': matches, 'available_peer_count': len(peers),
                           'status': row['status'], 'reason': row.get('reason'),
                           'legacy_suggestion_source': row.get('suggestion_source'),
                           'legacy_source_is_not_current_authorization': True})
        totals.update(counts)
        cases.append({'id': case, 'actual_formula_sheets': real_sheets,
                      'old_runner_parallel_sheets': declared,
                      'authoritative_public_parallel_sheets': public['parallel_sheets'],
                      'public_sha256': sha(public_path),
                      'declared_but_absent': declared_absent,
                      'counts': dict(counts), 'misses': misses})
    result = {'role': 'revealed development diagnostic; truth deliberately read only in audit',
              'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'cases': cases, 'totals': dict(totals),
              'findings': [
                  'Historical dev5/dev6/dev7 regression runner metadata uses A-E instead of frozen public.json.',
                  'The original baseline and dev2 use frozen public.json correctly.',
                  'suggestion_source survives from original predictions and is not current authorization.',
                  'dev7 only handles dev5 output-role dictionary; financial net profit is absent.',
                  'Shared peer support is candidate provenance, not independent business correctness.']}
    save(RUN / 'AUDIT.json', result)
    print(dict(totals))


if __name__ == '__main__':
    main()
