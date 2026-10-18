"""Experimental reference-only consensus; agreement does not establish intent."""
from decimal import Decimal
from functools import lru_cache

from openpyxl.formula.translate import Translator, TranslatorError
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula, iter_refs
from selector_dev11 import syntax_evidence

VERSION = 'hybridguard-bidirectional-reference-dev13-v1'
PARAMETERS = {'distances': [-2, -1, 1, 2], 'minimum_axis_peers': 2,
              'edit': 'one reference row or column only', 'adopted': False}


@lru_cache(maxsize=200000)
def supported_ast(formula):
    if not syntax_evidence(formula)['supported']:
        return None
    return parse_formula(formula)


def reference_difference(a, b):
    """Return the changed reference count, or None for any other AST change."""
    if type(a) is not type(b):
        return None
    if isinstance(a, Ref):
        x, y = a.address, b.address
        if (a.sheet, x.row_abs, x.col_abs) != (b.sheet, y.row_abs, y.col_abs):
            return None
        if x.row != y.row and x.col != y.col:
            return None
        return int((x.row, x.col) != (y.row, y.col))
    if isinstance(a, Number):
        return 0 if Decimal(a.source_text) == Decimal(b.source_text) else None
    if isinstance(a, Range):
        pairs = [(a.start, b.start), (a.end, b.end)]
    elif isinstance(a, Unary) and a.op == b.op:
        pairs = [(a.value, b.value)]
    elif isinstance(a, Binary) and a.op == b.op:
        pairs = [(a.left, b.left), (a.right, b.right)]
    elif isinstance(a, Func) and a.name == b.name and len(a.args) == len(b.args):
        pairs = list(zip(a.args, b.args))
    else:
        return None
    counts = [reference_difference(x, y) for x, y in pairs]
    return None if any(n is None for n in counts) else sum(counts)


def references_target(ast, sheet, row, col):
    def same_sheet(name):
        return name is None or name.casefold() == sheet.casefold()
    for ref in iter_refs(ast):
        if isinstance(ref, Ref):
            if same_sheet(ref.sheet) and (ref.address.row, ref.address.col) == (row, col):
                return True
        elif same_sheet(ref.start.sheet) and same_sheet(ref.end.sheet or ref.start.sheet):
            if (min(ref.start.address.row, ref.end.address.row) <= row <= max(ref.start.address.row, ref.end.address.row)
                    and min(ref.start.address.col, ref.end.address.col) <= col <= max(ref.start.address.col, ref.end.address.col)):
                return True
    return False


def axis_candidate(formulas, sheet, address, row, col, axis):
    peers = []
    trees = []
    for distance in PARAMETERS['distances']:
        r, c = (row + distance, col) if axis == 'column' else (row, col + distance)
        if not (1 <= r <= 1048576 and 1 <= c <= 16384):
            continue
        peer = f'{get_column_letter(c)}{r}'
        formula = formulas.get((sheet, peer))
        if formula is None:
            continue
        ast = supported_ast(formula)
        if ast is None or references_target(ast, sheet, row, col):
            return None
        try:
            translated = Translator(formula, origin=peer).translate_formula(address)
        except (ValueError, TranslatorError):
            return None
        tree = supported_ast(translated)
        if tree is None:
            return None
        peers.append({'cell': sheet+'!'+peer, 'translated_formula': translated})
        trees.append(tree)
    if len(peers) < PARAMETERS['minimum_axis_peers']:
        return None
    if not all(reference_difference(trees[0], other) == 0 for other in trees[1:]):
        return None
    tree = trees[0]
    original = supported_ast(formulas[(sheet, address)])
    if original is None or reference_difference(original, tree) != 1:
        return None
    if references_target(tree, sheet, row, col):
        return None
    return {'formula': peers[0]['translated_formula'], 'peers': peers,
            'business_correctness_proven': False}


def candidates(formulas):
    result = {'both': {}, 'row_only': {}, 'column_only': {}}
    for (sheet, address), formula in sorted(formulas.items()):
        if supported_ast(formula) is None:
            continue
        row, col = coordinate_to_tuple(address)
        axes = {axis: axis_candidate(formulas, sheet, address, row, col, axis)
                for axis in ('row', 'column')}
        label = sheet+'!'+address
        for axis in ('row', 'column'):
            if axes[axis] is not None:
                result[axis+'_only'][label] = axes[axis]
        if all(axes.values()) and reference_difference(
                supported_ast(axes['row']['formula']), supported_ast(axes['column']['formula'])) == 0:
            result['both'][label] = {
                'formula': axes['row']['formula'], 'axes': axes,
                'business_correctness_proven': False}
    return result


def merge(prior, additional):
    # Only the scoring experiment uses this view; no production model changes.
    result = {'rows': []}
    for old in prior['rows']:
        row = dict(old)
        extra = additional.get(row['cell'])
        if extra is not None and row.get('status') != 'propose':
            row.update(status='propose', suggested_formula=extra['formula'],
                       reason='experimental_reference_consensus', selector_version=VERSION)
        result['rows'].append(row)
    return result
