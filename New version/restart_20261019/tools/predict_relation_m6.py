#!/usr/bin/env python3
"""Paper candidate generation plus supplied-relation review of one target."""
import argparse
import json
import os
from pathlib import Path
import sys

from trace_paper_candidates import predict
from relation_candidates_m6 import review
from spreadsheetbench2_scoring import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    source, output = Path(request['workbook']).resolve(), args.output.resolve()
    if output.exists() or output in {source, args.request.resolve()} or sha256(source) != request['workbook_sha256']:
        raise SystemExit('Source hash must match; output must be new and distinct')

    def guard(event, values):
        if event != 'open' or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path == source:
            mode, flags = values[1:3]
            if (isinstance(mode, str) and any(c in mode for c in 'wa+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError('Original is read-only')
        elif path.suffix.lower() in {'.xlsx', '.xls', '.xlsm', '.ods'} or 'scoring' in path.parts or any(
                name in path.name.lower() for name in ('expected.json', 'golden', 'truth', 'after.xlsx')):
            raise PermissionError('Other workbook or scoring evidence access denied')

    sys.addaudithook(guard)
    paper = predict(source)
    cell = request['sheet'] + '!' + request['cell']
    observed = paper['observed_formulas'].get(cell)
    if observed is None:
        raise SystemExit('This mechanism requires an existing formula target')
    native = {p['formula'] for p in paper['candidate_trace']['fg'].get(cell, [])}
    native.update(p['formula'] for p in paper['candidate_trace']['sg'].get(cell, {}).get('candidates', []))
    target_row = next(r for r in paper['paper']['rows'] if r['cell'] == cell)
    if target_row.get('suggested_formula'):
        native.add(target_row['suggested_formula'])
    result = review(request, observed, sorted(native))
    if sha256(source) != request['workbook_sha256']:
        raise SystemExit('Source changed')
    result.update(request_sha256=sha256(args.request), workbook_sha256=sha256(source),
                  observed_formula=observed, paper_target_row=target_row,
                  unreviewed_paper_formula_rows=len(paper['paper']['rows']) - 1,
                  labels_read=[], original_unchanged=True,
                  relation_origin='Manually supplied business definition, not extracted from workbook')
    with output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
