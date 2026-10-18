"""Conservative visible declarations; dimensional evidence never authorizes signs."""
from bisect import bisect_left
from collections import defaultdict
from functools import lru_cache
import re

from formulaguard.a1 import parse_address
from unit_evidence_dev1 import UnitEvidence, UnknownUnit, parse_unit

VERSION = 'hybridguard-visible-unit-features-dev20-v1'
STATUSES = ('compatible', 'incompatible', 'unknown')
# Written scales are distinct formal units, not automatic physical conversion.
SYMBOLS = {'£': 'gbp', '£m': 'gbp_m', "£'000s": 'gbp_thousand',
           '$': 'usd', '€': 'eur', '%': '1'}
BARE = {'kg', 'g', 't', 'tonne', 'm', 'cm', 'mm', 'km', 's', 'h', 'hr',
        'day', 'year', 'l', 'ml', 'kwh', 'mwh', 'kw', 'mw', 'w',
        'usd', 'eur', 'gbp', 'gbp_m', 'gbp_thousand', '1'}

@lru_cache(maxsize=4096)
def written_unit(text, explicit=False):
    normalized = text.strip().casefold()
    if normalized in SYMBOLS:
        normalized = SYMBOLS[normalized]
    else:
        for symbol in ['£', '$', '€']:
            normalized = normalized.replace(symbol, SYMBOLS[symbol])
    result = parse_unit(normalized)
    if not explicit and any(k not in BARE for k, _ in result):
        raise UnknownUnit('not_standalone_unit_token')
    return result

class VisibleUnits(UnitEvidence):
    def __init__(self, model):
        super().__init__(model)
        self.row_units = defaultdict(list)
        for (s, a), value in model.cells.items():
            if ((s, a) in model.formulas or not isinstance(value, str)
                    or not model.is_visible((s, a))):
                continue
            try:
                u = written_unit(value)
            except (UnknownUnit, ValueError):
                continue
            p = parse_address(a)
            self.row_units[s, p.row].append((p.col, a, value, u))
        self.results = {}

    def declared(self, sheet, address):
        address = address.replace('$', '')
        key = sheet, address
        if key not in self._units:
            p = parse_address(address)
            declarations = []
            entries = self.headers.get((sheet, p.col), [])
            idx = bisect_left(self.header_rows.get((sheet, p.col), []), p.row) - 1
            if idx >= 0 and p.row - entries[idx][0] <= 8:
                _, a, text = entries[idx]
                match = re.search(r'\[([^\[\]]+)\]\s*$', text)
                if match:
                    try:
                        declarations.append((written_unit(match[1], explicit=True),
                                             {'cell': sheet+'!'+a, 'text': text}))
                    except (UnknownUnit, ValueError):
                        # An explicit unsupported declaration cannot be silently ignored.
                        self._units[key] = (None, 'unsupported_explicit_column_unit', None)
                        raise UnknownUnit('unsupported_explicit_column_unit')
            for c, a, text, u in self.row_units.get((sheet, p.row), []):
                if 0 < p.col-c <= 16:
                    declarations.append((u, {'cell': sheet+'!'+a, 'text': text}))
            unique = {u for u, _ in declarations}
            if len(unique) == 1:
                self._units[key] = (declarations[0][0], None,
                                    {'declarations': [e for _, e in declarations]})
            else:
                self._units[key] = (None, 'conflicting_visible_units' if unique else 'no_visible_unit', None)
        unit, error, evidence = self._units[key]
        if error:
            raise UnknownUnit(error)
        return unit, evidence

    def check(self, formula, sheet, address):
        key = sheet, address, formula
        if key not in self.results:
            self.results[key] = super().check(formula, sheet, address)
        return self.results[key]

    def features(self, sheet, address, observed, candidate):
        old = self.check(observed, sheet, address)['status']
        new = self.check(candidate, sheet, address)['status']
        return {**{'unit_old_'+s: float(old == s) for s in STATUSES},
                **{'unit_new_'+s: float(new == s) for s in STATUSES},
                **{'unit_delta_'+s: float(new == s)-float(old == s) for s in STATUSES}}
