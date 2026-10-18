"""Bounded hypotheses and observable reference features; never read repair labels."""
from collections import Counter
from functools import lru_cache
from numbers import Real

from formulaguard.a1 import parse_address, num_to_col
from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula
from formula_candidates_dev1 import generate, structural_key

VERSION = 'hybridguard-candidate-expansion-dev18-v1'

@lru_cache(maxsize=100000)
def expansion(formula):
    return generate(formula)

@lru_cache(maxsize=100000)
def ast_key(formula):
    try:
        return structural_key(formula)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None

def extend(observed, old):
    """old is a formula->origins mapping from label-free upstream predictions."""
    pool = {f: set(origins) for f, origins in old.items()}
    keys = {ast_key(f) for f in pool} - {None}
    result = expansion(observed)
    for c in result['candidates']:
        if c['structural_key'] in keys:
            continue
        keys.add(c['structural_key'])
        pool.setdefault(c['formula'], set()).add('single_edit')
    return pool, {k: v for k, v in result.items() if k not in ['candidates', 'selector_proposals', 'warning']}

@lru_cache(maxsize=100000)
def references(formula):
    """Reference occurrences, with a per-range cap; no upstream formula expansion."""
    refs = []; ranges = truncated = 0
    pending = [parse_formula(formula)]
    while pending:
        n = pending.pop()
        if isinstance(n, Ref):
            refs.append((n.sheet, n.address.row, n.address.col))
        elif isinstance(n, Range):
            ranges += 1
            r1, r2 = sorted([n.start.address.row, n.end.address.row])
            c1, c2 = sorted([n.start.address.col, n.end.address.col])
            count = (r2-r1+1)*(c2-c1+1)
            truncated += count > 256
            for i in range(min(count, 256)):
                refs.append((n.start.sheet or n.end.sheet, r1+i//(c2-c1+1), c1+i%(c2-c1+1)))
        elif isinstance(n, Binary):
            pending.extend([n.left, n.right])
        elif isinstance(n, Unary):
            pending.append(n.value)
        elif isinstance(n, Func):
            pending.extend(n.args)
        elif not isinstance(n, Number):
            raise ValueError('unknown_ast')
    return tuple(refs), ranges, truncated

def reference_features(model, sheet, address, formula):
    names = ['parse_failed', 'range_count', 'range_truncated', 'ref_occurrences', 'self_ref',
             'same_row', 'same_column', 'above', 'below', 'left', 'right', 'other_sheet',
             'row_distance_mean', 'column_distance_mean', 'formula', 'number', 'text',
             'blank', 'boolean', 'other']
    out = dict.fromkeys(names, 0.)
    try:
        refs, ranges, truncated = references(formula)
    except (ValueError, TypeError, OverflowError, RecursionError):
        out['parse_failed'] = 1.
        return out
    pos = parse_address(address)
    out.update(range_count=ranges, range_truncated=truncated, ref_occurrences=len(refs))
    for s, r, c in refs:
        s = s or sheet; key = (s, num_to_col(c)+str(r))
        if s != sheet:
            out['other_sheet'] += 1
        else:
            out['self_ref'] += key == (sheet, address)
            dr, dc = r-pos.row, c-pos.col
            for name, value in [('same_row', dr == 0), ('same_column', dc == 0),
                                ('above', dr < 0), ('below', dr > 0),
                                ('left', dc < 0), ('right', dc > 0)]:
                out[name] += value
            # Cap distances; absolute workbook coordinates never enter the vector.
            out['row_distance_mean'] += min(abs(dr), 256)
            out['column_distance_mean'] += min(abs(dc), 256)
        value = model.cells.get(key)
        kind = ('formula' if key in model.formulas else 'blank' if value is None else
                'boolean' if isinstance(value, bool) else 'number' if isinstance(value, Real) else
                'text' if isinstance(value, str) else 'other')
        out[kind] += 1
    for name in ['row_distance_mean', 'column_distance_mean']:
        out[name] /= max(1, len(refs))
    return out

def extra_features(model, sheet, address, observed, candidate, origins):
    old = reference_features(model, sheet, address, observed)
    new = reference_features(model, sheet, address, candidate)
    return {**{'ref_old_'+k: v for k, v in old.items()},
            **{'ref_new_'+k: v for k, v in new.items()},
            **{'ref_delta_'+k: new[k]-old[k] for k in old},
            'origin_single_edit': float('single_edit' in origins)}
