"""Certified pointwise validity; observed formula competes with every edit."""
from collections import defaultdict
import numpy as np
from candidate_features_dev16 import PARAMETERS, THRESHOLD, MARGIN, choose
from certified_preferences_dev22 import MAX_NEGATIVE_CANDIDATES

KEEP = '__observed_formula__'
KEEP_MARGIN = .05


def options(alternatives):
    groups = defaultdict(list)
    for r in alternatives:
        if r['label'] not in (0, 1, None) or r['kind'] not in ('keep', 'candidate'):
            raise ValueError('certified alternative required')
        groups[r['case'], r['cell']].append(r)
    rows = []
    for key, values in sorted(groups.items()):
        if len({r['id'] for r in values}) != len(values) or sum(r['kind']=='keep' for r in values) != 1:
            raise ValueError('unique alternatives and exactly one original required')
        positives = sorted((r for r in values if r['label']==1), key=lambda r:r['id'])
        negatives = sorted((r for r in values if r['label']==0 and r['kind']=='candidate'), key=lambda r:r['id'])[:MAX_NEGATIVE_CANDIDATES]
        negatives += [r for r in values if r['kind']=='keep' and r['label']==0]
        rows.extend(positives+negatives)
    return rows


def select(candidates, probabilities, keep_scores):
    grouped = defaultdict(list)
    if len(candidates) != len(probabilities): raise ValueError('candidate scores length')
    for c, p in zip(candidates, probabilities):
        if not np.isfinite(p): raise ValueError('nonfinite score')
        grouped[c['cell']].append((c, float(p)))
    selected = []
    for cell, values in sorted(grouped.items()):
        p_keep = keep_scores[cell]
        if not np.isfinite(p_keep): raise ValueError('nonfinite keep score')
        row = choose([c for c,p in values], [p for c,p in values])
        if row and row['probability'] - p_keep >= KEEP_MARGIN:
            selected.append(dict(row, keep_probability=float(p_keep)))
    return selected


def infer(model, payload, x, k, positions, unit_names):
    from run_unit_learning_dev20 import unit_filter
    column = list(model.classes_).index(1)
    scores = model.predict_proba(x)[:, column] if len(x) else np.empty(0, dtype=np.float64)
    keep = model.predict_proba(k)[:, column] if len(k) else np.empty(0, dtype=np.float64)
    keep_scores = {c['cell']: float(keep[positions[n]]) for n,c in enumerate(payload['candidates'])}
    raw = select(payload['candidates'], scores, keep_scores)
    selected = unit_filter(raw, payload['candidates'], x[:,-len(unit_names):], unit_names)
    old = {r['cell'] for r in payload['baseline']}
    return scores, keep, dict(dev11=payload['baseline'], learned_only=selected, learned_unfiltered=raw,
        keep_base_plus_learned=payload['baseline']+[r for r in selected if r['cell'] not in old])
