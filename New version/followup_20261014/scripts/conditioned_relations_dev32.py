"""Actual standard-domain repair hypotheses with uncached input conditions.

Visible roles plus successful execution constrain a hypothesis; neither proves
contractual intent. Unmarked business exceptions remain a scored failure mode.
"""
from collections import ChainMap, defaultdict
from copy import copy
import math

from formulaguard.a1 import parse_address, num_to_col
from dependency_execution_dev31_v2 import Executor
from relation_algebra_dev32 import Comparator
from selector_dev11 import syntax_evidence
from visible_relations_dev30 import Context, norm, EXCEPTION, INSTRUCTION

VERSION = 'hybridguard-conditioned-profit-debt-dev32-v1'
PROFIT_REQUIRED = ['units', 'unit price', 'unit cost', 'shipping']
PROFIT_OPTIONAL = ['discount rate', 'tax rate']
PROFIT_NAMES = set(PROFIT_REQUIRED + PROFIT_OPTIONAL + ['net profit'])
DEBT_NAMES = ['opening balance', 'drawdowns', 'principal repayment', 'closing balance']
MONEY_UNITS = {'£', 'gbp', 'k£', 'kgbp', '$', 'usd', 'k$', 'kusd', '€', 'eur', 'k€', 'keur'}


class Hypotheses:
    def __init__(self, model, inputs):
        self.model = model
        self.context = Context(model)
        self.engine = Executor(model, inputs)
        self.algebra = Comparator(model)
        self.blocker_cache = {}
        self.by_column = defaultdict(list)
        for sheet, texts in self.context.texts.items():
            for item in texts:
                self.by_column[sheet, item['col']].append(item)

    def blockers(self, sheet, names):
        key = sheet, tuple(sorted(names))
        if key in self.blocker_cache:
            reason = self.blocker_cache[key]
            if reason:
                raise ValueError(reason)
            return
        for item in self.context.texts[sheet]:
            if not item['visible']: continue
            text = norm(item['text'])
            if EXCEPTION.search(text):
                reason = 'visible_exception_or_policy_note:' + item['address']
                self.blocker_cache[key] = reason
                raise ValueError(reason)
            if INSTRUCTION.search(text) and any(name in text for name in names):
                reason = 'unverified_visible_instruction:' + item['address']
                self.blocker_cache[key] = reason
                raise ValueError(reason)
        self.blocker_cache[key] = None

    def value(self, key, low=None, high=None):
        if not self.model.is_visible(key):
            raise ValueError('hidden_input')
        result = self.engine.execute(key)
        if result['status'] != 'executed':
            raise ValueError('unsupported_input:' + result['reason'])
        if result['value']['kind'] != 'number':
            raise ValueError('nonnumeric_input_result')
        if result['audit']['hidden_cells']:
            raise ValueError('hidden_static_dependency')
        value = result['value']['value']
        if not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
            raise ValueError('input_outside_hypothesis_domain')
        return result

    def profit(self, sheet, address, header):
        self.blockers(sheet, PROFIT_NAMES)
        target = parse_address(address)
        if not header['visible'] or not self.model.is_visible((sheet, address)):
            raise ValueError('hidden_profit_header_or_target')
        preceding = [t for t in self.by_column[sheet, target.col] if t['row'] < target.row]
        if not preceding or max(preceding, key=lambda t:t['row'])['address'] != header['address']:
            raise ValueError('profit_header_scope_ended')
        titles = defaultdict(list)
        for item in self.context.texts[sheet]:
            if item['row'] == header['row']:
                titles[norm(item['text'])].append(item)
        if len(titles['net profit']) != 1:
            raise ValueError('duplicate_profit_output_role')
        bindings, inputs = {}, []
        for name in PROFIT_REQUIRED + PROFIT_OPTIONAL:
            items = titles.get(name, [])
            if not items and name in PROFIT_OPTIONAL:
                continue
            if len(items) != 1 or not items[0]['visible'] or items[0]['col'] == target.col:
                raise ValueError('missing_duplicate_or_hidden_profit_role:' + name)
            cell = num_to_col(items[0]['col']) + str(target.row)
            key = sheet, cell
            if key not in self.model.formulas and key not in self.engine.inputs:
                raise ValueError('missing_profit_input')
            execution = self.value(key, low=0, high=1 if name in PROFIT_OPTIONAL else None)
            bindings[name] = cell
            inputs.append(dict(role=name, caption_cell=items[0]['address'], value_cell=cell, execution=execution))
        units, price, cost, shipping = (bindings[k] for k in PROFIT_REQUIRED)
        revenue = units + '*' + price
        for rate in PROFIT_OPTIONAL:
            if rate in bindings: revenue += '*(1-' + bindings[rate] + ')'
        candidate = '=' + revenue + '-' + units + '*' + cost + '-' + shipping
        return candidate, dict(rule='standard_profit', header_cell=header['address'], inputs=inputs,
                               missing_rates='omitted factor', business_assumptions='standard sales receipts less direct costs and shipping')

    def debt(self, sheet, address):
        self.blockers(sheet, DEBT_NAMES)
        target = parse_address(address)
        titles = {name:self.context.unique(sheet, name) for name in DEBT_NAMES}
        if target.row != titles['closing balance']['row'] or not self.model.is_visible((sheet, address)):
            raise ValueError('unbound_or_hidden_debt_output')
        units = []
        for item in titles.values():
            cell = num_to_col(item['col'] + 1) + str(item['row'])
            unit = self.model.cells.get((sheet, cell))
            if not isinstance(unit, str) or norm(unit) not in MONEY_UNITS or not self.model.is_visible((sheet, cell)):
                raise ValueError('unknown_or_hidden_debt_money_unit')
            units.append(norm(unit))
        if len(set(units)) != 1:
            raise ValueError('conflicting_debt_units')
        bindings, inputs = [], []
        for name in DEBT_NAMES[:-1]:
            cell = self.context.bind(sheet, titles[name], target.col)
            execution = self.value((sheet, cell), low=None if name == 'principal repayment' else 0,
                                   high=0 if name == 'principal repayment' else None)
            if name == 'principal repayment' and not execution['audit']['functions'].get('PPMT'):
                raise ValueError('principal_missing_complete_ppmt_chain')
            bindings.append(cell)
            inputs.append(dict(role=name, caption_cell=titles[name]['address'], value_cell=cell, execution=execution))
        return '=SUM(' + ','.join(bindings) + ')', dict(rule='signed_debt_balance', inputs=inputs, unit=units[0],
             business_assumptions='closing debt is opening debt plus drawdowns plus signed negative principal')

    def qualify(self, sheet, address, candidate, evidence):
        observed = self.model.formulas[sheet, address]
        if not syntax_evidence(observed)['supported'] or not syntax_evidence(candidate)['supported']:
            raise ValueError('complete_ast_pair_required')
        if self.algebra.equivalent(observed, candidate, sheet):
            return dict(status='abstain', suggested_formula=None, reason='observed_matches_hypothesis', evidence=evidence)
        original = self.engine.execute((sheet, address))
        if original['status'] != 'executed' or original['value']['kind'] != 'number':
            raise ValueError('observed_not_supported_numeric_execution')
        if original['audit']['hidden_cells']:
            raise ValueError('hidden_observed_static_dependency')
        altered = copy(self.model)
        altered.formulas = ChainMap({(sheet, address):candidate}, self.model.formulas)
        alternate = copy(self.engine); alternate.model = altered
        alternate.nodes = {k:v for k,v in self.engine.nodes.items() if k != (sheet, address)}
        execution = alternate.execute((sheet, address))
        if execution['status'] != 'executed' or execution['value']['kind'] != 'number':
            raise ValueError('candidate_not_supported_numeric_execution')
        if execution['audit']['hidden_cells']:
            raise ValueError('hidden_candidate_static_dependency')
        evidence.update(original_execution=original, candidate_execution=execution,
                        source='visible_roles_fixed_hypothesis_and_uncached_dependency_execution',
                        author_intent_proven=False)
        return dict(status='propose', suggested_formula=candidate,
                    reason='observed_conflicts_with_conditioned_domain_hypothesis', evidence=evidence)


def predict(model, inputs):
    context = Hypotheses(model, inputs); rows = []
    targets = {}
    for (sheet, caption), headers in sorted(context.context.captions.items()):
        if caption == 'net profit':
            for header in headers:
                for key in model.formulas:
                    pos = parse_address(key[1])
                    if key[0] == sheet and pos.col == header['col'] and pos.row > header['row']:
                        preceding = [t for t in context.by_column[sheet, pos.col] if t['row'] < pos.row]
                        if preceding and max(preceding, key=lambda t:t['row'])['address'] == header['address']:
                            targets[key] = ('standard_profit', header)
        elif caption == 'closing balance':
            for header in headers:
                for address in context.context.formula_rows[sheet, header['row']]:
                    targets[sheet, address] = ('signed_debt_balance', header)
    for (sheet, address), (rule, header) in sorted(targets.items()):
        row = dict(cell=sheet + '!' + address, status='abstain', suggested_formula=None, rule=rule)
        try:
            candidate, evidence = (context.profit(sheet, address, header) if rule == 'standard_profit'
                                   else context.debt(sheet, address))
            row.update(context.qualify(sheet, address, candidate, evidence))
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            row['reason'] = str(exc)
        rows.append(row)
    return dict(version=VERSION, formula_count=len(model.formulas), rows=rows,
                suggestions=[r for r in rows if r['status']=='propose'],
                author_intent_proven=False, automatic_edits_applied=False)
