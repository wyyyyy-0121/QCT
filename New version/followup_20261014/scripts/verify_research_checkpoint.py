"""Read-only integrity check for the resumed development checkpoint."""
from pathlib import Path
import datetime
import hashlib
import json
import platform

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def verify():
    checks = []
    for name in ['source_lock.json', 'prediction_lock.json']:
        path = ROOT / 'baseline/protocol' / name
        for relative, expected in read(path)['files'].items():
            assert sha(ROOT / 'baseline' / relative) == expected, relative
        checks.append({'lock': str(path.relative_to(ROOT)), 'verified_files': len(read(path)['files']),
                       'sha256': sha(path)})
    for name in ['selector_dev1', 'selector_dev2', 'semantic_stress_dev1', 'selector_dev3',
                 'policy_tradeoff_dev1', 'selector_dev4']:
        run = ROOT / 'development' / name
        path = run / 'prediction_lock.json'; lock = read(path)
        assert sha(run / 'source_lock.json') == lock['source_lock_sha256']
        for relative, expected in lock['files'].items():
            assert sha(run / relative) == expected, (name, relative)
        for relative, expected in read(run / 'source_lock.json')['files'].items():
            assert sha(ROOT / relative) == expected, (name, relative)
        for relative, expected in lock.get('inputs_and_upstream', {}).items():
            assert sha(ROOT / relative) == expected, (name, relative)
        if (run / 'public_index.json').exists():
            assert sha(run / 'public_index.json') == lock['public_index_sha256']
            for entry in read(run / 'public_index.json'):
                assert sha(run / entry['input']) == entry['sha256']
        assert lock.get('labels_read', []) == []
        score = run / ('score_v2_propose_only.json' if name == 'selector_dev1' else 'score.json')
        # dev1's independent corrected scoring report predates this field contract.
        if 'prediction_lock_sha256' in read(score):
            assert read(score)['prediction_lock_sha256'] == sha(path)
        checks.append({'lock': str(path.relative_to(ROOT)), 'verified_files': len(lock['files']),
                       'sha256': sha(path), 'source_lock_verified': True, 'score_sha256': sha(score)})
    run = ROOT / 'development/crossdomain_dev1'
    path = run / 'prediction_lock.json'; lock = read(path)
    assert sha(run / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(run / 'public_index.json') == lock['public_index_sha256']
    for relative, expected in lock['files'].items():
        assert sha(run / relative) == expected, ('crossdomain', relative)
    for relative, expected in read(run / 'source_lock.json')['files'].items():
        assert sha(ROOT / relative) == expected, ('crossdomain-source', relative)
    assert lock.get('labels_read', []) == []
    for entry in read(run / 'public_index.json'):
        assert sha(run / entry['input']) == entry['sha256'], ('crossdomain-input', entry['id'])
    score = read(run / 'score.json')
    assert score['prediction_lock_sha256'] == sha(path)
    assert len(score['cases']) == 32
    assert {item['family'] for item in score['cases']} == {
        'inventory_rollforward', 'loan_amortization', 'budget_allocation', 'unit_conversion'}
    assert read(run / 'registration.json')['new_final_families'] == 0
    assert len(read(run / 'qa/input_oracle_check.json')) == 32
    totals = score['totals']['all_development_families']
    assert totals['dev4']['proposals'] == 11
    assert totals['dev4']['correct'] == 8
    assert totals['dev4']['wrong'] == 3
    checks.append({'lock': str(path.relative_to(ROOT)), 'verified_files': len(lock['files']),
                   'sha256': sha(path), 'source_lock_verified': True, 'score_sha256': sha(run / 'score.json'),
                   'revealed_development_cases': 32, 'families': 4,
                   'dev4_proposals': 11, 'dev4_correct': 8, 'dev4_wrong': 3})
    dev2 = read(ROOT / 'development/selector_dev2/score.json')['totals']
    dev4 = read(ROOT / 'development/selector_dev4/score.json')
    assert dev2 == dev4['regression']['totals']
    assert sum(c['wrong'] for c in dev4['stress']['cases']) == 0
    assert sum(c['wrong'] for c in dev4['tradeoff']['cases']) == 25
    assert dev4['tradeoff']['cases'][0]['correct'] == 24
    status = read(ROOT / 'STATUS.json'); ledger = read(ROOT / 'source_discovery/SOURCE_READINESS.json')
    assert status['goal_status'] == 'active'
    assert not status['development_gate_passed'] and not status['final_validation_complete']
    assert ledger['accepted_sources'] == ledger['accepted_template_families'] == 0
    result = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'python': platform.python_version(),
              'checks': checks, 'development_totals_verified': dev2, 'goal_active': True,
              'final_gate_passed': False, 'dev4_unmarked_exception_wrong_proposals': 25,
              'dev4_known_policy_coverage_case_correct_repairs': 24}
    path = ROOT / 'qa/RESUME_VERIFICATION_20261015.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('Verified', len(checks), 'source/prediction locks and current scores; goal active, not passed')


if __name__ == '__main__':
    verify()
