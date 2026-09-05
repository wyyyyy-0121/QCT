# FormulaGuard VDEL preregistration amendment 1

Date frozen: 2026-09-03

Parent protocol: `formulaguard_vdel_v1`

Status: frozen after two pre-output input refusals and before any complete U0
receipt, longevity manifest, overlap result, or aggregate label count existed

## Discovery

The first formal U0 attempt stopped before creating an output directory because
the VDEL formula-profile validator encountered a non-formula string. A read-only
diagnostic established that current openpyxl represents array formulas with an
`ArrayFormula` object whose stable formula text is in its `text` attribute. The
old shared VEnron extractor instead called `str(cell.value)`, producing strings
of this form:

`<openpyxl.worksheet.formula.ArrayFormula object at 0x...>`

The public-workbook extractor was corrected to retain `ArrayFormula.text`, a
regression test was added, and the complete 656-test suite passed. A second
pre-output U0 attempt then found the same object-rendering artifact already
embedded in a frozen VEnron V0 profile shard. The recorded hexadecimal address
is process-specific, is not formula text, and can create false formula changes
between versions. The existing V0 resource counts remain historical evidence
but cannot make those particular profiles valid VDEL inputs.

Neither failed attempt wrote `results/vdel_u0_run_a`, a partial output directory,
a label manifest, an overlap result, or aggregate longevity counts. The only
row-level diagnostic before this amendment stopped at the first affected
profile. No threshold or label outcome was observed.

## Frozen handling

Before near-duplicate comparison or longevity classification, U0 must scan every
profile in each otherwise eligible candidate evolution group. A profile has
valid formula text only when every retained formula field is a nonempty string
whose end-trimmed value starts with `=`. This admits stable ordinary and array-
formula text and rejects object representations, blank values, and other opaque
formula payloads.

If any version in a candidate evolution group has invalid formula text, exclude
that complete group from overlap analysis, ranking windows, controls, folds, and
all U1 inputs. The receipt records only the number of excluded groups and stable
hashes of their opaque group IDs. It must not export the invalid strings, source
paths, worksheet names, cell addresses, or memory-address fragments.

The U0 integrity gate additionally requires:

1. every candidate group was checked before classification;
2. every invalid-profile group was excluded in full;
3. zero ranking or control rows come from an invalid-profile group;
4. both formal runs reproduce the invalid-group hash set byte for byte.

This amendment does not regenerate or alter the frozen VEnron V0 profiles,
change any sample-size threshold, add a label family, relax overlap detection,
extend the future horizon, or authorize U1 after a failed U0 gate.
