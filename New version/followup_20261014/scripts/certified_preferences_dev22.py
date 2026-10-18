"""Construct preference pairs only from explicitly certified correctness states.

This module consumes training-fold labels; it never obtains or infers labels.
Unknown alternatives remain in the prediction pool, outside this constructor.
"""
from collections import defaultdict

MAX_NEGATIVE_CANDIDATES = 32


def certified_pairs(alternatives, max_negative_candidates=MAX_NEGATIVE_CANDIDATES):
    if not isinstance(max_negative_candidates, int) or max_negative_candidates < 0:
        raise ValueError('negative candidate cap must be a nonnegative integer')
    grouped = defaultdict(list)
    for row in alternatives:
        if row['label'] not in (0, 1, None):
            raise ValueError('correctness must be certified 0/1 or unknown None')
        if row['kind'] not in ('candidate', 'keep'):
            raise ValueError('alternative kind must be candidate or keep')
        grouped[row['case'], row['cell']].append(row)
    pairs = []
    stats = dict(targets=len(grouped), unknown_alternatives=0,
                 both_wrong_comparisons_excluded=0, both_correct_comparisons_excluded=0,
                 targets_without_certified_contrast=0, forward_pairs=0, directed_pairs=0)
    for (case, cell), rows in sorted(grouped.items()):
        if len({r['id'] for r in rows}) != len(rows):
            raise ValueError('alternative IDs must be unique within each target')
        if sum(r['kind']=='keep' for r in rows) != 1:
            raise ValueError('exactly one observed-formula alternative is required')
        positives = sorted((r for r in rows if r['label']==1), key=lambda r:r['id'])
        negatives = sorted((r for r in rows if r['label']==0 and r['kind']=='candidate'),
                           key=lambda r:r['id'])[:max_negative_candidates]
        # Explicit observed-formula comparison is retained independently of the
        # cap on generated negative candidates. No correctness is assumed here.
        negatives += [r for r in rows if r['kind']=='keep' and r['label']==0]
        known_wrong = sum(r['label']==0 for r in rows)
        stats['unknown_alternatives'] += sum(r['label'] is None for r in rows)
        stats['both_wrong_comparisons_excluded'] += known_wrong*(known_wrong-1)//2
        stats['both_correct_comparisons_excluded'] += len(positives)*(len(positives)-1)//2
        if not positives or not negatives:
            stats['targets_without_certified_contrast'] += 1
        for positive in positives:
            for negative in negatives:
                pair = dict(case=case, cell=cell, left_id=positive['id'], right_id=negative['id'], label=1)
                pairs.append(pair)
                pairs.append(dict(pair, left_id=negative['id'], right_id=positive['id'], label=0))
                stats['forward_pairs'] += 1
    stats['directed_pairs'] = len(pairs)
    return pairs, stats
