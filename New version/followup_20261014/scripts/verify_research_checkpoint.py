"""Read-only integrity check for the resumed development checkpoint."""
from pathlib import Path
import datetime
import hashlib
import json
import platform
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_selector_dev5 import read as read_compressed, metrics, total, verify_run

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
    # Verify new files and recompute scores from actual locked predictions,
    # including all clean cells and every uncorrected error in denominators.
    verify_run()
    dev5_run = ROOT / 'development/selector_dev5'
    dev5_score = read(dev5_run / 'score.json')
    assert dev5_score['prediction_lock_sha256'] == sha(dev5_run / 'prediction_lock.json')
    for group, folder in [('regression',None), ('stress','semantic_stress_dev1'),
                          ('tradeoff','policy_tradeoff_dev1'), ('crossdomain','crossdomain_dev1')]:
        entries = (read(ROOT / 'baseline/protocol/data_manifest.json') if folder is None else
                   read(ROOT / 'development' / folder / 'truth.json')['cases'])
        scored = {c['id']:c for c in dev5_score[group]['cases']}
        assert set(scored) == {e['id'] for e in entries}
        for entry in entries:
            case = entry['id']
            if folder is None:
                truth = read(ROOT / 'baseline/data' / case / 'truth.json')
                observed = read_compressed(ROOT / 'baseline/predictions' / case / 'input_formulas.json.gz')
            else:
                truth = entry
                suffix = '.json.gz' if group == 'crossdomain' else '.json'
                observed = read_compressed(ROOT / 'development' / folder / 'predictions' / (case+suffix))['observed_formulas']
            for name in ['dev4','dev5']:
                if name == 'dev4' and group == 'crossdomain':
                    pred = read_compressed(ROOT / 'development/crossdomain_dev1/predictions' / (case+'.json.gz'))['dev4']
                else:
                    pred = read_compressed(ROOT / 'development' / ('selector_'+name) / 'predictions' / group / (case+'.json.gz'))
                assert metrics(pred,truth,observed) == scored[case][name], (group,case,name)
        if group in ['regression','crossdomain']:
            assert dev5_score[group]['totals'] == {name:total(list(scored.values()),name) for name in ['dev4','dev5']}
    assert dev5_score['regression']['totals']['dev5'] == dev5_score['regression']['totals']['dev4']
    assert dev5_score['crossdomain']['totals']['dev5']['correct'] == 492
    assert dev5_score['crossdomain']['totals']['dev5']['wrong'] == 0
    checks.append({'lock':'development/selector_dev5/prediction_lock.json',
        'verified_files':len(read(dev5_run / 'prediction_lock.json')['files']),
        'sha256':sha(dev5_run / 'prediction_lock.json'), 'scores_recomputed':True,
        'cases':83,'source_lock_verified':True,'score_sha256':sha(dev5_run / 'score.json')})
    adversarial = ROOT / 'development/dev5_adversarial1'
    lock = read(adversarial / 'prediction_lock.json')
    assert sha(adversarial / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(adversarial / 'public_index.json') == lock['public_index_sha256']
    for root, files in [(ROOT,read(adversarial / 'source_lock.json')['files']), (adversarial,lock['files'])]:
        for relative, expected in files.items(): assert sha(root / relative) == expected, relative
    assert lock['labels_read'] == []
    for entry in read(adversarial / 'public_index.json'):
        assert sha(adversarial / entry['input']) == entry['sha256']
    adverse_score = read(adversarial / 'score.json')
    assert adverse_score['prediction_lock_sha256'] == sha(adversarial / 'prediction_lock.json')
    assert not adverse_score['pooled_acceptance_metric']
    assert read(adversarial / 'registration.json')['dev5_prediction_lock_sha256'] == sha(dev5_run / 'prediction_lock.json')
    scored = {c['id']:c for c in adverse_score['cases']}
    truths = read(adversarial / 'truth.json')['cases']
    assert len(scored) == len(truths) == 24
    for truth in truths:
        prediction = read_compressed(adversarial / 'predictions' / (truth['id']+'.json.gz'))
        for name in ['paper','dev4','dev5']:
            pred = prediction[name]
            if name == 'paper':
                pred = {**pred,'rows':[{**r,'status':'propose' if r.get('suggested_formula') else 'abstain'} for r in pred['rows']]}
            assert metrics(pred,truth,prediction['observed_formulas']) == scored[truth['id']][name]
    for scenario, counts in adverse_score['by_variant'].items():
        assert counts == {name:total([c for c in scored.values() if c['scenario']==scenario],name)
                          for name in ['paper','dev4','dev5']}
    assert adverse_score['by_variant']['unmarked_reversed_role']['dev5']['wrong'] == 4
    checks.append({'lock':'development/dev5_adversarial1/prediction_lock.json',
        'verified_files':len(lock['files']), 'sha256':sha(adversarial / 'prediction_lock.json'),
        'scores_recomputed':True,'cases':24,'source_lock_verified':True,
        'score_sha256':sha(adversarial / 'score.json')})
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
