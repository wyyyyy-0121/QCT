"""Bounded, business-agnostic single-edit candidates for revealed development.

This module generates hypotheses, not repair decisions. No header roles, peer
votes, expected formulas or business contracts are read. Even a unique candidate
in this grammar cannot establish correctness.
"""
from dataclasses import asdict
import json

from formulaguard.a1 import Address, parse_address
from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula, tokenize

VERSION = 'hybridguard-followup-candidates-dev1'
PARAMETERS = {
    'version': VERSION, 'max_candidates': 256, 'max_tokens': 512,
    'binary_operator_substitutions': ['+', '-', '*', '/'],
    'unary_sign_edits': True, 'numeric_scaling_operand_deletion': True,
    'reference_offsets': [[-1, 0], [1, 0], [0, -1], [0, 1]],
    'preserve_sheet_and_absolute_flags': True, 'multi_edit_search': False,
    'selection_authority': 'none; diagnostic candidate inventory only',
}


def structural_key(formula):
    """AST identity only, not algebraic/business equivalence; no simplification."""
    def encode(node):
        if isinstance(node, Number): return ['number', node.value]
        if isinstance(node, Ref): return ['ref', node.sheet, asdict(node.address)]
        if isinstance(node, Range): return ['range', encode(node.start), encode(node.end)]
        if isinstance(node, Unary): return ['unary', node.op, encode(node.value)]
        if isinstance(node, Binary): return ['binary', node.op, encode(node.left), encode(node.right)]
        if isinstance(node, Func): return ['func', node.name, [encode(arg) for arg in node.args]]
        raise TypeError(type(node))
    return json.dumps(encode(parse_formula(formula)), sort_keys=True, separators=(',', ':'))


def generate(formula):
    try:
        observed_key = structural_key(formula)
        tokens = tokenize(formula)[:-1]
    except (ValueError, TypeError, OverflowError) as error:
        return {'status': 'unsupported', 'reason': str(error), 'candidates': [],
                'search_truncated': False, 'selector_proposals': []}
    if len(tokens) > PARAMETERS['max_tokens']:
        return {'status': 'token_budget_exceeded', 'candidates': [], 'search_truncated': True,
                'selector_proposals': [], 'token_count': len(tokens)}
    text = formula[1:] if formula.startswith('=') else formula
    candidates = {}
    def add(start, end, replacement, kind, detail):
        candidate = '=' + text[:start] + replacement + text[end:]
        try:
            key = structural_key(candidate)
        except (ValueError, TypeError, OverflowError):
            return
        if key == observed_key:
            return
        evidence = {'kind': kind, 'span': [start, end], 'replacement': replacement, **detail}
        if key in candidates:
            candidates[key]['edits'].append(evidence)
        else:
            candidates[key] = {'formula': candidate, 'structural_key': key, 'edits': [evidence]}

    for i, token in enumerate(tokens):
        previous = tokens[i - 1] if i else None
        is_binary = previous is not None and (previous.kind in {'NUMBER', 'REF'} or previous.value == ')')
        if token.kind == 'OP' and token.value in {'+', '-', '*', '/'}:
            if is_binary:
                for op in PARAMETERS['binary_operator_substitutions']:
                    if op != token.value:
                        add(token.start, token.end, op, 'binary_operator_substitution',
                            {'from': token.value, 'to': op})
                # Delete only an adjacent literal scaling operand. Parenthesized
                # or composite factors are outside this single-token grammar.
                if token.value in {'*', '/'} and i + 1 < len(tokens) and tokens[i + 1].kind == 'NUMBER':
                    literal = tokens[i + 1]
                    # A literal immediately followed by ^ is a compound factor;
                    # deleting just its prefix would change unrelated syntax.
                    if i + 2 == len(tokens) or tokens[i + 2].value != '^':
                        add(token.start, literal.end, '', 'delete_right_literal_scale',
                            {'operator': token.value, 'literal': literal.value})
                if token.value == '*' and previous.kind == 'NUMBER':
                    # Do not remove a literal that is part of a preceding power
                    # or unary sign: that would edit more than one operand.
                    before_literal = tokens[i - 2] if i > 1 else None
                    if before_literal is None or before_literal.value not in {'^', '+', '-'}:
                        add(previous.start, token.end, '', 'delete_left_literal_scale',
                            {'literal': previous.value})
            elif token.value in {'+', '-'}:
                opposite = '+' if token.value == '-' else '-'
                add(token.start, token.end, opposite, 'unary_sign_substitution',
                    {'from': token.value, 'to': opposite})
                add(token.start, token.end, '', 'unary_sign_deletion', {'from': token.value})
        if token.kind == 'REF':
            pieces = token.value.rsplit('!', 1)
            prefix = pieces[0] + '!' if len(pieces) == 2 else ''
            address = parse_address(pieces[-1])
            for dr, dc in PARAMETERS['reference_offsets']:
                row, column = address.row + dr, address.col + dc
                if not (1 <= row <= 1048576 and 1 <= column <= 16384):
                    continue
                new = Address(row, column, address.row_abs, address.col_abs)
                add(token.start, token.end, prefix + new.a1, 'reference_offset',
                    {'row_offset': dr, 'column_offset': dc})
    all_candidates = sorted(candidates.values(), key=lambda c: (c['formula'], c['structural_key']))
    truncated = len(all_candidates) > PARAMETERS['max_candidates']
    return {'status': 'supported', 'token_count': len(tokens),
            'enumerated_unique_candidates': len(all_candidates),
            'candidates': all_candidates[:PARAMETERS['max_candidates']],
            'search_truncated': truncated, 'selector_proposals': [],
            'warning': 'Candidate availability is not repair precision or correct-repair coverage.'}
