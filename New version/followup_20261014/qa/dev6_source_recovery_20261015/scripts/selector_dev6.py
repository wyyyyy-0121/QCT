"""A bounded contract-candidate experiment for common peer corruption.

This module deliberately treats the four development header dictionaries as an
explicit, development-authored contract.  It is not general spreadsheet
semantics and it is not enabled for final validation.  A candidate is emitted
only when every parallel sheet has the same formula, the current formula
violates the registered role directions, and the output/unit headers match
exactly.  Otherwise the dev5 decision is preserved.
"""
from collections import defaultdict

from formulaguard.a1 import num_to_col, parse_address
from structuralguard.formula import profile_formula

from selector_dev5 import (
    VERSION as DEV5_VERSION,
    augment as dev5_augment,
    header_index,
    policy_scopes,
    semantic_check,
    semantic_roles,
)

VERSION = 'hybridguard-followup-selector-dev6-contract-candidate'


def _cell(roles, name, row):
    for col, (role, _direction) in roles.items():
        if role == name:
            return num_to_col(col) + str(row)
    raise ValueError('missing role: ' + name)


def contract_formula(output, roles, row):
    """Build only the four exact formulas registered for this experiment."""
    if output == 'closing inventory [units]':
        return '=B%s+C%s-D%s-E%s' % (row, row, row, row)
    if output == 'closing loan [usd]':
        return '=%s+%s-%s' % (_cell(roles, 'opening loan [usd]', row),
                              _cell(roles, 'interest [usd]', row),
                              _cell(roles, 'payment [usd]', row))
    if output == 'allocated budget [usd]':
        return '=%s*%s/%s+%s' % (_cell(roles, 'budget [usd]', row),
                                 _cell(roles, 'allocation weight', row),
                                 _cell(roles, 'total weight', row),
                                 _cell(roles, 'adjustment [usd]', row))
    if output == 'temperature [f]':
        return '=%s*%s+%s+%s' % (_cell(roles, 'temperature [c]', row),
                                 _cell(roles, 'scale [f/c]', row),
                                 _cell(roles, 'offset [f]', row),
                                 _cell(roles, 'sensor correction [f]', row))
    raise ValueError('unregistered output role')


def _norm(formula):
    return ''.join(str(formula).split()).casefold()


def _all_peers_same(model, sheet, address, parallel_sheets):
    actual = model.formulas.get((sheet, address))
    if actual is None:
        return False, 0
    peers = [model.formulas.get((peer, address)) for peer in parallel_sheets
             if peer != sheet]
    peers = [value for value in peers if value is not None]
    if len(peers) < 2:
        return False, len(peers)
    target = _norm(actual)
    return bool(target and all(_norm(value) == target for value in peers)), len(peers)


def augment(model, prior, parallel_sheets):
    base = dev5_augment(model, prior, parallel_sheets)
    index = header_index(model)
    scopes = policy_scopes(model)
    resolved = None
    rows = []
    for old in base['rows']:
        row = dict(old)
        sheet, address = row['cell'].rsplit('!', 1)
        if row.get('status') == 'propose' or scopes.get(sheet, {}).get('opaque'):
            rows.append(row)
            continue
        roles, output = semantic_roles(index, sheet, address)
        if not roles or not output or scopes.get(sheet, {}).get('rows'):
            rows.append(row)
            continue
        same, peer_count = _all_peers_same(model, sheet, address, parallel_sheets)
        row['contract_candidate_diagnostic'] = {
            'peer_count': peer_count,
            'all_parallel_formulas_same': same,
            'contract_version': VERSION,
            'contract_source': 'development_authored_exact_header_role_dictionary',
        }
        if not same:
            rows.append(row)
            continue
        if resolved is None:
            resolved, _ = model.evaluate()
        current = semantic_check(model.formulas[sheet, address], sheet, address,
                                 roles, resolved)
        if (not current.get('available') or not current.get('opposite_roles')
                or current.get('missing_roles')):
            rows.append(row)
            continue
        try:
            candidate = contract_formula(output, roles, parse_address(address).row)
            check = semantic_check(candidate, sheet, address, roles, resolved)
            profile_formula(candidate, address, sheet)
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            rows.append(row)
            continue
        if not check.get('available') or check.get('opposite_roles') or check.get('missing_roles'):
            rows.append(row)
            continue
        row.update(status='propose', suggested_formula=candidate,
                   candidate_formula=candidate, selection_evidence=[{
                       'kind': 'development_contract_candidate',
                       'contract_source': 'exact_header_role_dictionary',
                       'peer_count': peer_count,
                       'all_parallel_formulas_same': True,
                   }], semantic_candidate=check,
                   reason='explicit_contract_recovers_common_peer_corruption',
                   selector_version=VERSION)
        rows.append(row)
    return {**base, 'rows': rows, 'selector_version': VERSION,
            'parameters': {
                'base_selector': DEV5_VERSION,
                'contract_source': 'development_authored_exact_header_role_dictionary',
                'requires_all_parallel_formulas_same': True,
                'requires_exact_output_and_unit_headers': True,
                'final_validation_eligible': False,
            },
            'limitations': list(base.get('limitations', [])) + [
                'Contract candidates are a revealed development experiment only.',
                'The header dictionary is not an independently verified workbook contract.',
                'No proposal from this selector may enter final validation without a frozen contract protocol.'
            ]}
