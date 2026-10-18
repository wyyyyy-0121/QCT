"""Disk-backed HGB input, preserving the registered float32 arithmetic exactly."""
import gc
import hashlib
from collections import defaultdict
import numpy as np


def build_matrix(path, rows, width, index, load_case):
    count = len(rows)
    # sklearn HGB validates input as float64. A float32 in-memory matrix would
    # coexist with its full float64 copy. Store already-rounded values directly
    # in a float64 mmap so validation needs no conversion or second matrix.
    x = np.lib.format.open_memmap(path, mode='w+', dtype=np.float64,
                                 shape=(2 * count, 2 * width))
    positions = defaultdict(dict)
    for n, row in enumerate(rows):
        assert row['id'] not in positions[row['case']]
        positions[row['case']][row['id']] = n
    for case, ids in positions.items():
        payload, values, keep_vectors, offsets = load_case(index[case])
        assert values.dtype == keep_vectors.dtype == np.float32
        found = 0
        for n, candidate in enumerate(payload['candidates']):
            if candidate['id'] not in ids:
                continue
            out = ids[candidate['id']]
            keep = keep_vectors[offsets[n]]
            delta = values[n] - keep  # subtraction stays float32, as registered
            x[out, :width] = x[out + count, :width] = keep
            x[out, width:] = delta
            x[out + count, width:] = -delta
            found += 1
        assert found == len(ids)
        # Do not retain the last case's Python candidate payload during fitting.
        del payload, values, keep_vectors, offsets, keep, delta
    x.flush()
    del x, positions
    gc.collect()
    with open(path, 'rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    return np.load(path, mmap_mode='r', allow_pickle=False), digest
