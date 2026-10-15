"""Paper components plus directional header evidence, without truth access.

Header interpretation is a limited hypothesis, not verified business intent.
Unknown roles and direction-preserving coefficient changes remain unresolved.
"""
from collections import Counter, defaultdict
import math
from formulaguard.a1 import parse_address, num_to_col
from formulaguard.formula import Number, Ref, Unary, Binary, parse_formula
from structuralguard.formula import profile_formula, translate_formula

VERSION = 'hybridguard-followup-selector-dev2'
PARAMETERS = {'column_min_support': 20, 'column_ratio': .75,
              'cross_min_support': 3, 'cross_ratio': .60,
              'output_roles': ['net profit', 'profit'],
              'direction_roles': {'unit price': 1, 'unit cost': -1,
                                  'discount rate': -1, 'shipping': -1},
              'version': VERSION}


def header_roles(model, sheet, col):
    # Only a plain first-row header is supported; multirow/unknown headers abstain.
    output = str(model.cells.get((sheet, num_to_col(col)+'1'), '')).strip().casefold()
    if output not in PARAMETERS['output_roles']:
        return {}
    roles = {}
    for (s, address), value in model.cells.items():
        a = parse_address(address)
        if s == sheet and a.row == 1 and isinstance(value, str):
            role = value.strip().casefold()
            if role in PARAMETERS['direction_roles']:
                roles[a.col] = (role, PARAMETERS['direction_roles'][role])
    return roles


def arithmetic(node, model, sheet, override):
    if isinstance(node, Number):
        return node.value
    if isinstance(node, Ref):
        key = (node.sheet or sheet, node.address.a1.replace('$', ''))
        if key in model.formulas:
            raise ValueError('formula dependency unsupported in directional check')
        value = override.get(key, model.cells.get(key))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError('requires nonnegative numeric inputs')
        return float(value)
    if isinstance(node, Unary):
        value = arithmetic(node.value, model, sheet, override)
        return value if node.op == '+' else -value
    if isinstance(node, Binary):
        left = arithmetic(node.left, model, sheet, override)
        right = arithmetic(node.right, model, sheet, override)
        if node.op == '+': return left + right
        if node.op == '-': return left - right
        if node.op == '*': return left * right
        if node.op == '/': return left / right
    raise ValueError('unsupported arithmetic or function')


def directional_check(model, formula, sheet, address, roles):
    if not roles:
        return {'available': False, 'violations': []}
    row = parse_address(address).row
    try:
        node = parse_formula(formula)
        violations = []
        checks = []
        baseline = arithmetic(node, model, sheet, {})
        if not math.isfinite(baseline): raise ValueError('nonfinite')
        for col, (role, direction) in sorted(roles.items()):
            key = (sheet, num_to_col(col)+str(row))
            value = model.cells.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError('role input unavailable')
            step = max(abs(value)*.01, .001)
            shifted = arithmetic(node, model, sheet, {key: value + step})
            effect = (shifted - baseline) / step
            if not math.isfinite(effect): raise ValueError('nonfinite')
            # A declared input expected to matter must have strict expected sign.
            violation = direction * effect <= 1e-8
            checks.append({'role': role, 'input': key[1], 'effect': effect,
                           'expected_direction': direction})
            if violation: violations.append(role)
        return {'available': True, 'violations': violations, 'checks': checks,
                'interpretation': 'header-derived hypothesis, not a business contract'}
    except (ValueError, ZeroDivisionError, OverflowError):
        return {'available': False, 'violations': []}


def select(model, original, fg_rows, sg_rows, parallel_sheets):
    profiles = {}; columns = defaultdict(list); positions = defaultdict(list)
    for key, formula in model.formulas.items():
        try:
            profiles[key] = profile_formula(formula, key[1], key[0])
            columns[(key[0],parse_address(key[1]).col)].append(key)
            if key[0] in parallel_sheets: positions[key[1]].append(key)
        except ValueError:
            pass
    counts = {k:Counter(profiles[x].exact_shape for x in v) for k,v in columns.items()}
    role_cache = {k:header_roles(model,*k) for k in columns}
    fg = {r['cell']:r for r in fg_rows}
    output = []
    for old in original['rows']:
        row = dict(old); label = row['cell']; sheet,address = label.rsplit('!',1)
        key = sheet,address
        row.update(status='abstain', suggested_formula=None,candidate_formula=None,
                   original_formula=model.formulas[key], selector_version=VERSION,
                   selection_evidence=[])
        p = profiles.get(key)
        if p is None:
            row.update(status='unsupported',reason='formula_profile_unavailable');output.append(row);continue
        colkey = sheet,parse_address(address).col
        actual = model.formulas[key]; roles = role_cache[colkey]
        current_direction = directional_check(model,actual,sheet,address,roles)
        row['directional_evidence'] = current_direction
        pool = defaultdict(list)
        keys = columns[colkey]; counter = counts[colkey]
        shape,support = counter.most_common(1)[0]
        if support >= PARAMETERS['column_min_support'] and support/len(keys) >= PARAMETERS['column_ratio']:
            anchor = next(k for k in keys if profiles[k].exact_shape==shape)
            pool[translate_formula(model.formulas[anchor],anchor[1],address)].append(
                {'kind':'within_sheet_column','support':support,'ratio':support/len(keys)})
        peers = positions[address]
        if len(peers) >= PARAMETERS['cross_min_support']:
            cross_shape,cross_support=Counter(profiles[k].exact_shape for k in peers).most_common(1)[0]
            if cross_support>=PARAMETERS['cross_min_support'] and cross_support/len(peers)>=PARAMETERS['cross_ratio']:
                anchor=next(k for k in peers if profiles[k].exact_shape==cross_shape)
                pool[translate_formula(model.formulas[anchor],anchor[1],address)].append(
                    {'kind':'parallel_sheet','support':cross_support,'ratio':cross_support/len(peers),
                     'independence':'unknown'})
        f=fg.get(label,{})
        if f.get('candidate_formula') and f.get('evidence',{}).get('candidate_peer_support',0)>=2:
            pool[f['candidate_formula']].append({'kind':'paper_formulaguard_peer'})
        # Retain paper group proposals as candidates; qualify every member anew.
        if old.get('group_id') and old.get('suggested_formula'):
            pool[old['suggested_formula']].append({'kind':'paper_group_candidate'})
        pool.pop(actual,None)
        qualified=[]
        for candidate,evidence in pool.items():
            cp=profile_formula(candidate,address,sheet)
            if cp.has_ref_error or cp.has_direct_self_reference or p.functions!=cp.functions:
                continue
            direction=directional_check(model,candidate,sheet,address,roles)
            kinds={e['kind'] for e in evidence}
            if current_direction['available'] and current_direction['violations']:
                if direction['available'] and not direction['violations'] and kinds & {'within_sheet_column','parallel_sheet','paper_group_candidate'}:
                    qualified.append((candidate,evidence,'directional_violation_resolved'))
            elif p.exact_shape!=shape and 'within_sheet_column' in kinds:
                # Direction-preserving constant changes may be business exceptions.
                # Keep them for review until a user contract or separate evidence exists.
                if p.constants==cp.constants and not (direction['available'] and direction['violations']):
                    qualified.append((candidate,evidence,'column_supported_nonconstant_anomaly'))
        if len(qualified)==1:
            candidate,evidence,reason=qualified[0]
            row.update(status='propose',suggested_formula=candidate,selection_evidence=evidence,reason=reason)
        elif len(qualified)>1:
            row.update(status='review',reason='conflicting_qualified_candidates')
        elif pool:
            row.update(status='review',reason='insufficient_semantic_or_role_evidence')
        else:
            row['reason']='no_qualified_candidate'
        output.append(row)
    return {'rows':output,'selector_version':VERSION,'parameters':PARAMETERS,
            'automatic_edit_applied':False,'labels_read':[],
            'limitation':'Directional roles are header hypotheses. Coefficient intent and source independence remain unverified.'}
