"""Explicit visible reconciliation experiment; declarations are unverified input.

This is a controlled development hypothesis, not a correctness certificate.
Numeric agreement cannot establish provenance or distinguish all formulas.
No truth, expected-formula dictionary, filename or case identifier is used.
"""
from collections import Counter
from copy import deepcopy
import math
import re

from formulaguard.a1 import plain_address
from formulaguard.formula import Binary, Number, Ref, Unary, parse_formula
from formula_candidates_dev1 import generate, structural_key
from selector_dev11 import qualify, syntax_evidence

VERSION = 'hybridguard-followup-dev12-explicit-reconciliation-v1'
PARAMETERS = {'maximum_declarations': 256, 'maximum_expression_chars': 1024,
              'maximum_expression_nodes': 128, 'maximum_control_closure': 2048,
              'candidate_search': 'frozen single-edit inventory plus prior suggestion',
              'selection': 'exactly one structural candidate satisfies every declaration',
              'provenance_verified': False, 'final_validation_eligible': False}
PATTERN = re.compile(
    r'Reconciliation: target=([A-Za-z]{1,3}[1-9][0-9]*); '
    r'expression=(.+); expected=([-+0-9.eE]+); tolerance=([-+0-9.eE]+)\.',
    re.IGNORECASE)


def references(formula, sheet):
    """Bounded arithmetic AST only; missing references never silently become 0."""
    if not isinstance(formula, str) or len(formula) > PARAMETERS['maximum_expression_chars']:
        raise ValueError('expression budget')
    refs = []
    pending, count = [parse_formula(formula)], 0
    while pending:
        node = pending.pop(); count += 1
        if count > PARAMETERS['maximum_expression_nodes']:
            raise ValueError('expression node budget')
        if isinstance(node, Number):
            if not math.isfinite(node.value):
                raise ValueError('nonfinite literal')
        elif isinstance(node, Ref):
            if not (1 <= node.address.row <= 1048576 and 1 <= node.address.col <= 16384):
                raise ValueError('grid boundary')
            refs.append((node.sheet or sheet, plain_address(node.address.a1)))
        elif isinstance(node, Unary) and node.op in ('+', '-'):
            pending.append(node.value)
        elif isinstance(node, Binary) and node.op in ('+', '-', '*', '/'):
            pending.extend([node.left, node.right])
        else:
            raise ValueError('reconciliation supports bounded scalar arithmetic only')
    return refs


def declarations(model):
    result = []
    visible = sorted((k, v) for k, v in model.cells.items()
                     if k not in model.formulas and model.is_visible(k)
                     and isinstance(v, str) and v.strip().casefold().startswith('reconciliation:'))
    for key, text in visible:
        row = {'source_cell': '!'.join(key), 'declaration': text, 'valid': False}
        hint = re.search(r'target=([A-Za-z]{1,3}[1-9][0-9]*)', text, re.IGNORECASE)
        row['target'] = (key[0], plain_address(hint.group(1))) if hint else None
        try:
            if len(visible) > PARAMETERS['maximum_declarations']:
                raise ValueError('declaration budget')
            match = PATTERN.fullmatch(text.strip())
            if not match:
                raise ValueError('incomplete controlled declaration')
            target, expression, expected, tolerance = match.groups()
            target = key[0], plain_address(target)
            if target not in model.formulas or not model.is_visible(target):
                raise ValueError('target is not a visible formula')
            expected, tolerance = float(expected), float(tolerance)
            if not all(math.isfinite(x) for x in (expected, tolerance)) or tolerance < 0:
                raise ValueError('invalid expectation or tolerance')
            expression = expression if expression.startswith('=') else '=' + expression
            refs = references(expression, key[0])
            if refs.count(target) != 1:
                raise ValueError('target must occur directly exactly once')
            controls = set(refs) - {target}
            if not controls:
                raise ValueError('no independently recorded control')
            row.update(target=target, expression=expression, expected=expected,
                       tolerance=tolerance, controls=sorted(controls), valid=True)
        except (ValueError, TypeError, OverflowError, RecursionError) as error:
            row['reason'] = str(error)
        result.append(row)
    return result


def closure(model, start, forbidden):
    pending, seen = [start], set()
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        if key == forbidden:
            raise ValueError('control depends on target')
        seen.add(key)
        if len(seen) > PARAMETERS['maximum_control_closure']:
            raise ValueError('control dependency budget')
        if key not in model.cells and key not in model.formulas:
            raise ValueError('missing control or precedent')
        if not model.is_visible(key):
            raise ValueError('hidden control or precedent')
        if key in model.formulas:
            pending.extend(references(model.formulas[key], key[0]))
        else:
            numeric(model.cells[key])
    return seen


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('control or result is not finite numeric')
    return float(value)


def evaluate_expression(model, sheet, expression, overrides):
    # A temporary evaluator target is supplied by override, never written to cells.
    probe = sheet, 'XFD1048576'
    if probe in model.cells or probe in model.formulas or probe in references(expression, sheet):
        raise ValueError('reserved evaluator address is occupied')
    values, errors = model.evaluate(overrides={**overrides, probe: expression}, targets=[probe])
    if errors or probe not in values:
        raise ValueError('formula evaluation failed')
    return numeric(values[probe])


def constraint_results(model, target, specs, formula):
    values = []
    for spec in specs:
        value = evaluate_expression(model, target[0], spec['expression'], {target: formula})
        values.append({'source_cell': spec['source_cell'], 'value': value,
                       'expected': spec['expected'], 'tolerance': spec['tolerance'],
                       'satisfied': abs(value-spec['expected']) <= spec['tolerance']})
    return values


def apply(model, prior):
    """Use workbook-visible numeric assertions; never modify workbook or prior."""
    result = deepcopy(prior)
    specs = declarations(model)
    if not specs:
        result['reconciliation_summary'] = {'declarations': 0, 'changed_decisions': 0,
                                            'final_validation_eligible': False}
        return result
    by_target = {}
    for spec in specs:
        if spec['target']:
            by_target.setdefault(tuple(spec['target']), []).append(spec)
    unknown_sheets = {s['source_cell'].rsplit('!', 1)[0] for s in specs if not s['target']}
    changed, reasons = 0, Counter()
    for row in result['rows']:
        target = tuple(row['cell'].rsplit('!', 1))
        relevant = by_target.get(target, [])
        if not relevant and target[0] not in unknown_sheets:
            continue
        before = row.get('status'), row.get('suggested_formula')
        prior_candidate = row.get('suggested_formula')
        if prior_candidate:
            row['reconciliation_prior_suggestion'] = prior_candidate
        row.update(status='review', suggested_formula=None, candidate_formula=None,
                   selector_version=VERSION)
        diagnostic = {'declaration_cells': [s['source_cell'] for s in relevant],
                      'control_provenance_verified': False,
                      'formula_identity_proven_by_numeric_agreement': False}
        row['reconciliation'] = diagnostic
        try:
            if target[0] in unknown_sheets or not relevant or not all(s['valid'] for s in relevant):
                raise ValueError('invalid_or_unscoped_declaration')
            original = model.formulas[target]
            if not syntax_evidence(original)['supported']:
                raise ValueError('unsupported_original')
            original_refs = references(original, target[0])
            controls = set()
            for spec in relevant:
                for control in spec['controls']:
                    controls.update(closure(model, tuple(control), target))
            # Check output inputs too; the original evaluator otherwise defaults blanks to 0.
            output_inputs = set()
            for ref in original_refs:
                output_inputs.update(closure(model, ref, target))
            if controls & output_inputs:
                raise ValueError('control_and_output_share_precedents')
            current = constraint_results(model, target, relevant, original)
            diagnostic['original_checks'] = current
            if all(v['satisfied'] for v in current):
                row.update(status='abstain', reason='declared_checks_preserve_original')
            else:
                inventory = generate(original)
                diagnostic['inventory_size'] = len(inventory['candidates'])
                if inventory['status'] != 'supported' or inventory['search_truncated']:
                    raise ValueError('incomplete_candidate_search')
                pool = {c['structural_key']: c['formula'] for c in inventory['candidates']}
                if prior_candidate and syntax_evidence(prior_candidate)['supported']:
                    pool.setdefault(structural_key(prior_candidate), prior_candidate)
                pool.pop(structural_key(original), None)
                matches, rejected = [], Counter()
                for candidate in pool.values():
                    try:
                        refs = references(candidate, target[0])
                        if target in refs or controls & set(refs):
                            raise ValueError('candidate_reads_control_or_self')
                        for ref in refs:
                            deps = closure(model, ref, target)
                            if deps & controls:
                                raise ValueError('candidate_indirectly_reads_control')
                        checks = constraint_results(model, target, relevant, candidate)
                        if all(v['satisfied'] for v in checks):
                            matches.append({'formula': candidate, 'checks': checks})
                    except (ValueError, TypeError, ZeroDivisionError, OverflowError, RecursionError) as error:
                        rejected[str(error)] += 1
                diagnostic.update(satisfying_candidates=matches, rejected_candidates=dict(rejected))
                if len(matches) == 1:
                    row.update(status='propose', suggested_formula=matches[0]['formula'],
                               candidate_formula=matches[0]['formula'],
                               reason='unique_candidate_satisfies_declared_checks')
                else:
                    row['reason'] = 'ambiguous_declared_checks' if matches else 'no_candidate_satisfies_declared_checks'
        except (ValueError, TypeError, ZeroDivisionError, OverflowError, RecursionError) as error:
            row['reason'] = str(error)
            diagnostic['failure'] = str(error)
        reasons[row['reason']] += 1
        changed += before != (row.get('status'), row.get('suggested_formula'))
    result['reconciliation_summary'] = {'declarations': len(specs),
        'valid_declarations': sum(s['valid'] for s in specs), 'changed_decisions': changed,
        'reasons': dict(reasons), 'control_provenance_verified': False,
        'final_validation_eligible': False}
    result = qualify(model, result)
    result['selector'] = VERSION
    for row in result['rows']:
        if 'reconciliation' in row:
            row['selector_version'] = VERSION
    return result
