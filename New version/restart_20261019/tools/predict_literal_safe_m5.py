#!/usr/bin/env python3
"""Paper inference with literal-safe transforms; original workbook is read-only."""
import argparse
import json
import os
from pathlib import Path
import sys

from trace_paper_candidates import predict
from literal_safe_candidates import literal_safe_paper
from spreadsheetbench2_scoring import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.input.resolve(), args.output.resolve()
    if not source.is_file() or source == output or output.exists():
        raise SystemExit('Source must exist; output must be new and distinct')
    before = sha256(source)

    def guard(event, values):
        if event != 'open' or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path == source:
            mode, flags = values[1:3]
            if (isinstance(mode, str) and any(c in mode for c in 'wa+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError('Workbook is read-only')
        elif path.suffix.lower() in {'.xlsx', '.xls', '.xlsm', '.ods'} or 'scoring' in path.parts or any(
                x in path.name.lower() for x in ('golden', 'truth', 'expected.json', 'dataset.json', 'candidate_differences')):
            raise PermissionError('Other workbooks and scoring evidence are forbidden')

    sys.addaudithook(guard)
    with literal_safe_paper():
        predicted = predict(source)
    if sha256(source) != before:
        raise SystemExit('Source changed')
    result = {key: predicted[key] for key in ('paper', 'observed_formulas')}
    result.update(input_sha256=before, original_unchanged=True, labels_read=[],
                  model='paper-plus-m5-literal-protection', status='complete',
                  final_validation_eligible=False)
    with output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
