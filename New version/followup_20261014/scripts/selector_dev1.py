"""Development selection layer over the paper components. No label access."""
from collections import Counter, defaultdict
from formulaguard.a1 import parse_address
from structuralguard.formula import profile_formula, translate_formula

VERSION = "hybridguard-followup-selector-dev1"
PARAMETERS = {"column_min_support": 20, "column_ratio": 0.75,
              "local_min_support": 2, "cross_ratio": 0.8,
              "function_role_conflict": "review", "version": VERSION}


def select(model, original, fg_rows, sg_rows, parallel_sheets):
    """Keep ranking, independently qualify final suggestions and retain conflicts.

    Column consensus and local components are evidence, not business truth.
    Function-changing candidates are reviewed; supplied parallel-sheet declarations
    are retained as in the paper. The routine is intentionally a development model.
    """
    profiles = {}
    columns = defaultdict(list)
    positions = defaultdict(list)
    for key, formula in model.formulas.items():
        sheet, address = key
        try:
            p = profile_formula(formula, address, sheet)
            col = parse_address(address).col
            profiles[key] = p
            columns[(sheet, col)].append(key)
            if sheet in parallel_sheets:
                positions[address].append(key)
        except ValueError:
            continue
    counts = {k: Counter(profiles[x].exact_shape for x in v) for k, v in columns.items()}
    fg = {x['cell']: x for x in fg_rows}
    sg = {x['cell']: x for x in sg_rows}
    result = []
    for original_row in original['rows']:
        row = dict(original_row)
        label = row['cell']
        sheet, address = label.rsplit('!', 1)
        key = sheet, address
        actual = model.formulas[key]
        row.update(status='abstain', suggested_formula=None, original_formula=actual,
                   candidate_formula=None, selector_version=VERSION, selection_evidence=[])
        p = profiles.get(key)
        if p is None:
            row.update(status='unsupported', reason='formula_profile_unavailable')
            result.append(row)
            continue
        col = parse_address(address).col
        column_keys = columns[(sheet, col)]
        counter = counts[(sheet, col)]
        shape, support = counter.most_common(1)[0]
        candidates = defaultdict(list)
        if support >= PARAMETERS['column_min_support'] and support / len(column_keys) >= PARAMETERS['column_ratio'] and p.exact_shape != shape:
            anchor = next(x for x in column_keys if profiles[x].exact_shape == shape)
            candidate = translate_formula(model.formulas[anchor], anchor[1], address)
            if candidate:
                candidates[candidate].append({'kind': 'within_sheet_column', 'support': support,
                    'ratio': support / len(column_keys), 'source': anchor[0]+'!'+anchor[1]})
        f = fg.get(label, {})
        ev = f.get('evidence', {})
        if f.get('candidate_formula') and ev.get('candidate_peer_support', 0) >= PARAMETERS['local_min_support']:
            candidates[f['candidate_formula']].append({'kind': 'paper_formulaguard_peer',
                'support': ev['candidate_peer_support'], 'gain': ev.get('candidate_gain')})
        peers = positions[address]
        if len(peers) >= 3:
            cross = Counter(profiles[x].exact_shape for x in peers)
            cross_shape, cross_support = cross.most_common(1)[0]
            if cross_support >= 3 and cross_support / len(peers) >= PARAMETERS['cross_ratio'] and cross_shape != p.exact_shape:
                anchor = next(x for x in peers if profiles[x].exact_shape == cross_shape)
                candidate = translate_formula(model.formulas[anchor], anchor[1], address)
                if candidate:
                    candidates[candidate].append({'kind': 'parallel_sheet', 'support': cross_support,
                        'ratio': cross_support/len(peers), 'source': anchor[0]+'!'+anchor[1],
                        'independence': 'unknown'})
        candidates.pop(actual, None)
        # Strong disagreement inside a column is a conflict; do not silently select
        # between own-sheet structure and a cross-sheet majority.
        own_candidates = {c for c, es in candidates.items() if any(e['kind']=='within_sheet_column' for e in es)}
        local_candidates = {c for c, es in candidates.items() if any(e['kind']=='paper_formulaguard_peer' for e in es)}
        cross_candidates = {c for c, es in candidates.items() if any(e['kind']=='parallel_sheet' for e in es)}
        eligible = own_candidates or local_candidates
        if not eligible and cross_candidates:
            # A locally consistent full column may represent a legitimate different
            # business role. Require local evidence of a change before replacing it.
            if len(counter) > 1:
                eligible = cross_candidates
        if not eligible:
            row['reason'] = 'no_qualified_candidate' if not candidates else 'locally_consistent_or_unverified_reference'
            if candidates:
                row['status'] = 'review'
            row['selection_evidence'] = [{'formula': c, 'evidence': es} for c, es in candidates.items()]
        elif len(eligible) != 1:
            row.update(status='review', reason='conflicting_qualified_candidates')
            row['selection_evidence'] = [{'formula': c, 'evidence': candidates[c]} for c in sorted(eligible)]
        else:
            candidate = next(iter(eligible))
            row['candidate_formula'] = candidate
            row['selection_evidence'] = candidates[candidate]
            cp = profile_formula(candidate, address, sheet)
            if p.functions != cp.functions:
                row.update(status='review', reason='function_role_conflict')
            elif cp.has_ref_error or cp.has_direct_self_reference:
                row.update(status='review', reason='invalid_reference_candidate')
            elif own_candidates and local_candidates and own_candidates != local_candidates:
                row.update(status='review', reason='local_candidate_conflict')
            else:
                row.update(status='propose', suggested_formula=candidate, reason='qualified_structural_evidence')
        result.append(row)
    return {'rows': result, 'selector_version': VERSION, 'parameters': PARAMETERS,
            'automatic_edit_applied': False, 'labels_read': [],
            'limitation': 'Structural agreement cannot establish business intent or independent provenance.'}
