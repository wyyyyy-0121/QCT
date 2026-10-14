"""Run dev1 on already revealed regression cases; lock outputs before scoring."""
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import importlib.util
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'baseline'
sys.path.insert(0, str(BASELINE / 'source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev1 import select, VERSION, PARAMETERS


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    if path.suffix == '.gz':
        with gzip.open(path, 'rt') as f:
            return json.load(f)
    return json.loads(path.read_text())


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def predict():
    run = ROOT / 'development/selector_dev1'
    if run.exists():
        raise SystemExit('Refusing to overwrite development evidence')
    lock = read(BASELINE / 'protocol/prediction_lock.json')
    for relative, expected in lock['files'].items():
        assert sha(BASELINE / relative) == expected, relative
    entries = read(BASELINE / 'protocol/public_index.json')
    source_files = [Path(__file__), ROOT/'scripts/selector_dev1.py'] + sorted((BASELINE/'source').rglob('*.py'))
    save(run/'source_lock.json', {'version': VERSION, 'parameters': PARAMETERS,
        'files': {str(p.relative_to(ROOT)): sha(p) for p in source_files}})

    def deny_labels(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0]).lower()
            if 'truth.json' in name or '/results/' in name:
                raise PermissionError('Prediction cannot read truth or scored results: '+name)
    sys.addaudithook(deny_labels)
    for entry in entries:
        case = entry['id']
        start = time.perf_counter()
        model = WorkbookModel.from_xlsx(BASELINE/'data'/case/'input.xlsx')
        pred = BASELINE/'predictions'/case
        fg = read(pred/'fg.json.gz')['rows']
        sg = read(pred/'sg.json.gz')['rows']
        public = read(BASELINE/'data'/case/'public.json')
        before = dict(model.formulas)
        output = select(model, read(pred/'full.json.gz'), fg, sg, public['parallel_sheets'])
        assert model.formulas == before
        output.update(case=case, seconds=time.perf_counter()-start)
        target = run/'predictions'/(case+'.json.gz')
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(filename=str(target), mode='wb', mtime=0) as f:
            f.write(json.dumps(output, ensure_ascii=False, sort_keys=True).encode())
        print(case, 'propose', sum(r['status']=='propose' for r in output['rows']), flush=True)
    files = sorted((run/'predictions').glob('*.gz'))
    assert len(files) == 39
    save(run/'prediction_lock.json', {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'labels_read': [], 'role': 'revealed development only', 'source_lock_sha256': sha(run/'source_lock.json'),
        'baseline_prediction_lock_sha256': sha(BASELINE/'protocol/prediction_lock.json'),
        'files': {str(p.relative_to(run)): sha(p) for p in files}})


def score():
    run = ROOT/'development/selector_dev1'
    lock = read(run/'prediction_lock.json')
    for relative, expected in lock['files'].items():
        assert sha(run/relative) == expected, relative
    assert sha(run/'source_lock.json') == lock['source_lock_sha256']
    for relative, expected in read(run/'source_lock.json')['files'].items():
        assert sha(ROOT/relative) == expected, relative
    spec = importlib.util.spec_from_file_location('paper_scorer', BASELINE/'scripts/score.py')
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    rows = []
    for entry in read(BASELINE/'protocol/data_manifest.json'):
        case = entry['id']
        observed = read(BASELINE/'predictions'/case/'input_formulas.json.gz')
        truth = read(BASELINE/'data'/case/'truth.json')
        pred = read(run/'predictions'/(case+'.json.gz'))
        metrics = scorer.evaluate(pred, observed, truth)
        rows.append({'case': case, 'family': entry['family'], 'version': VERSION, **metrics})
    totals = {'proposals': sum(x['proposals'] for x in rows), 'correct': sum(x['exact_repairs'] for x in rows),
        'errors': sum(x['errors'] for x in rows), 'harmful_correct_cells': sum(x['harmful_correct_cells'] for x in rows)}
    totals['precision'] = totals['correct']/totals['proposals'] if totals['proposals'] else None
    totals['coverage'] = totals['correct']/totals['errors']
    save(run/'score.json', {'role': 'revealed development, not final validation', 'totals': totals, 'cases': rows})
    print(json.dumps(totals, indent=2))
    for family in sorted({x['family'] for x in rows}):
        cases = [x for x in rows if x['family']==family]
        p = sum(x['proposals'] for x in cases); c = sum(x['exact_repairs'] for x in cases); e = sum(x['errors'] for x in cases)
        print(family, 'precision', c/p if p else None, 'coverage', c/e if e else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['predict','score'])
    args = parser.parse_args()
    predict() if args.stage=='predict' else score()
