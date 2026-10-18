"""Rebuild missing derived fold files from published certified case-level files."""
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, sha
from build_candidates_dev18 import compact
from build_keep_features_dev21 import case_path
DATA = ROOT/'development/certified_preferences_dev22_data_v1'


def rebuild(output_root=DATA, fold_id=None):
    lock = read(DATA/'preparation_lock.json')
    for name in ['state_counts.json', 'fold_index.json']: assert sha(DATA/name) == lock['files'][name]
    metadata = {row['case']: dict(family=row['family'], source=row['source']) for row in read(DATA/'state_counts.json')}
    folds = read(DATA/'fold_index.json')['folds']
    if fold_id is not None:
        assert fold_id in {f['id'] for f in folds}
        folds = [f for f in folds if f['id'] == fold_id]
    for fold in folds:
        rel = fold['train_label_file']; target = output_root/rel
        if target.exists():
            assert sha(target) == fold['train_label_sha256'], target
            print('existing verified', fold['id'], flush=True); continue
        rows = []; states = []
        for case in fold['train_cases']:
            rel_pairs = 'author_case_pairs/'+case_path(case)+'.json.gz'
            rel_states = 'author_case_states/'+case_path(case)+'.json.gz'
            for path in [rel_pairs, rel_states]: assert sha(DATA/path) == lock['files'][path], path
            rows.extend(dict(row, **metadata[case]) for row in read(DATA/rel_pairs)['pairs'])
            states.extend(read(DATA/rel_states)['alternatives'])
        compact(target, dict(training_cases=fold['train_cases'], heldout_cases=fold['test_cases'], rows=rows, alternatives=states))
        assert sha(target) == fold['train_label_sha256'] == lock['files'][rel], target
        print('rebuilt exact', fold['id'], sha(target), flush=True)
        del rows, states


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, default=DATA)
    parser.add_argument('--fold')
    args = parser.parse_args(); rebuild(args.output_root, args.fold)
