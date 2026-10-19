#!/usr/bin/env python3
"""Experimental paper-candidate filter. No labels, workbooks or scoring imports."""
import argparse
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from openpyxl.formula import Tokenizer
from openpyxl.formula.translate import Translator, TranslatorError
from openpyxl.utils.cell import get_column_letter, coordinate_to_tuple, range_boundaries

CELL = r'\$?[A-Za-z]{1,3}\$?[1-9][0-9]*'
SHEET = r"(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!"
REFERENCE = re.compile(rf'(?:{SHEET})?{CELL}(?::{CELL})?\Z')


@lru_cache(maxsize=32768)
def simple_references(formula):
    """Whitelist ordinary A1 operands; reject names and unsupported syntax."""
    if not isinstance(formula, str) or not formula.startswith('='):
        return None
    try:
        tokens = Tokenizer(formula).items
        refs = []
        for token in tokens:
            if token.type == 'OPERAND' and token.subtype == 'ERROR':
                return None
            if token.type == 'OPERAND' and token.subtype == 'RANGE':
                if not REFERENCE.fullmatch(token.value):
                    return None
                refs.append(token.value)
        return tuple(refs) if refs else None
    except (ValueError, IndexError, TranslatorError):
        return None


def direct_self_reference(refs, sheet, address):
    row, col = coordinate_to_tuple(address)
    for ref in refs:
        if '!' in ref:
            name, area = ref.rsplit('!', 1)
            name = name[1:-1].replace("''", "'") if name.startswith("'") else name
            if name.casefold() != sheet.casefold():
                continue
        else:
            area = ref
        c1, r1, c2, r2 = range_boundaries(area)
        if r1 <= row <= r2 and c1 <= col <= c2:
            return True
    return False


def translated(formula, origin, target):
    if simple_references(formula) is None:
        return None
    try:
        result = Translator(formula, origin=origin).translate_formula(target)
        return result if simple_references(result) is not None else None
    except (ValueError, IndexError, TranslatorError):
        return None


def gate_row(row, observed):
    candidate, cell = row.get('suggested_formula'), row['cell']
    if not isinstance(candidate, str) or not candidate.startswith('=') or candidate == observed.get(cell):
        return False, 'no_changed_candidate'
    refs = simple_references(candidate)
    if refs is None:
        return False, 'unsupported_candidate'
    sheet, address = cell.rsplit('!', 1)
    if direct_self_reference(refs, sheet, address):
        return False, 'direct_self_reference'
    r, c = coordinate_to_tuple(address)
    axes = []
    for coords in (((r, c-1), (r, c+1)), ((r-1, c), (r+1, c))):
        if any(not (1 <= rr <= 1048576 and 1 <= cc <= 16384) for rr, cc in coords):
            continue
        neighbors = [get_column_letter(cc) + str(rr) for rr, cc in coords]
        proposals = [translated(observed.get(sheet + '!' + source), source, address)
                     for source in neighbors]
        if proposals[0] is not None and proposals[0] == proposals[1]:
            axes.append(proposals[0])
    if len(set(axes)) > 1:
        return False, 'axis_conflict'
    if not axes:
        return False, 'no_bilateral_support'
    if candidate != axes[0]:
        return False, 'paper_candidate_disagrees'
    return True, 'bilateral_support'


def filter_prediction(prediction):
    observed = prediction['observed_formulas']
    rows = []
    for row in prediction['paper']['rows']:
        accepted, reason = gate_row(row, observed)
        changed = deepcopy(row)
        changed['m1_decision'] = reason
        if not accepted:
            changed['suggested_formula'] = None
        rows.append(changed)
    return {'observed_formulas': observed.copy(), 'paper': {'rows': rows},
            'model': 'paper-plus-m1-bilateral-gate', 'labels_read': [],
            'role': 'Revealed-development candidate filter; not business certification'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-prediction', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() == args.frozen_prediction.resolve():
        raise SystemExit('Output must be new and distinct')
    source = args.frozen_prediction.read_bytes()
    result = filter_prediction(json.loads(source))
    result['frozen_prediction_sha256'] = hashlib.sha256(source).hexdigest()
    with args.output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
