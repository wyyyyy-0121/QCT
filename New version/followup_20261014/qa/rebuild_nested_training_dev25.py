"""Rebuild exact nested fold copies from frozen published dev24 case options."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,sha
from build_candidates_dev18 import compact
DATA=ROOT/'development/nested_calibration_dev25_data_v1'
OPTIONS=ROOT/'development/absolute_selection_dev24_data_v1'


def rebuild(output_root=DATA,pair_id=None):
    lock=read(DATA/'preparation_lock.json');option_lock=read(OPTIONS/'preparation_lock.json')
    assert sha(DATA/'fold_index.json')==lock['files']['fold_index.json']
    folds=read(DATA/'fold_index.json')['pairs']
    if pair_id:
        assert pair_id in {f['id'] for f in folds};folds=[f for f in folds if f['id']==pair_id]
    for f in folds:
        target=output_root/f['train_label_file']
        if target.exists():assert sha(target)==f['train_label_sha256'];continue
        rows=[]
        for case in f['train_cases']:
            rel='author_case_options/'+case.replace('/','__')+'.json.gz'
            assert sha(OPTIONS/rel)==option_lock['files'][rel]
            rows.extend(read(OPTIONS/rel)['alternatives'])
        compact(target,dict(training_cases=f['train_cases'],heldout_cases=f['test_cases'],alternatives=rows))
        assert sha(target)==f['train_label_sha256']==lock['files'][f['train_label_file']]
        print('rebuilt nested exact',f['id'],sha(target),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path,default=DATA);parser.add_argument('--pair')
    args=parser.parse_args();rebuild(args.output_root,args.pair)
