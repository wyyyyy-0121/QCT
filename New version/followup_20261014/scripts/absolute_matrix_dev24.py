"""Bounded absolute option matrix from the same frozen float32 features."""
from collections import defaultdict
import gc
import hashlib
import numpy as np
from absolute_selection_dev24 import KEEP


def build_matrix(path, rows, width, index, load_case):
    matrix = np.lib.format.open_memmap(path, mode='w+', dtype=np.float64, shape=(len(rows),width))
    grouped = defaultdict(list)
    for n,r in enumerate(rows): grouped[r['case']].append((n,r))
    for case,selected in grouped.items():
        payload,x,k,positions = load_case(index[case])
        assert x.dtype==k.dtype==np.float32 and x.shape[1]==k.shape[1]==width
        candidates = {c['id']:n for n,c in enumerate(payload['candidates'])}
        cells = {c['cell']:positions[n] for n,c in enumerate(payload['candidates'])}
        for n,row in selected:
            if row['id']==KEEP: matrix[n]=k[cells[row['cell']]]
            else:
                pos=candidates[row['id']]
                assert payload['candidates'][pos]['cell']==row['cell']
                matrix[n]=x[pos]
        del payload,x,k,positions,candidates,cells
    matrix.flush();del matrix,grouped;gc.collect()
    with open(path,'rb') as handle: digest=hashlib.file_digest(handle,'sha256').hexdigest()
    return np.load(path,mmap_mode='r',allow_pickle=False),digest
