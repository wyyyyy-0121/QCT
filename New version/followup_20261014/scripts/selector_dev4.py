"""Experimental narrow, auditable policy interpretation; no answer access.

Only the complete controlled English phrases listed below are recognized.
Unknown policy prose retains dev3 review. This is development scope, not broad
natural-language understanding or a verified contract supplied by an author.
"""
import re
import selector_dev2 as dev2
from selector_dev3 import policy_notes
from formulaguard.a1 import parse_address
from structuralguard.formula import profile_formula

VERSION = 'hybridguard-followup-selector-dev4'


def interpret(model, sheet, notes, output_rows):
    rules = []
    for note in notes:
        value = str(model.cells.get((sheet, note['text_cell']), '')).strip()
        pieces = re.split(r'[:：]', value, maxsplit=1)
        if pieces[0].strip().casefold() in {'business policy', 'notes', 'business rules'} and len(pieces) == 2:
            value = pieces[1].strip()
        lowered = value.casefold()
        waiver = re.fullmatch(r'row (\d+): seller absorbs shipping; exclude shipping from this profit calculation\.', lowered)
        if waiver:
            row = int(waiver.group(1))
            if row not in output_rows:
                return None
            rules.append({'row': row, 'role': 'shipping', 'direction': 0, 'source': note})
        elif lowered == f'sheet {sheet.casefold()}: contractual full-price sales; discount rate is quoted but not applied.':
            rules.append({'row': None, 'role': 'discount rate', 'direction': 0, 'source': note})
        elif lowered == f'sheet {sheet.casefold()}: unit cost is fully reimbursed as an additional receipt in this contract.':
            rules.append({'row': None, 'role': 'unit cost', 'direction': 1, 'source': note})
        elif lowered == 'all ordinary shipping costs in this sheet are borne by the seller.':
            rules.append({'row': None, 'role': 'shipping', 'direction': -1, 'source': note})
        else:
            return None
    return rules


def check(model, formula, sheet, address, roles, rules):
    got = dev2.directional_check(model, formula, sheet, address, roles)
    if not got['available']:
        return got
    row = parse_address(address).row
    overrides = {}
    for rule in rules:
        if rule['row'] is None or rule['row'] == row:
            if rule['role'] in overrides and overrides[rule['role']] != rule['direction']:
                return {'available': False, 'violations': [], 'reason': 'conflicting_policy_rules'}
            overrides[rule['role']] = rule['direction']
    checks = []; violations = []
    for raw in got['checks']:
        item = dict(raw); direction = overrides.get(item['role'], item['expected_direction'])
        item['expected_direction'] = direction
        item['policy_override'] = item['role'] in overrides
        bad = abs(item['effect']) > 1e-8 if direction == 0 else direction * item['effect'] <= 1e-8
        if bad:
            violations.append(item['role'])
        checks.append(item)
    return {'available': True, 'checks': checks, 'violations': violations,
            'interpretation': 'controlled policy text plus remaining unverified header hypotheses'}


def review_guard(model, prediction):
    notes_by_sheet = policy_notes(model)
    rows_by_sheet = {}
    for sheet, address in model.formulas:
        rows_by_sheet.setdefault(sheet, set()).add(parse_address(address).row)
    interpreted = {s: interpret(model, s, notes, rows_by_sheet.get(s, set()))
                   for s, notes in notes_by_sheet.items()}
    result = []; cache = {}
    for old in prediction['rows']:
        row = dict(old); row['selector_version'] = VERSION
        sheet, address = row['cell'].rsplit('!', 1)
        if sheet not in notes_by_sheet:
            result.append(row); continue
        rules = interpreted[sheet]
        if rules is None:
            if row['status'] == 'propose':
                row.update(status='review', review_candidate=row['suggested_formula'], suggested_formula=None,
                           candidate_formula=None, reason='unparsed_business_policy')
            result.append(row); continue
        col = parse_address(address).col
        if (sheet, col) not in cache:
            cache[sheet, col] = dev2.header_roles(model, sheet, col)
        roles = cache[sheet, col]
        current = check(model, model.formulas[sheet, address], sheet, address, roles, rules)
        row['policy_interpretation'] = {'rules': rules, 'current_check': current}
        if row['status'] != 'propose':
            result.append(row); continue
        candidate = check(model, row['suggested_formula'], sheet, address, roles, rules)
        p = profile_formula(model.formulas[sheet, address], address, sheet)
        cp = profile_formula(row['suggested_formula'], address, sheet)
        qualified = False
        if current['available'] and candidate['available'] and not candidate['violations']:
            if current['violations']:
                qualified = True
            elif not current['violations'] and row.get('reason') == 'column_supported_nonconstant_anomaly' and p.constants == cp.constants:
                qualified = True
        if not qualified:
            row.update(status='review', review_candidate=row['suggested_formula'], suggested_formula=None,
                       candidate_formula=None, reason='policy_does_not_authorize_proposal')
        else:
            row['reason'] = 'policy_compatible_' + row.get('reason', 'proposal')
        result.append(row)
    return {**prediction, 'rows': result, 'selector_version': VERSION,
        'policy_interpretation': {'rules_by_sheet': interpreted, 'controlled_language_only': True},
        'limitation': 'Known development policy phrases only; unmarked exceptions, coefficient intent, '
                      'unknown roles and general policy language remain unresolved.'}


def select(model, original, fg_rows, sg_rows, parallel_sheets):
    return review_guard(model, dev2.select(model, original, fg_rows, sg_rows, parallel_sheets))
