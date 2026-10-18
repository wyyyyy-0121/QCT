"""Experimental workbook-only role hypotheses; explicit intent is not proven.

This is a real suggestion arm, scored in full. No source IDs, fixed workbook
addresses, truth files, expected-formula inventories or learned labels enter it.
"""
from collections import defaultdict
import re

from formulaguard.a1 import parse_address, num_to_col
from relation_algebra_dev30 import equivalent, UnknownRelation
from selector_dev11 import syntax_evidence

VERSION = 'hybridguard-visible-financial-relations-dev30-v1'
TARGETS = {'net cash flow': 'net_cash', 'yearly % base': 'percentage_sum',
           'yearly cost': 'annual_cost', 'opening balance': 'opening_rollforward'}
ROLE_NAMES = set(TARGETS) | {'total cash inflows', 'total cash outflows',
                           'base annual development cost', 'closing balance'}
EXCEPTION = re.compile(r'\b(?:exception|adjustment|override|policy|contract)\b', re.I)
INSTRUCTION = re.compile(r'\b(?:equals|subtract\w*|plus|times)\b', re.I)


def norm(text):
    return ' '.join(text.strip().rstrip(':').casefold().split())


class Context:
    def __init__(self, model):
        self.model = model
        self.captions = defaultdict(list)
        self.texts = defaultdict(list)
        self.formula_rows = defaultdict(list)
        for (sheet, address), value in model.cells.items():
            if (sheet, address) not in model.formulas and isinstance(value, str) and value.strip():
                pos = parse_address(address)
                self.texts[sheet].append(dict(address=address, text=value, row=pos.row, col=pos.col,
                                              visible=model.is_visible((sheet, address))))
                self.captions[sheet, norm(value)].append(self.texts[sheet][-1])
        for sheet, address in model.formulas:
            pos = parse_address(address)
            self.formula_rows[sheet, pos.row].append(address)

    def unique(self, sheet, title):
        records = self.captions.get((sheet, title), [])
        if len(records) != 1:
            raise ValueError('missing_or_duplicate_role:' + title)
        item = records[0]
        if not item['visible']:
            raise ValueError('hidden_role:' + title)
        return item

    def bind(self, sheet, role, col):
        if col <= role['col']:
            raise ValueError('role_not_left_of_value')
        address = num_to_col(col) + str(role['row'])
        key = sheet, address
        if not self.model.is_visible(key):
            raise ValueError('hidden_input')
        if key not in self.model.formulas and type(self.model.cells.get(key)) not in (int, float):
            raise ValueError('missing_or_nonnumeric_role_value')
        return address

    def blockers(self, sheet):
        for item in self.texts[sheet]:
            if not item['visible']:
                continue
            text = norm(item['text'])
            if EXCEPTION.search(text):
                raise ValueError('visible_exception_or_policy_note:' + item['address'])
            if INSTRUCTION.search(text) and any(title in text for title in ROLE_NAMES):
                raise ValueError('unverified_visible_instruction:' + item['address'])

    def candidate(self, sheet, address, title):
        self.blockers(sheet)
        output = self.unique(sheet, title)
        pos = parse_address(address)
        if pos.row != output['row'] or pos.col <= output['col']:
            raise ValueError('output_not_bound_to_role')
        if not self.model.is_visible((sheet, address)):
            raise ValueError('hidden_output')
        bindings = []
        def role(name, col=pos.col):
            item = self.unique(sheet, name)
            value = self.bind(sheet, item, col)
            bindings.append(dict(role=name, caption_cell=item['address'], value_cell=value,
                                 caption_text=item['text']))
            return value
        kind = TARGETS[title]
        if kind == 'net_cash':
            candidate = '=' + role('total cash inflows') + '-' + role('total cash outflows')
        elif kind == 'annual_cost':
            candidate = '=' + role('yearly % base') + '*' + role('base annual development cost')
        elif kind == 'percentage_sum':
            base = self.unique(sheet, 'base annual development cost')
            parts = [item for item in self.texts[sheet]
                     if '(% of base)' in norm(item['text']) and base['row'] < item['row'] < output['row']]
            if not 2 <= len(parts) <= 12 or len({norm(p['text']) for p in parts}) != len(parts):
                raise ValueError('ambiguous_or_insufficient_percentage_components')
            addresses = []
            for part in sorted(parts, key=lambda p: p['row']):
                if not part['visible']:
                    raise ValueError('hidden_percentage_role')
                value = self.bind(sheet, part, pos.col)
                bindings.append(dict(role=norm(part['text']), caption_cell=part['address'],
                                     value_cell=value, caption_text=part['text']))
                addresses.append(value)
            candidate = '=SUM(' + ','.join(addresses) + ')'
        else:
            if pos.col <= 1:
                raise ValueError('no_previous_column')
            close = self.unique(sheet, 'closing balance')
            units = [self.model.cells.get((sheet, num_to_col(r['col'] + 1) + str(r['row'])))
                     for r in (output, close)]
            if not all(isinstance(u, str) and u.strip() for u in units) or norm(units[0]) != norm(units[1]):
                raise ValueError('missing_or_conflicting_balance_units')
            for r in (output, close):
                if not self.model.is_visible((sheet, num_to_col(r['col'] + 1) + str(r['row']))):
                    raise ValueError('hidden_unit')
            candidate = '=' + role('closing balance', pos.col - 1)
        return candidate, dict(rule=kind, output_caption=title, output_caption_cell=output['address'],
                               bindings=bindings, source='visible_workbook_roles_and_fixed_domain_hypothesis',
                               author_intent_proven=False)


def predict(model):
    context = Context(model)
    rows = []
    for (sheet, title), records in sorted(context.captions.items()):
        if title not in TARGETS:
            continue
        addresses = sorted({a for r in records for a in context.formula_rows[sheet, r['row']]})
        for address in addresses:
            observed = model.formulas[sheet, address]
            item = dict(cell=sheet + '!' + address, status='abstain', suggested_formula=None, rule=TARGETS[title])
            try:
                if not syntax_evidence(observed)['supported']:
                    raise ValueError('observed_complete_ast_required')
                candidate, evidence = context.candidate(sheet, address, title)
                if not syntax_evidence(candidate)['supported']:
                    raise ValueError('candidate_complete_ast_required')
                item['evidence'] = evidence
                if equivalent(observed, candidate, sheet, model):
                    item['reason'] = 'observed_matches_hypothesized_relation'
                else:
                    item.update(status='propose', suggested_formula=candidate,
                                reason='visible_roles_conflict_with_fixed_domain_hypothesis')
            except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
                item['reason'] = str(error)
            rows.append(item)
    # A duplicate output title is an abstention, never multiple suggestions.
    assert len({r['cell'] for r in rows}) == len(rows)
    return dict(version=VERSION, formula_count=len(model.formulas), rows=rows,
                suggestions=[r for r in rows if r['status'] == 'propose'],
                author_intent_proven=False, automatic_edits_applied=False)
