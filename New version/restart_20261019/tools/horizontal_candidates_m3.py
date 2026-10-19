#!/usr/bin/env python3
"""Additional paper-native horizontal peer candidates; never select a repair."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'followup_20261014/baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.a1 import parse_address, num_to_col
from formulaguard.formula import parse_formula, translate_formula, iter_refs, Ref, Range
from spreadsheetbench2_scoring import sha256

RADIUS = 5
MIN_SUPPORT = 2


def candidate_is_safe(formula, cell):
    """Paper AST references, with explicit self-reference exclusion."""
    try:
        node = parse_formula(formula)
        address = parse_address(cell[1])
        for ref in iter_refs(node):
            if isinstance(ref, Ref):
                if ((ref.sheet or cell[0]).casefold() == cell[0].casefold()
                        and ref.address.row == address.row and ref.address.col == address.col):
                    return False
            elif isinstance(ref, Range):
                sheet = ref.start.sheet or ref.end.sheet or cell[0]
                if (sheet.casefold() == cell[0].casefold()
                        and min(ref.start.address.row, ref.end.address.row) <= address.row <= max(ref.start.address.row, ref.end.address.row)
                        and min(ref.start.address.col, ref.end.address.col) <= address.col <= max(ref.start.address.col, ref.end.address.col)):
                    return False
        return True
    except ValueError:
        return False


def generate(observed):
    pool = {}
    statuses = Counter()
    for label, original in observed.items():
        sheet, target = label.rsplit('!', 1)
        try:
            parse_formula(original)
        except ValueError:
            statuses['original_parse_unsupported'] += 1
            continue
        address = parse_address(target)
        proposals = defaultdict(list)
        for distance in range(1, RADIUS + 1):
            for col in (address.col - distance, address.col + distance):
                if not 1 <= col <= 16384:
                    continue
                source = num_to_col(col) + str(address.row)
                formula = observed.get(sheet + '!' + source)
                if formula is None:
                    continue
                try:
                    candidate = translate_formula(formula, source, target)
                except ValueError:
                    continue
                if candidate != original and candidate_is_safe(candidate, (sheet, target)):
                    proposals[candidate].append(sheet + '!' + source)
        supported = [dict(formula=formula, peer_support=len(sources), source_cells=sources,
                          origin='horizontal_peer_translation')
                     for formula, sources in sorted(proposals.items()) if len(sources) >= MIN_SUPPORT]
        if supported:
            pool[label] = supported
            statuses['target_with_candidates'] += 1
        else:
            statuses['no_supported_changed_candidate'] += 1
    return dict(candidate_pool=pool, target_status_counts=statuses,
                automatic_edit_applied=False, selected_repairs=[], labels_read=[],
                parameters=dict(radius=RADIUS, minimum_support=MIN_SUPPORT),
                role='Candidate generation only; not a repair prediction')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-prediction', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Preserve existing outputs')
    prediction = json.loads(args.frozen_prediction.read_text())
    result = generate(prediction['observed_formulas'])
    result['frozen_prediction_sha256'] = sha256(args.frozen_prediction)
    with gzip.open(args.output, 'xt', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


if __name__ == '__main__':
    main()
