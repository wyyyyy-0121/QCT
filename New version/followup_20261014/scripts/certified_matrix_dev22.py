"""Disk-backed certified comparisons, with the observed context on both sides."""
from collections import defaultdict
import gc
import hashlib
import numpy as np

KEEP = '__observed_formula__'


def build_matrix(path, rows, width, index, load_case):
    x = np.lib.format.open_memmap(path, mode='w+', dtype=np.float64,
                                 shape=(len(rows), 2 * width))
    by_case = defaultdict(list)
    for n, row in enumerate(rows):
        by_case[row['case']].append((n, row))
    for case, selected in by_case.items():
        payload, values, keep, positions = load_case(index[case])
        assert values.dtype == keep.dtype == np.float32
        lookup = {c['id']: n for n, c in enumerate(payload['candidates'])}
        cells = {c['cell']: positions[n] for n, c in enumerate(payload['candidates'])}
        for n, row in selected:
            context = keep[cells[row['cell']]]
            def vector(key):
                if key == KEEP:
                    return context
                pos = lookup[key]
                assert payload['candidates'][pos]['cell'] == row['cell']
                return values[pos]
            x[n, :width] = context
            x[n, width:] = vector(row['left_id']) - vector(row['right_id'])
        del payload, values, keep, positions, lookup, cells, context
    x.flush()
    del x, by_case
    gc.collect()
    with open(path, 'rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    return np.load(path, mmap_mode='r', allow_pickle=False), digest
