"""Bounded, separately declared contract input; never inferred from truth.

Schema validation verifies syntax and workbook binding, not authorship or
business correctness. This auxiliary mode does not count toward the main
workbook-only acceptance gate. Contracts must precede mutation/prediction.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

from formulaguard.a1 import col_to_num, num_to_col, parse_address
from formulaguard.formula import Binary, Number, Ref, Unary, parse_formula
from formula_candidates_dev1 import structural_key

VERSION = 'hybridguard-contract-mode-dev1'
SCHEMA_VERSION = 1
SHA = re.compile(r'[0-9a-f]{64}')
ROLE = re.compile(r'[a-z][a-z0-9_]*')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _row(value):
    return type(value) is int and 1 <= value <= 1048576


def _arithmetic(node):
    if isinstance(node, Number):
        if not math.isfinite(node.value):
            raise ValueError('nonfinite_contract_constant')
    elif isinstance(node, Ref):
        if node.sheet or node.address.row_abs or node.address.col_abs:
            raise ValueError('contract_reference_outside_role_grammar')
    elif isinstance(node, Unary) and node.op in ('+', '-'):
        _arithmetic(node.value)
    elif isinstance(node, Binary) and node.op in ('+', '-', '*', '/'):
        _arithmetic(node.left); _arithmetic(node.right)
    else:
        raise ValueError('contract_template_unsupported_arithmetic')


def _template_names(template, roles):
    if not isinstance(template, str) or not template.startswith('=') or len(template) > 2048:
        raise ValueError('formula_template_missing_or_too_long')
    names = set(re.findall(r'\{([a-z][a-z0-9_]*)\}', template))
    if not names or names - set(roles):
        raise ValueError('template_references_unknown_role')
    bare = re.sub(r'\{([a-z][a-z0-9_]*)\}', '1', template)
    if re.search(r'[A-Za-z{}!$]', bare):
        raise ValueError('template_has_undeclared_reference_or_function')
    _arithmetic(parse_formula(bare))
    return names


def validate_contract(contract):
    if not isinstance(contract, dict) or type(contract.get('schema_version')) is not int or contract['schema_version'] != SCHEMA_VERSION:
        raise ValueError('unsupported_contract_schema')
    if contract.get('mode') != 'author_supplied_contract':
        raise ValueError('contract_mode_must_be_explicit')
    if not all(isinstance(contract.get(k), str) and contract[k].strip()
               for k in ('author', 'source_uri')):
        raise ValueError('contract_provenance_missing')
    if contract.get('provenance_status') not in ('development_authored', 'author_declared_unverified'):
        raise ValueError('contract_provenance_status_required')
    if not isinstance(contract.get('workbook_sha256'), str) or not SHA.fullmatch(contract['workbook_sha256']):
        raise ValueError('contract_workbook_binding_missing')
    scopes = contract.get('sheet_scopes')
    if not isinstance(scopes, dict) or not scopes:
        raise ValueError('contract_sheet_scopes_missing')
    for sheet, scope in scopes.items():
        if not isinstance(sheet, str) or not sheet or not isinstance(scope, dict):
            raise ValueError('invalid_sheet_scope')
        if scope.get('action', 'propose') != 'propose':
            raise ValueError('unsupported_contract_action')
        if not _row(scope.get('header_row')):
            raise ValueError('explicit_header_row_required')
        data_rows = scope.get('data_rows')
        if (not isinstance(data_rows, list) or len(data_rows) != 2
                or not all(_row(v) for v in data_rows)
                or not scope['header_row'] < data_rows[0] <= data_rows[1]):
            raise ValueError('explicit_bounded_data_rows_required')
        output = scope.get('output_column')
        if (not isinstance(output, str) or not re.fullmatch(r'[A-Z]{1,3}', output)
                or col_to_num(output) > 16384):
            raise ValueError('explicit_output_column_required')
        if not isinstance(scope.get('output_header'), str) or not scope['output_header'].strip():
            raise ValueError('output_header_missing')
        roles = scope.get('roles')
        if not isinstance(roles, dict) or not roles:
            raise ValueError('role_map_missing')
        for role, spec in roles.items():
            if not isinstance(role, str) or not ROLE.fullmatch(role) or not isinstance(spec, dict):
                raise ValueError('invalid_role_spec')
            if not isinstance(spec.get('header'), str) or not spec['header'].strip():
                raise ValueError('role_header_missing')
        _template_names(scope.get('formula_template'), roles)
        rules = scope.get('row_rules', [])
        if not isinstance(rules, list):
            raise ValueError('invalid_row_rules')
        seen = set()
        for rule in rules:
            if (not isinstance(rule, dict) or not _row(rule.get('row'))
                    or not data_rows[0] <= rule['row'] <= data_rows[1]
                    or rule['row'] in seen):
                raise ValueError('duplicate_or_out_of_scope_row_rule')
            seen.add(rule['row']); _template_names(rule.get('formula_template'), roles)
        excluded = scope.get('excluded_rows', [])
        if (not isinstance(excluded, list) or any(not _row(v) or not data_rows[0] <= v <= data_rows[1] for v in excluded)
                or len(set(excluded)) != len(excluded) or seen & set(excluded)):
            raise ValueError('invalid_or_conflicting_excluded_rows')
    return True


def load_contract(path):
    raw = path.read_bytes(); value = json.loads(raw)
    validate_contract(value)
    return value, hashlib.sha256(raw).hexdigest()


def _norm(text):
    return ' '.join(str(text).strip().casefold().split())


def _headers(model, sheet, row):
    headings = {}
    for (s, address), value in model.cells.items():
        if s == sheet and isinstance(value, str) and (s, address) not in model.formulas and model.is_visible((s, address)):
            a = parse_address(address)
            if a.row == row:
                headings.setdefault(_norm(value), []).append(a.col)
    return headings


def _render(model, sheet, scope, number):
    headings = _headers(model, sheet, scope['header_row'])
    out_col = col_to_num(scope['output_column'])
    if headings.get(_norm(scope['output_header'])) != [out_col]:
        raise ValueError('contract_output_header_missing_or_ambiguous')
    template = scope['formula_template']
    for rule in scope.get('row_rules', []):
        if rule['row'] == number:
            template = rule['formula_template']
    names = _template_names(template, scope['roles'])
    inputs = []
    for name in sorted(names):
        cols = headings.get(_norm(scope['roles'][name]['header']), [])
        if len(cols) != 1 or cols[0] == out_col:
            raise ValueError('contract_input_header_missing_ambiguous_or_self_reference')
        address = num_to_col(cols[0]) + str(number)
        if not model.is_visible((sheet, address)):
            raise ValueError('contract_input_hidden')
        inputs.append((sheet, address))
        template = template.replace('{' + name + '}', address)
    if len(set(inputs)) != len(inputs):
        raise ValueError('contract_distinct_roles_alias_one_input')
    _arithmetic(parse_formula(template))
    return template, inputs


def _review(row, reason, candidate=None):
    return {**row, 'status': 'review', 'suggested_formula': None,
            'candidate_formula': None, 'review_candidate': candidate,
            'reason': reason, 'selector_version': VERSION}


def apply_contract(model, prior, contract, workbook_sha256, contract_sha256=None):
    validate_contract(contract)
    if workbook_sha256 != contract['workbook_sha256']:
        raise ValueError('contract_workbook_hash_mismatch')
    if contract_sha256 is not None and not SHA.fullmatch(contract_sha256):
        raise ValueError('contract_file_hash_invalid')
    expected = {sheet+'!'+addr for sheet, addr in model.formulas}
    labels = [r['cell'] for r in prior.get('rows', [])]
    if len(labels) != len(set(labels)) or set(labels) != expected:
        raise ValueError('prediction_must_cover_every_formula_exactly_once')
    rows = []
    contract_hash = digest(contract)
    for original in prior['rows']:
        row = deepcopy(original)
        sheet, address = row['cell'].rsplit('!', 1); a = parse_address(address)
        scope = contract['sheet_scopes'].get(sheet)
        if (scope is None or num_to_col(a.col) != scope['output_column']
                or not scope['data_rows'][0] <= a.row <= scope['data_rows'][1]):
            rows.append(row); continue
        if a.row in scope.get('excluded_rows', []):
            rows.append(_review(row, 'author_contract_excludes_row')); continue
        candidate = None
        try:
            if not model.is_visible((sheet, address)):
                raise ValueError('contract_output_hidden')
            candidate, inputs = _render(model, sheet, scope, a.row)
            values, failures = model.evaluate(overrides={(sheet, address): candidate})
            for key in inputs + [(sheet, address)]:
                value = values.get(key)
                if key in failures or type(value) not in (float, int) or not math.isfinite(value):
                    raise ValueError('contract_candidate_or_input_unresolved')
            equivalent = structural_key(candidate) == structural_key(model.formulas[sheet, address])
        except (ValueError, TypeError, OverflowError, ZeroDivisionError) as exc:
            rows.append(_review(row, str(exc), candidate)); continue
        provenance = {'contract_file_sha256': contract_sha256,
                      'contract_canonical_sha256': contract_hash,
                      'workbook_sha256': workbook_sha256,
                      'author': contract['author'], 'source_uri': contract['source_uri'],
                      'provenance_status': contract['provenance_status'],
                      'author_identity_verified': False}
        if equivalent:
            row.update(status='abstain', suggested_formula=None, candidate_formula=None,
                       reason='observed_formula_matches_declared_contract',
                       selector_version=VERSION, contract_provenance=provenance)
        else:
            row.update(status='propose', suggested_formula=candidate, candidate_formula=candidate,
                       reason='declared_contract_authorizes_proposal',
                       selector_version=VERSION, contract_provenance=provenance)
        rows.append(row)
    return {**prior, 'rows': rows, 'selector_version': VERSION,
            'contract_mode': True, 'contract_canonical_sha256': contract_hash,
            'automatic_edit_applied': False, 'labels_read': [],
            'main_acceptance_eligible': False,
            'limitations': ['Declared contracts are extra inputs, not inferred intent.',
                            'Schema/hash checks do not verify contract authorship or correctness.',
                            'This auxiliary mode cannot satisfy the main workbook-only gate.']}
