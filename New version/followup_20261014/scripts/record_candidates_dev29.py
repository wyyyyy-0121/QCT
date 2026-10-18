"""Bounded adjacent-row candidates; row coherence is never repair authority."""
from collections import Counter
import re

from string_execution_dev28 import Concat
from string_execution_dev28_v2 import parse, execute, provenance, Unsupported

VERSION = 'text-record-candidates-dev29-v1-review-only'
REFERENCE_TOKEN = re.compile(
    r"(?:(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z_0-9.]*)!)?"
    r'(\$?[A-Za-z]{1,3})(\$?)([1-9][0-9]*)')


def generate(formula, sheet, address, inputs, formula_cells=(), sheet_names=None):
    """Return a review candidate, never a propose action or business label."""
    formula_cells = tuple(formula_cells)
    sheet_names = tuple(sheet_names) if sheet_names is not None else None
    try:
        node = parse(formula)
        if not isinstance(node, Concat):
            return dict(status='abstain', reason='not_text_concatenation')
        execute(node, sheet, inputs, formula_cells, sheet_names)
        refs = provenance(node, sheet)
        if any(r['sheet'].casefold() != sheet.casefold() for r in refs):
            return dict(status='abstain', reason='cross_sheet_reference')
        row = int(re.fullmatch(r'[A-Za-z]+([1-9][0-9]*)', address)[1])
        groups = Counter(int(re.search(r'[0-9]+$', r['address'])[0]) for r in refs)
        dissent = [r for r in refs if int(re.search(r'[0-9]+$', r['address'])[0]) != row]
        anchors = {re.match(r'[A-Z]+', r['address'])[0] for r in refs
                   if int(re.search(r'[0-9]+$', r['address'])[0]) == row}
        if len(anchors) < 3:
            return dict(status='abstain', reason='fewer_than_three_distinct_anchor_columns')
        if len(dissent) != 1:
            return dict(status='abstain', reason='not_exactly_one_offrow_reference')
        ref = dissent[0]
        old_row = int(re.search(r'[0-9]+$', ref['address'])[0])
        if abs(old_row - row) != 1 or ref['row_absolute']:
            return dict(status='abstain', reason='nonadjacent_or_absolute_row')
        match = REFERENCE_TOKEN.match(formula, ref['formula_offset'])
        if match is None or match[2] or int(match[3]) != old_row:
            return dict(status='abstain', reason='reference_offset_not_verified')
        candidate = formula[:match.start(3)] + str(row) + formula[match.end(3):]
        edited = parse(candidate)
        new_refs = provenance(edited, sheet)
        assert len(new_refs) == len(refs)
        execute(edited, sheet, inputs, formula_cells, sheet_names)
        return dict(status='candidate_for_review', candidate_formula=candidate,
                    changed_reference=ref, anchor_columns=sorted(anchors),
                    observed_reference_rows=dict(groups), business_authority=False,
                    automatic_repair_allowed=False)
    except Unsupported as error:
        return dict(status='unsupported', reason=error.code)
