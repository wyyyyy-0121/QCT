"""Preserve unresolved visible business policies before qualifying repairs.

This guard recognizes policy-bearing text, not its meaning. It conservatively
routes proposals on that sheet to review until a policy interpreter is available.
Absence of a recognized marker does not prove absence of a legitimate exception.
"""
from collections import defaultdict
import re

from formulaguard.a1 import parse_address, num_to_col
from selector_dev2 import select as select_dev2

VERSION = 'hybridguard-followup-selector-dev3'
POLICY_MARKERS = frozenset({
    'business policy', 'business policies', 'business rules', 'business exceptions',
    'policy notes', 'assumptions', 'model assumptions', 'exceptions', 'notes',
    '业务规则', '业务说明', '业务例外', '假设', '备注',
})


def policy_notes(model):
    """Only nonformula prose adjacent to an explicit marker triggers this guard."""
    found = defaultdict(list)
    for (sheet, address), value in sorted(model.cells.items()):
        if (sheet, address) in model.formulas or not isinstance(value, str):
            continue
        # Accept "Notes: ..." as well as a separate header and adjacent text.
        pieces = re.split(r'[:：]', value, maxsplit=1)
        marker = ' '.join(pieces[0].strip().casefold().split())
        if marker not in POLICY_MARKERS:
            continue
        a = parse_address(address)
        targets = [(address, pieces[1].strip())] if len(pieces) == 2 else []
        targets += [(num_to_col(a.col) + str(a.row + 1), None),
                    (num_to_col(a.col + 1) + str(a.row), None)]
        for target, inline in targets:
            key = sheet, target
            text = inline if inline is not None else model.cells.get(key)
            if key in model.formulas or not isinstance(text, str) or not text.strip():
                continue
            # Avoid treating another recognized heading as its own policy body.
            if ' '.join(text.strip().casefold().split()) in POLICY_MARKERS:
                continue
            found[sheet].append({'marker_cell': address, 'text_cell': target,
                                 'scope': 'sheet conservatively; exact scope unresolved'})
    return dict(found)


def review_guard(model, prediction):
    policies = policy_notes(model)
    rows = []
    for original in prediction['rows']:
        row = dict(original)
        sheet = row['cell'].rsplit('!', 1)[0]
        row['selector_version'] = VERSION
        if row['status'] == 'propose' and sheet in policies:
            row.update(status='review', suggested_formula=None, candidate_formula=None,
                       review_candidate=original['suggested_formula'],
                       reason='unresolved_visible_business_policy',
                       policy_evidence=policies[sheet])
        rows.append(row)
    return {**prediction, 'rows': rows, 'selector_version': VERSION,
            'policy_guard': {'policies': policies, 'interpreted': False},
            'limitation': 'Header direction remains a hypothesis. Marked policy prose requires review; '
                          'unmarked exceptions and coefficient intent remain unresolved.'}


def select(model, original, fg_rows, sg_rows, parallel_sheets):
    return review_guard(model, select_dev2(model, original, fg_rows, sg_rows, parallel_sheets))
