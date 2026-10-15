"""Dependency-aware peer selection, a revealed-development hypothesis.

Extends immutable dev4 predictions. Header/unit dictionaries are authored on
revealed cases; they are not universal business rules. Peers supply candidates,
never independent confirmation. Input workbooks and upstream code stay intact.
"""
from collections import Counter, defaultdict
import math
import re

from formulaguard.a1 import parse_address, num_to_col
from formulaguard.formula import Binary, Number, Ref, Unary, parse_formula
from structuralguard.formula import profile_formula, translate_formula
from selector_dev3 import POLICY_MARKERS, policy_notes

VERSION = 'hybridguard-followup-selector-dev5'
OUTPUT_ROLES = {
    'closing inventory [units]': {
        'opening inventory [units]': 1, 'receipts [units]': 1,
        'issues [units]': -1, 'write-offs [units]': -1},
    'closing loan [usd]': {
        'opening loan [usd]': 1, 'interest [usd]': 1, 'payment [usd]': -1},
    'allocated budget [usd]': {
        'budget [usd]': 1, 'allocation weight': 1, 'total weight': -1,
        'adjustment [usd]': 1},
    'temperature [f]': {
        'temperature [c]': 1, 'offset [f]': 1, 'sensor correction [f]': 1},
}
PARAMETERS = {'version': VERSION, 'header_roles': OUTPUT_ROLES,
    'all_peer_shapes': True, 'candidate_generation': 'existing peer formula or dev4 proposal',
    'relative_step': .01, 'absolute_step': .001, 'effect_tolerance': 1e-8,
    'unknown_policy_scope': 'sheet unless one complete explicit Row N note',
    'independent_peer_assumption': False,
    'coefficient_or_dependency_set_changes': 'review',
    'fallback': 'immutable dev4 for outputs outside new header dictionary'}


def clean_text(value):
    return ' '.join(str(value).strip().casefold().split())


def header_index(model):
    index = defaultdict(list)
    for key, value in model.cells.items():
        if key not in model.formulas and isinstance(value, str) and model.is_visible(key):
            sheet, address = key; a = parse_address(address)
            index[sheet, a.col].append((a.row, clean_text(value)))
    return {k: sorted(v) for k, v in index.items()}


def semantic_roles(index, sheet, address):
    target = parse_address(address)
    previous = [(r, text) for r, text in index.get((sheet, target.col), []) if r < target.row]
    if not previous:
        return {}, None
    header_row, output = previous[-1]
    if output not in OUTPUT_ROLES:
        return {}, None
    roles = {}
    for (s, col), entries in index.items():
        for r, name in entries:
            if s == sheet and r == header_row and name in OUTPUT_ROLES[output]:
                if name in [role for role, _ in roles.values()]:
                    return {}, 'ambiguous_duplicate_header'
                roles[col] = (name, OUTPUT_ROLES[output][name])
    if len(roles) != len(OUTPUT_ROLES[output]):
        return {}, 'incomplete_header_roles'
    return roles, output


def expression_value(node, sheet, resolved, overrides):
    """Hold other resolved precedents constant for local partial derivatives.

    A formula precedent is first evaluated from the observed workbook, then
    treated as an intermediate quantity. This is not causal propagation.
    """
    if isinstance(node, Number): return node.value
    if isinstance(node, Ref):
        key = (node.sheet or sheet, node.address.a1.replace('$', ''))
        value = overrides.get(key, resolved.get(key))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('unresolved or nonnumeric precedent')
        if not math.isfinite(value): raise ValueError('nonfinite precedent')
        return float(value)
    if isinstance(node, Unary):
        value = expression_value(node.value, sheet, resolved, overrides)
        return value if node.op == '+' else -value
    if isinstance(node, Binary):
        left = expression_value(node.left, sheet, resolved, overrides)
        right = expression_value(node.right, sheet, resolved, overrides)
        if node.op == '+': return left + right
        if node.op == '-': return left - right
        if node.op == '*': return left * right
        if node.op == '/': return left / right
    raise ValueError('direction check supports arithmetic expressions only')


def semantic_check(formula, sheet, address, roles, resolved):
    if not roles:
        return {'available': False, 'opposite_roles': [], 'missing_roles': []}
    checks = []; opposite = []; missing = []
    try:
        node = parse_formula(formula)
        base = expression_value(node, sheet, resolved, {})
        if not math.isfinite(base): raise ValueError('nonfinite output')
        row = parse_address(address).row
        for col, (name, direction) in sorted(roles.items()):
            key = sheet, num_to_col(col) + str(row)
            value = resolved.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError('role unavailable')
            step = max(abs(value) * PARAMETERS['relative_step'], PARAMETERS['absolute_step'])
            effect = (expression_value(node, sheet, resolved, {key: value + step}) - base) / step
            if not math.isfinite(effect): raise ValueError('nonfinite effect')
            signed = direction * effect
            if signed < -PARAMETERS['effect_tolerance']: opposite.append(name)
            elif abs(effect) <= PARAMETERS['effect_tolerance']: missing.append(name)
            checks.append({'role': name, 'input': key[1], 'expected_direction': direction,
                           'partial_effect': effect})
        return {'available': True, 'opposite_roles': opposite, 'missing_roles': missing,
                'checks': checks, 'interpretation': 'header hypothesis; local partial derivatives'}
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
        return {'available': False, 'opposite_roles': [], 'missing_roles': [], 'reason': str(exc)}


def policy_scopes(model):
    result = {}
    for sheet, notes in policy_notes(model).items():
        rows = set(); opaque = False
        texts = set()
        for note in notes:
            texts.add(str(model.cells.get((sheet, note['text_cell']), '')).strip())
            # Contiguous prose below a detected marker can qualify/conflict with
            # its first line. Do not silently ignore a second policy paragraph.
            marker = parse_address(note['marker_cell'])
            row = marker.row + 1
            while True:
                key = sheet, num_to_col(marker.col) + str(row)
                value = model.cells.get(key)
                if key in model.formulas or not isinstance(value, str) or not value.strip():
                    break
                texts.add(value.strip()); row += 1
        formula_rows = {parse_address(address).row for s, address in model.formulas if s == sheet}
        for value in sorted(texts):
            pieces = re.split(r'[:：]', value, maxsplit=1)
            if len(pieces) == 2 and clean_text(pieces[0]) in POLICY_MARKERS:
                body = pieces[1]
                value = body.strip()
            match = re.fullmatch(r'(?is)row\s+([1-9]\d*)\s*:\s*([^\n]+)', value)
            # Multiple/global scopes or additional sentences retain sheet review.
            if match and int(match.group(1)) in formula_rows and not re.search(
                r'(?i)\b(all|other|following|subsequent|previous|next|through|rows|sheet|table|range|except)\b|'
                r'\brow\b|\d|[.!?].*\S', match.group(2).rstrip('.')):
                number = int(match.group(1))
                if number in rows: opaque = True
                rows.add(number)
            else: opaque = True
        result[sheet] = {'rows': sorted(rows), 'opaque': opaque,
                         'interpretation': 'explicit syntax only; contents uninterpreted'}
    return result


def dependencies(profile, sheet):
    return Counter((r.sheet.casefold() if r.sheet.casefold() != sheet.casefold() else 'self',
                    r.address, r.row_abs, r.col_abs) for r in profile.references)


def augment(model, prior, parallel_sheets):
    index = header_index(model); scopes = policy_scopes(model)
    positions = defaultdict(list)
    for (sheet, address), formula in model.formulas.items():
        if sheet in parallel_sheets: positions[address].append((sheet, formula))
    resolved = None; results = []
    for old in prior['rows']:
        row = dict(old); row['selector_version'] = VERSION
        sheet, address = row['cell'].rsplit('!', 1)
        roles, output = semantic_roles(index, sheet, address)
        if not roles:
            results.append(row); continue
        row.update(status='abstain', suggested_formula=None, candidate_formula=None,
                   reason='new_header_without_authorized_change', selection_evidence=[])
        scope = scopes.get(sheet); number = parse_address(address).row
        if scope and (scope['opaque'] or number in scope['rows']):
            row.update(status='review', reason='uninterpreted_policy_scope',
                       policy_scope=scope, review_candidate=old.get('suggested_formula'))
            results.append(row); continue
        if resolved is None: resolved, _ = model.evaluate()
        actual = model.formulas[sheet, address]
        current = semantic_check(actual, sheet, address, roles, resolved)
        row['semantic_current'] = current
        # Missing terms and coefficient-only changes can be legitimate exceptions.
        if not current['available'] or not current['opposite_roles'] or current['missing_roles']:
            if old.get('suggested_formula'):
                row.update(status='review', reason='no_opposite_sign_evidence',
                           review_candidate=old['suggested_formula'])
            results.append(row); continue
        p = profile_formula(actual, address, sheet)
        pool = defaultdict(list)
        for peer_sheet, formula in positions.get(address, []):
            if peer_sheet == sheet: continue
            peer_roles, peer_output = semantic_roles(index, peer_sheet, address)
            if peer_output != output or peer_roles != roles: continue
            pp = profile_formula(formula, address, peer_sheet)
            if any(r.sheet.casefold() != peer_sheet.casefold() for r in pp.references): continue
            pool[translate_formula(formula, address, address)].append(
                {'kind': 'parallel_sheet_candidate', 'peer_sheet': peer_sheet,
                 'independence': 'unknown; no vote-based authorization'})
        if old.get('suggested_formula'):
            pool[old['suggested_formula']].append({'kind': 'dev4_candidate'})
        pool.pop(actual, None)
        qualified = []
        for candidate, evidence in pool.items():
            cp = profile_formula(candidate, address, sheet)
            if (cp.has_ref_error or cp.has_direct_self_reference or p.functions != cp.functions
                    or p.constants != cp.constants or dependencies(p, sheet) != dependencies(cp, sheet)):
                continue
            check = semantic_check(candidate, sheet, address, roles, resolved)
            if check['available'] and not check['opposite_roles'] and not check['missing_roles']:
                qualified.append((candidate, evidence, check))
        row['candidate_diagnostic'] = {'peer_candidates': len(pool), 'qualified': len(qualified),
                                       'peer_counts_not_independent': True}
        if len(qualified) == 1:
            candidate, evidence, check = qualified[0]
            row.update(status='propose', suggested_formula=candidate, selection_evidence=evidence,
                       semantic_candidate=check, reason='peer_candidate_resolves_opposite_sign')
        elif pool: row.update(status='review', reason='no_unique_semantic_peer_candidate')
        results.append(row)
    return {**prior, 'rows': results, 'selector_version': VERSION, 'parameters': PARAMETERS,
            'automatic_edit_applied': False, 'labels_read': [],
            'limitations': ['Explicit development-authored header/unit dictionary only.',
                           'Header roles and Row N scopes remain business hypotheses.',
                           'Shared candidates and cached values do not establish correctness.',
                           'Missing terms and coefficient intent remain unresolved.']}
