"""Use frozen, label-free parallel-sheet metadata; fail on stale names."""
def corrected_index(root, items, read, sha):
    result = []
    for original in items:
        item = dict(original)
        if item['group'] == 'regression':
            path = root / 'baseline/data' / item['id'] / 'public.json'
            metadata = read(path)
            names = metadata['parallel_sheets']
            if (not isinstance(names, list) or not names
                    or any(not isinstance(name, str) or not name for name in names)
                    or len(set(names)) != len(names)):
                raise ValueError('Invalid frozen parallel-sheet declaration')
            item['previous_parallel_sheets'] = item['parallel_sheets']
            item['parallel_sheets'] = names
            item['parallel_metadata'] = str(path.relative_to(root))
            item['parallel_metadata_sha256'] = sha(path)
        result.append(item)
    return result


def assert_parallel_sheets(model, declared):
    present = {s for s, _ in model.formulas}
    missing = set(declared) - present
    if missing:
        raise ValueError('Declared parallel sheets absent from formula input: ' + ', '.join(sorted(missing)))
