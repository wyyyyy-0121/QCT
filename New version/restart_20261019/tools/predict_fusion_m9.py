#!/usr/bin/env python3
"""Run original paper from real workbook, then apply frozen M9 priority ablation."""
import argparse
import json
import os
from pathlib import Path
import sys

from fusion_priority_m9 import apply
from spreadsheetbench2_scoring import sha256
from trace_paper_candidates import predict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.input.resolve(), args.output.resolve()
    if output.exists() or output == source or source.suffix.lower() != '.xlsx':
        raise SystemExit('Read-only xlsx input and new distinct output required')
    before = sha256(source)

    def guard(event, values):
        if event != 'open' or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path == source:
            mode, flags = values[1:3]
            if (isinstance(mode, str) and any(c in mode for c in 'wa+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError('Original is read-only')
        elif (path.suffix.lower() in {'.xlsx', '.xls', '.xlsm', '.ods', '.properties'}
                or 'scoring' in path.parts or 'configuration_files' in path.parts
                or any(marker in path.name.lower() for marker in ('golden', 'truth', 'score_inventory', 'expected.json'))):
            raise PermissionError('Other workbook/label evidence access denied')
        elif path.name == 'prediction.json' and path != output:
            raise PermissionError('Frozen predictions are not inference inputs')

    sys.addaudithook(guard)
    trace = predict(source)
    result = apply(trace)
    result.update(original_paper=trace['paper'], input_sha256=before, original_unchanged=sha256(source) == before,
                  fg_selected=trace['fg_selected'], sg_selected=trace['sg_selected'],
                  inference_mode='Real workbook; original paper followed by unchanged M9 priority')
    if not result['original_unchanged']:
        raise SystemExit('Source changed')
    with output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
