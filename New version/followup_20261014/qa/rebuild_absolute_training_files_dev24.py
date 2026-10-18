"""Rebuild exact fold copies using the published per-case selected options."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,sha
from build_candidates_dev18 import compact
from build_keep_features_dev21 import case_path
DATA=ROOT/'development/absolute_selection_dev24_data_v1'


def rebuild(output_root=DATA,fold_id=None):
    lock=read(DATA/'preparation_lock.json')
    assert sha(DATA/'fold_index.json')==lock['files']['fold_index.json']
    folds=read(DATA/'fold_index.json')['folds']
    if fold_id:
        assert fold_id in {f['id'] for f in folds};folds=[f for f in folds if f['id']==fold_id]
    for fold in folds:
        rel=fold['train_label_file'];target=output_root/rel
        if target.exists():
            assert sha(target)==fold['train_label_sha256'];continue
        rows=[]
        for case in fold['train_cases']:
            path='author_case_options/'+case_path(case)+'.json.gz'
            assert sha(DATA/path)==lock['files'][path]
            rows.extend(read(DATA/path)['alternatives'])
        compact(target,dict(training_cases=fold['train_cases'],heldout_cases=fold['test_cases'],alternatives=rows))
        assert sha(target)==fold['train_label_sha256']==lock['files'][rel]
        print('rebuilt dev24 exact',fold['id'],sha(target),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path,default=DATA);parser.add_argument('--fold')
    args=parser.parse_args();rebuild(args.output_root,args.fold)
