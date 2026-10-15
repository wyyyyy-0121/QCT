"""Diagnose revealed development failures; never used by prediction."""
from pathlib import Path
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import argparse

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'baseline'


def read(path):
    if path.suffix == '.gz':
        with gzip.open(path, 'rt') as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def main(run_name='selector_dev1'):
    RUN = ROOT / 'development' / run_name
    lock = read(RUN / 'prediction_lock.json')
    for relative, expected in lock['files'].items():
        assert hashlib.sha256((RUN / relative).read_bytes()).hexdigest() == expected
    cases = []
    wrong = []
    for entry in read(BASE / 'protocol/data_manifest.json'):
        case = entry['id']
        truth = read(BASE / 'data' / case / 'truth.json')
        observed = read(BASE / 'predictions' / case / 'input_formulas.json.gz')
        rows = read(RUN / 'predictions' / (case + '.json.gz'))['rows']
        errors = set(truth['errors'])
        reasons = Counter()
        examples = defaultdict(list)
        correct = 0
        for row in rows:
            key = row['cell']
            proposed = row.get('suggested_formula') if row['status'] == 'propose' else None
            expected = truth['expected_formulas'][key]
            if proposed and proposed != observed[key]:
                if proposed == expected:
                    correct += 1
                else:
                    wrong.append({'case': case, 'cell': key, 'is_error': key in errors,
                        'actual': observed[key], 'expected': expected,
                        'proposed': proposed, 'evidence': row['selection_evidence']})
            if key in errors and proposed != expected:
                reason = row.get('reason', row['status'])
                reasons[reason] += 1
                if len(examples[reason]) < 3:
                    examples[reason].append({'cell': key, 'actual': observed[key],
                        'expected': expected, 'status': row['status'],
                        'candidate': row.get('candidate_formula'),
                        'evidence': row['selection_evidence']})
        cases.append({'case': case, 'family': entry['family'], 'errors': len(errors),
            'correct': correct, 'missed': len(errors) - correct,
            'missed_by_reason': dict(reasons), 'examples': dict(examples)})
    report = {'role': 'revealed development diagnostic; labels intentionally read here only',
        'cases': cases, 'wrong_proposals': wrong,
        'wrong_count': len(wrong), 'missed_count': sum(c['missed'] for c in cases)}
    destination = RUN / 'FAILURE_AUDIT.json'
    if destination.exists():
        raise SystemExit('Refusing to overwrite existing failure audit')
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('wrong:',len(wrong),'missed:',report['missed_count'])
    for case in cases:
        if case['missed']:
            print(case['case'],case['correct'],'/',case['errors'],case['missed_by_reason'])
    print('wrong signatures:',Counter((w['actual'].rstrip('0123456789'), w['proposed'].rstrip('0123456789')) for w in wrong))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',default='selector_dev1',choices=['selector_dev1','selector_dev2'])
    main(parser.parse_args().run)
