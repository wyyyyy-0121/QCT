#!/usr/bin/env python3
"""Input-only paper syntax diagnosis and locked 20-worker orchestration."""
import argparse
from collections import Counter
import datetime as dt
import gzip
import json
from pathlib import Path
import re
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock
sys.path.insert(0, str(ROOT.parent / 'followup_20261014/baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.formula import parse_formula, Func, Binary, Unary
from openpyxl.formula import Tokenizer

EXPERIMENT = EVIDENCE / 'model_m4_syntax'
SUPPORTED_FUNCTIONS = {'IF', 'SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT'}


def functions(node):
    if isinstance(node, Func):
        yield node.name
        for arg in node.args:
            yield from functions(arg)
    elif isinstance(node, Binary):
        yield from functions(node.left)
        yield from functions(node.right)
    elif isinstance(node, Unary):
        yield from functions(node.value)


def features(formula):
    result = set()
    try:
        tokens = Tokenizer(formula).items
        for token in tokens:
            if token.type == 'OPERAND':
                if token.subtype in {'TEXT', 'LOGICAL', 'ERROR'}:
                    result.add({'TEXT': 'text_literal', 'LOGICAL': 'logical_literal', 'ERROR': 'error_literal'}[token.subtype])
                if token.subtype == 'RANGE':
                    if '[' in token.value:
                        result.add('external_or_structured_reference')
                    elif not re.search(r'\$?[A-Za-z]{1,3}\$?\d+', token.value):
                        result.add('name_or_noncell_reference')
            if token.type == 'OPERATOR-POSTFIX' and token.value == '%':
                result.add('percent_operator')
            if token.type == 'OPERATOR-INFIX' and token.value == '&':
                result.add('concatenation_operator')
    except Exception as error:
        result.add('secondary_lexer_' + type(error).__name__)
    return sorted(result)


def classify(formula):
    try:
        node = parse_formula(formula)
        unsupported = sorted(set(functions(node)) - SUPPORTED_FUNCTIONS)
        return dict(status='parsed', unsupported_functions=unsupported)
    except ValueError as error:
        flags = features(formula)
        primary = next((f for f in ('error_literal', 'external_or_structured_reference', 'text_literal',
                                    'logical_literal', 'percent_operator', 'concatenation_operator',
                                    'name_or_noncell_reference') if f in flags), 'other_grammar')
        return dict(status='unsupported', primary=primary, features=flags, error=str(error))


def diagnose(source, output):
    if output.exists():
        raise SystemExit('Preserve existing diagnosis')
    prediction = json.loads(source.read_text())
    rows = {cell: classify(formula) for cell, formula in prediction['observed_formulas'].items()}
    with gzip.open(output, 'xt', encoding='utf-8') as handle:
        json.dump(dict(frozen_prediction_sha256=sha256(source), cells=rows, labels_read=[]),
                  handle, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def run():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != baseline['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    EXPERIMENT.mkdir(exist_ok=False)
    script = Path(__file__).resolve()
    sources = {str(p.relative_to(ROOT)): sha256(p) for p in (script, RUNNER, ROOT / 'MODEL_M4_SYNTAX_PLAN.md')}
    prelock = dict(created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   prediction_lock_sha256=sha256(EVIDENCE / 'prediction_lock.json'),
                   source_sha256=sources, workers=20)
    (EXPERIMENT / 'prelock.json').write_text(json.dumps(prelock, indent=2) + '\n')
    tasks = [dict(id=t['id'], argv=[sys.executable, str(script), '--frozen-prediction',
                  str(Path(t['cwd']) / 'prediction.json'), '--output', 'syntax.json.gz'],
                  outputs=['syntax.json.gz'], timeout_seconds=120)
             for t in baseline['full_runtime']['tasks'] if t['status'] == 'complete']
    manifest = EXPERIMENT / 'manifest.jsonl'
    manifest.write_text(''.join(json.dumps(t) + '\n' for t in tasks))
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(manifest), '--output-dir', str(EXPERIMENT / 'runs'),
                    '--workers', '20', '--worker-memory-mib', '256', '--timeout', '120'], cwd=ROOT, check=True)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if runtime['worker_count'] != 20 or len(runtime['tasks']) != 90 or not runtime['all_tasks_complete']:
        raise SystemExit('Syntax batch incomplete')
    if any(sha256(ROOT / p) != expected for p, expected in sources.items()):
        raise SystemExit('Source changed')
    outputs = []
    for task in runtime['tasks']:
        path = Path(task['cwd']) / 'syntax.json.gz'
        if sha256(path) != task['output_sha256']['syntax.json.gz']:
            raise SystemExit('Diagnosis output changed')
        outputs.append(dict(id=task['id'], path=str(path), sha256=sha256(path)))
    with (EXPERIMENT / 'output_lock.json').open('x') as handle:
        json.dump(dict(prelock_sha256=sha256(EXPERIMENT / 'prelock.json'),
                       manifest_sha256=sha256(manifest), runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'),
                       outputs=outputs, scoring_may_begin=True), handle, indent=2)
        handle.write('\n')
    print('M4 SYNTAX LOCKED', len(outputs), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--frozen-prediction', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.run:
        run()
    elif args.frozen_prediction and args.output:
        diagnose(args.frozen_prediction, args.output)
    else:
        parser.error('Choose --run or frozen prediction and output')


if __name__ == '__main__':
    main()
