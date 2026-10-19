#!/usr/bin/env python3
"""Single ablation: prefer an emitted SG suggestion over conflicting emitted FG."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys


def apply(trace):
    observed = trace['observed_formulas']
    paper = deepcopy(trace['paper'])
    switches = 0
    for row in paper['rows']:
        cell = row['cell']
        old = row.get('suggested_formula')
        fg = trace['fg_selected'].get(cell)
        sg = trace['sg_selected'].get(cell)
        if (row.get('suggestion_source') == 'formulaguard-v5'
                and isinstance(fg, str) and fg.startswith('=') and old == fg
                and fg != observed.get(cell) and isinstance(sg, str) and sg.startswith('=')
                and sg != observed.get(cell) and sg != fg):
            row.update(suggested_formula=sg, suggestion_source='m9-emitted-structuralguard',
                       m9_previous_formula=old, m9_decision='prefer_emitted_sg_on_fg_conflict')
            switches += 1
    return dict(observed_formulas=dict(observed), paper=paper, labels_read=[],
                model='paper-plus-m9-emitted-sg-priority', changed_selection_count=switches,
                final_validation_eligible=False, role='Revealed development; single fusion ablation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.trace.resolve(), args.output.resolve()
    if output.exists() or source == output:
        raise SystemExit('Output must be new and distinct')

    def guard(event, values):
        if event != 'open' or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path == source:
            mode, flags = values[1:3]
            if (isinstance(mode, str) and any(c in mode for c in 'wa+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError('Trace is read-only')
        elif (path.suffix.lower() in {'.xlsx', '.xls', '.xlsm', '.ods'} or 'scoring' in path.parts
                or any(marker in path.name.lower() for marker in ('golden', 'truth', 'candidate_differences'))):
            raise PermissionError('Workbook/scoring evidence access denied')

    sys.addaudithook(guard)
    raw = source.read_bytes()
    trace = json.loads(gzip.decompress(raw))
    result = apply(trace)
    result.update(trace_sha256=hashlib.sha256(raw).hexdigest(), input_sha256=trace['input_sha256'])
    with output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
