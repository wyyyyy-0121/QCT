"""Replay locked unit/candidate diagnostics before opening any scoring labels."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import datetime
import sys
import time
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_evidence_gap_dev1 import RUN, REVIEW_STATUSES, verify_lock, build_score
from run_selector_dev5 import read, save, sha
from formulaguard.workbook import WorkbookModel
from formula_candidates_dev1 import generate
from unit_evidence_dev1 import UnitEvidence


def main():
    verify_lock()
    accesses = set()
    replaying = True
    def guard(event, args):
        if replaying and event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(term in name.casefold() for term in [
                    'truth.json', '/score', '/results/', 'input_oracle', 'mutation_log', 'failure_audit']):
                raise PermissionError('Replay must finish before reading labels: ' + name)
            if str(ROOT) in name:
                accesses.add(name)
    sys.addaudithook(guard)
    started = time.perf_counter()
    counts = Counter()
    cached_generate = lru_cache(maxsize=2048)(generate)
    for item in read(RUN / 'public_index.json'):
        path = ROOT / item['input']
        assert sha(path) == item['input_sha256']
        model = WorkbookModel.from_xlsx(path)
        unit = UnitEvidence(model)
        prior = {r['cell']: r for r in read(ROOT / item['dev6_prediction'])['rows']}
        prediction = read(RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz'))
        observed = {s+'!'+a: f for (s, a), f in model.formulas.items()}
        assert len(prediction['rows']) == len(observed)
        assert {r['cell'] for r in prediction['rows']} == set(observed)
        assert not prediction['selector_changes']
        assert prediction['labels_read'] == prediction['repair_proposals'] == []
        for row in prediction['rows']:
            cell = row['cell']; sheet, address = cell.rsplit('!', 1)
            assert row['observed_formula'] == observed[cell]
            assert row['prior_status'] == prior[cell]['status']
            # JSON locking converts tuple-valued normalized units to lists.
            # Compare the canonical serialized representation on replay.
            expected_unit = json.loads(json.dumps(unit.check(observed[cell], sheet, address)))
            assert row['unit_current'] == expected_unit
            counts['formula_cells'] += 1
            if prior[cell]['status'] in REVIEW_STATUSES:
                assert row['inventory_requested']
                generated = cached_generate(observed[cell])
                assert row['inventory_status'] == generated['status']
                assert row['search_truncated'] == generated['search_truncated']
                assert [c['formula'] for c in row['candidates']] == [c['formula'] for c in generated['candidates']]
                for candidate, origin in zip(row['candidates'], generated['candidates']):
                    check = unit.check(candidate['formula'], sheet, address)
                    assert candidate['unit_status'] == check['status']
                    assert candidate['unit_reason'] == check.get('reason')
                    assert candidate['edit_kinds'] == sorted({e['kind'] for e in origin['edits']})
                    counts['candidate_hypotheses'] += 1
                counts['inventory_rows'] += 1
            else:
                assert not row['inventory_requested'] and not row['candidates']
        counts['cases'] += 1
        print('Replayed', item['group'], item['id'], flush=True)
    replay_seconds = time.perf_counter() - started
    replaying = False
    # Labels can only be read after every prediction has been replayed.
    assert read(RUN / 'score.json') == build_score()
    report = {'all_locks_verified': True, 'all_diagnostics_replayed_exactly': True,
              'labels_read_during_replay': False, 'score_recomputed_after_replay': True,
              'counts': dict(counts), 'replay_wall_seconds': replay_seconds,
              'prediction_lock_sha256': sha(RUN / 'prediction_lock.json'),
              'score_sha256': sha(RUN / 'score.json'), 'verifier_sha256': sha(Path(__file__)),
              'repair_proposals_generated': False, 'final_validation_eligible': False,
              'replay_accesses': sorted(accesses),
              'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(ROOT / 'qa/EVIDENCE_GAP_DEV1_REPLAY_20261015.json', report)
    print(dict(counts), 'replayed and score recomputed', flush=True)


if __name__ == '__main__':
    main()
