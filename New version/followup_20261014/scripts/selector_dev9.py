"""Measure a bounded coefficient-outlier hypothesis above immutable dev6.

Repeated peers are correlated candidate evidence, not proof of business intent.
This experiment deliberately measures that risk on ALL revealed controls.
No label, case id, source path or cached result enters selection.
"""
from collections import defaultdict
from functools import lru_cache
import math

from formulaguard.a1 import parse_address
from formulaguard.formula import Binary, Number, Ref, Unary, parse_formula
from selector_dev5 import header_index, policy_scopes
from selector_dev6 import augment as dev6_augment

VERSION = 'hybridguard-followup-selector-dev9-peer-scalar-v1'
PARAMETERS = {
    'minimum_peer_support': 2,
    'majority': 'strictly more than half of all present same-address peers',
    'difference': 'exactly one positive multiplicative literal insert/remove/replace',
    'headers': 'exact nearest visible output and precedent headers',
    'policy_guard': 'target and candidate peer scopes',
    'existing_proposals': 'preserve dev6',
    'independent_business_authorization': False,
    'final_validation_eligible': False,
}


@lru_cache(maxsize=32768)
def arithmetic(formula):
    node = parse_formula(formula)
    def valid(n):
        if isinstance(n, Number):
            return math.isfinite(n.value)
        if isinstance(n, Ref):
            return n.sheet is None
        if isinstance(n, Unary):
            return n.op in ('+', '-') and valid(n.value)
        if isinstance(n, Binary):
            return n.op in ('+', '-', '*', '/') and valid(n.left) and valid(n.right)
        return False
    if not valid(node):
        raise ValueError('unsupported arithmetic or explicitly qualified reference')
    return node


def positive_literal(node):
    return isinstance(node, Number) and math.isfinite(node.value) and node.value > 0


def scalar_difference(left, right):
    """Return one for exactly one supported scalar AST edit; otherwise zero."""
    def edits(a, b, scalar_position=False):
        if a == b:
            return 0
        if scalar_position and positive_literal(a) and positive_literal(b):
            return 1
        for outer, inner in ((a, b), (b, a)):
            if isinstance(outer, Binary) and outer.op == '*':
                if positive_literal(outer.left) and outer.left.value != 1 and outer.right == inner:
                    return 1
                if positive_literal(outer.right) and outer.right.value != 1 and outer.left == inner:
                    return 1
            if (isinstance(outer, Binary) and outer.op == '/'
                    and positive_literal(outer.right) and outer.right.value != 1
                    and outer.left == inner):
                return 1
        if isinstance(a, Binary) and isinstance(b, Binary) and a.op == b.op:
            # A literal is a scale only when it is an operand of * or a divisor.
            l = edits(a.left, b.left, a.op == '*')
            r = edits(a.right, b.right, a.op in ('*', '/'))
            return l + r
        if isinstance(a, Unary) and isinstance(b, Unary) and a.op == b.op:
            return edits(a.value, b.value)
        return 1000
    return edits(left, right) == 1


def reference_columns(node):
    if isinstance(node, Ref):
        return {node.address.col}
    if isinstance(node, Unary):
        return reference_columns(node.value)
    if isinstance(node, Binary):
        return reference_columns(node.left) | reference_columns(node.right)
    return set()


def header_signature(index, sheet, address, node):
    target = parse_address(address)
    signature = []
    for col in sorted(reference_columns(node) | {target.col}):
        preceding = [(row, text) for row, text in index.get((sheet, col), [])
                     if row < target.row]
        if not preceding:
            return None
        signature.append((col, preceding[-1]))
    return tuple(signature)


def blocked(scopes, sheet, address):
    scope = scopes.get(sheet, {})
    return scope.get('opaque', False) or parse_address(address).row in scope.get('rows', [])


def extend(model, base, parallel_sheets):
    """Pure extension; exposing this boundary permits meaningful preservation tests."""
    index, scopes = header_index(model), policy_scopes(model)
    positions = defaultdict(list)
    for (sheet, address), formula in model.formulas.items():
        if sheet in parallel_sheets:
            positions[address].append((sheet, formula))
    rows = []
    for original in base['rows']:
        row = dict(original)
        sheet, address = row['cell'].rsplit('!', 1)
        if (row.get('status') == 'propose' or sheet not in parallel_sheets
                or not model.is_visible((sheet, address)) or blocked(scopes, sheet, address)):
            rows.append(row)
            continue
        actual = model.formulas[sheet, address]
        peers = [(s, f) for s, f in positions[address] if s != sheet]
        if len(peers) < PARAMETERS['minimum_peer_support'] or all(f == actual for _, f in peers):
            rows.append(row)
            continue
        try:
            node = arithmetic(actual)
            signature = header_signature(index, sheet, address, node)
        except ValueError:
            rows.append(row)
            continue
        if signature is None or not reference_columns(node):
            rows.append(row)
            continue
        pool = defaultdict(list)
        texts = {}
        for peer_sheet, candidate in peers:
            if blocked(scopes, peer_sheet, address) or not model.is_visible((peer_sheet, address)):
                continue
            try:
                candidate_node = arithmetic(candidate)
                if (not scalar_difference(node, candidate_node)
                        or signature != header_signature(index, peer_sheet, address, candidate_node)):
                    continue
            except ValueError:
                continue
            pool[candidate_node].append(peer_sheet)
            texts.setdefault(candidate_node, candidate)
        qualified = [(n, support) for n, support in pool.items()
                     if len(support) >= PARAMETERS['minimum_peer_support']
                     and len(support) * 2 > len(peers)]
        if len(qualified) == 1:
            candidate_node, support = qualified[0]
            candidate = texts[candidate_node]
            row.update(status='propose', suggested_formula=candidate, candidate_formula=candidate,
                       selector_version=VERSION, reason='repeated_peer_single_scalar_hypothesis',
                       selection_evidence=[{
                           'kind': 'bounded_peer_scalar_hypothesis', 'peer_sheets': sorted(support),
                           'all_present_peers': len(peers), 'header_signature_equal': True,
                           'one_positive_scalar_edit': True, 'independent_business_proof': False,
                       }])
        rows.append(row)
    return {**base, 'rows': rows, 'selector_version': VERSION,
            'dev9_parameters': PARAMETERS, 'automatic_edit_applied': False,
            'limitations': list(base.get('limitations', [])) + [
                'Scalar majority may erase legitimate undocumented business exceptions.',
                'This is a revealed-development hypothesis, not verified business intent.',
            ]}


def augment(model, prior, parallel_sheets):
    return extend(model, dev6_augment(model, prior, parallel_sheets), parallel_sheets)
