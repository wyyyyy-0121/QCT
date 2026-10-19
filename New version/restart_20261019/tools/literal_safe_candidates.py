"""Protect Excel literals around the paper's existing formula transformations.

No new grammar or repair heuristic. Install only in an isolated prediction
process/context; the frozen source files remain unchanged.
"""
from contextlib import contextmanager
import re
import sys

QUOTED = re.compile(r'"(?:[^\"]|\"\")*"|\'(?:[^\']|\'\')*\'(?=!)')


def protect(formula):
    stored = {}
    marker = '\ue000'
    while marker in formula:
        marker += '\ue001'

    def replacement(match):
        value = match.group()
        # No letters, numbers, operators or whitespace inside placeholders.
        placeholder = value[0] + marker + '\ue002' * (len(stored) + 1) + value[-1]
        stored[placeholder] = value
        return placeholder

    masked = QUOTED.sub(replacement, formula)

    def restore(value):
        for placeholder, original in stored.items():
            value = value.replace(placeholder, original)
        return value

    return masked, restore


def wrap_transforms(formula_module):
    originals = {name: getattr(formula_module, name) for name in (
        'translate_formula', 'small_edit_candidates_with_kinds', 'normalized_formula')}

    def translate(formula, origin, target):
        masked, restore = protect(formula)
        return restore(originals['translate_formula'](masked, origin, target))

    def candidates(formula):
        masked, restore = protect(formula)
        return [(restore(candidate), kinds) for candidate, kinds in
                originals['small_edit_candidates_with_kinds'](masked)]

    def normalize(formula):
        masked, restore = protect(formula)
        return restore(originals['normalized_formula'](masked))

    return originals, dict(translate_formula=translate, small_edit_candidates_with_kinds=candidates,
                          normalized_formula=normalize)


@contextmanager
def literal_safe_paper():
    import formulaguard.formula as formula_module
    # Import model dependencies first so their bound references are also replaced.
    import formulaguard.v5_structural_guard
    import formulaguard.workbook
    originals, replacements = wrap_transforms(formula_module)
    patches = []
    for name, module in list(sys.modules.items()):
        if module is None or not name.startswith(('formulaguard.', 'hybridguard.')):
            continue
        for attr, original in originals.items():
            if getattr(module, attr, None) is original:
                patches.append((module, attr, original))
                setattr(module, attr, replacements[attr])
    try:
        yield replacements
    finally:
        for module, attr, original in reversed(patches):
            setattr(module, attr, original)
