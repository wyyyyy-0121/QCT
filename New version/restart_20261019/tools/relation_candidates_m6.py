"""Generate missing paper candidates from supplied linear-output relations."""
import ast
from copy import deepcopy
import re

import sympy as sp

from e3_contract import Quantity, Unsupported, arithmetic, equivalent, select, active_branch
from candidate_gate_m1 import REFERENCE


def solve_relation(request):
    definitions = request['symbols']
    if 'y' in definitions or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in definitions):
        raise Unsupported('invalid_input_symbols')
    variables = {name: Quantity(sp.Symbol(name, positive=True), tuple(sorted(data['units'].items())))
                 for name, data in definitions.items()}
    y = sp.Symbol('y', real=True)
    variables['y'] = Quantity(y, tuple(sorted(request['output_units'].items())))
    solutions = []
    for relation in request['relations']:
        left = arithmetic(relation['lhs'], variables)
        right = arithmetic(relation['rhs'], variables)
        if left.units != right.units:
            raise Unsupported('relation_units_mismatch')
        numerator, denominator = sp.fraction(sp.cancel(left.value - right.value))
        if y in denominator.free_symbols:
            raise Unsupported('output_in_denominator')
        polynomial = sp.Poly(numerator, y)
        if polynomial.degree() != 1:
            raise Unsupported('output_relation_not_linear_and_unique')
        coefficient = polynomial.coeff_monomial(y)
        if coefficient.is_positive is not True and coefficient.is_negative is not True:
            raise Unsupported('output_coefficient_not_provably_nonzero')
        solution = sp.factor(-polynomial.coeff_monomial(1) / coefficient)
        if y in solution.free_symbols:
            raise Unsupported('output_not_eliminated')
        solutions.append(Quantity(solution, variables['y'].units))
    if not solutions:
        return None, variables
    if any(not equivalent(solutions[0], value) for value in solutions[1:]):
        raise Unsupported('conflicting_business_relations')
    return solutions[0], variables


def render_solution(expression, references, sheet, target):
    reverse = {}
    used = {str(symbol) for symbol in expression.free_symbols}
    for reference, name in references.items():
        if name not in used:
            continue
        if not REFERENCE.fullmatch(reference) or ':' in reference:
            raise Unsupported('reference_mapping_not_single_a1')
        if name in reverse:
            raise Unsupported('ambiguous_reference_mapping')
        if '!' in reference:
            ref_sheet, address = reference.rsplit('!', 1)
            ref_sheet = ref_sheet[1:-1].replace("''", "'") if ref_sheet.startswith("'") else ref_sheet
        else:
            ref_sheet, address = sheet, reference
        if ref_sheet.casefold() == sheet.casefold() and address.replace('$', '').upper() == target.upper():
            raise Unsupported('self_reference_mapping')
        reverse[name] = reference
    if used != reverse.keys():
        raise Unsupported('missing_reference_mapping')

    def render(node):
        if isinstance(node, sp.Symbol):
            return reverse[str(node)]
        if isinstance(node, sp.Integer):
            return str(node)
        numerator, denominator = sp.fraction(node)
        if denominator != 1:
            return '(' + render(numerator) + '/' + render(denominator) + ')'
        if isinstance(node, sp.Add):
            return '(' + '+'.join(render(term) for term in node.args) + ')'
        if isinstance(node, sp.Mul):
            return '(' + '*'.join(render(term) for term in node.args) + ')'
        if isinstance(node, sp.Pow) and node.exp.is_Integer:
            return '(' + render(node.base) + '^' + str(node.exp) + ')'
        raise Unsupported('solution_rendering_unsupported')

    return render(expression)


def replace_active_branch(observed, replacement, branch):
    # The existing checker validates the declared guard/inactive token sequence.
    active_branch(observed, branch)
    opening = observed.find('(')
    depth, quote, commas, closing = 1, None, [], None
    index = opening + 1
    while index < len(observed):
        char = observed[index]
        if quote:
            if char == quote:
                if index + 1 < len(observed) and observed[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                closing = index
                break
        elif char == ',' and depth == 1:
            commas.append(index)
        index += 1
    if len(commas) != 2 or closing is None or observed[closing + 1:].strip():
        raise Unsupported('unsupported_if_envelope')
    prefix = observed[:commas[1] + 1]
    return prefix + replacement + observed[closing:], prefix


def review(request, observed, native_candidates):
    result = dict(status='abstain', reason=None, suggested_formula=None,
                  generated_candidate=None, native_candidate_count=len(native_candidates),
                  native_pool_has_equivalent=None, generator_input_contains_candidates=False,
                  automatic_edit_applied=False, final_validation_eligible=False,
                  scope='Supplied business relation; positive input symbols; declared IF active branch only')
    if 'candidates' in request:
        result.update(status='unsupported', reason='manual_candidate_list_forbidden')
        return result
    if not request.get('relations'):
        result['reason'] = 'missing_business_relation'
        return result
    try:
        solution, variables = solve_relation(request)
        expression = render_solution(solution.value, request['references'], request['sheet'], request['cell'])
        generated = '=' + expression
        if request.get('branch'):
            generated, prefix = replace_active_branch(observed, expression, request['branch'])
            result['preserved_if_prefix'] = prefix
        verifier = deepcopy(request)
        verifier['constraints'] = [str(solution.value)]
        verifier['candidates'] = list(dict.fromkeys(native_candidates))
        old = select(verifier, observed)
        result['native_pool_has_equivalent'] = any(r.get('matches') for r in old['candidate_diagnostics'])
        verifier['candidates'] = list(dict.fromkeys([*native_candidates, generated]))
        checked = select(verifier, observed)
        result.update(status=checked['status'], reason=checked['reason'],
                      suggested_formula=checked['suggested_formula'], generated_candidate=generated,
                      original_satisfies_contract=checked['original_satisfies_contract'],
                      verified_candidate_count=len(verifier['candidates']),
                      generated_candidate_matches=any(r.get('matches') and r['formula'] == generated
                                                      for r in checked['candidate_diagnostics']))
        return result
    except (Unsupported, SyntaxError, ValueError, TypeError, KeyError, ZeroDivisionError) as error:
        reason = str(error)
        result.update(status='abstain' if reason in ('conflicting_business_relations',
                      'output_coefficient_not_provably_nonzero') else 'unsupported', reason=reason)
        return result
