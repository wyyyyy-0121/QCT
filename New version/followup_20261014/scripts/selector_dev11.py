"""Require supported complete ASTs before a dev6 proposal can be emitted.

This repairs a qualification defect; successful parsing is not business proof.
Names, strings and unsupported functions need future semantic implementations,
not majority-based replacement with another formula. Historical selectors stay
unchanged. This gate cannot infer hidden intent or recover coefficient misses.
"""
from copy import deepcopy

from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula
from selector_dev6 import augment as dev6_augment

VERSION = 'hybridguard-followup-selector-dev11-complete-ast-gate-v1'
PARAMETERS = {
    'max_formula_characters': 8192, 'max_ast_nodes': 512,
    'binary_operators': ['+', '-', '*', '/', '^', '=', '<>', '<', '>', '<=', '>='],
    'supported_functions': ['SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT', 'IF'],
    'business_authority_from_parsing': False,
}


def syntax_evidence(formula):
    if not isinstance(formula, str) or not formula.startswith('='):
        return {'supported': False, 'reason': 'missing_formula'}
    if len(formula) > PARAMETERS['max_formula_characters']:
        return {'supported': False, 'reason': 'formula_budget'}
    try:
        pending = [parse_formula(formula)]
        count = 0
        while pending:
            node = pending.pop()
            count += 1
            if count > PARAMETERS['max_ast_nodes']:
                return {'supported': False, 'reason': 'ast_budget'}
            if isinstance(node, Number):
                continue
            if isinstance(node, Ref):
                if not (1 <= node.address.row <= 1048576 and 1 <= node.address.col <= 16384):
                    return {'supported': False, 'reason': 'reference_outside_excel_grid'}
                continue
            if isinstance(node, Range):
                pending.extend([node.start, node.end])
                continue
            if isinstance(node, Unary) and node.op in ('+', '-'):
                pending.append(node.value)
                continue
            if isinstance(node, Binary) and node.op in PARAMETERS['binary_operators']:
                pending.extend([node.left, node.right])
                continue
            if isinstance(node, Func):
                if node.name not in PARAMETERS['supported_functions']:
                    return {'supported': False, 'reason': 'unsupported_function', 'function': node.name}
                if node.name == 'IF' and len(node.args) not in (2, 3):
                    return {'supported': False, 'reason': 'unsupported_function_arity'}
                if node.name in ('MIN', 'MAX', 'AVERAGE') and not node.args:
                    return {'supported': False, 'reason': 'unsupported_function_arity'}
                pending.extend(node.args)
                continue
            return {'supported': False, 'reason': 'unsupported_ast_node'}
        return {'supported': True, 'reason': 'complete_supported_ast', 'nodes': count,
                'business_correctness_proven': False}
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        return {'supported': False, 'reason': 'unsupported_formula_syntax',
                'error_type': type(error).__name__}


def qualify(model, prediction):
    result = deepcopy(prediction)
    blocked = 0
    for row in result['rows']:
        if row.get('status') != 'propose':
            continue
        key = tuple(row['cell'].rsplit('!', 1))
        evidence = {'original': syntax_evidence(model.formulas.get(key)),
                    'candidate': syntax_evidence(row.get('suggested_formula')),
                    'business_authority_from_parsing': False}
        row['complete_ast_gate'] = evidence
        if not all(evidence[k]['supported'] for k in ['original', 'candidate']):
            row['suppressed_proposal'] = {
                'formula': row.get('suggested_formula'), 'reason': row.get('reason'),
                'source_selector': row.get('selector_version')}
            row.update(status='review', suggested_formula=None, candidate_formula=None,
                       reason='complete_semantic_parse_required')
            blocked += 1
        row['selector_version'] = VERSION
    result['selector'] = VERSION
    result['complete_ast_gate_summary'] = {'blocked_proposals': blocked,
                                         'remaining_proposals': sum(r.get('status') == 'propose' for r in result['rows']),
                                         'final_validation_eligible': False}
    return result


def augment(model, prior, parallel_sheets):
    return qualify(model, dev6_augment(model, prior, parallel_sheets))
