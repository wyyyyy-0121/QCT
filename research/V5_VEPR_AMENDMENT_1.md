# FormulaGuard VEPR preregistration amendment 1

Date frozen: 2026-09-03

Applies to: `research/V5_VEPR_PREREGISTRATION.md`

Status: frozen before any VEPR transition label, feature, model, or ranking was
materialized

## Reason

The base protocol pins the original VEnron formula-profile index. The completed
VDEL audit had already established, before VEPR was proposed, that one evolution
group in that pinned index contains at least one formula serialized as a
nondeterministic openpyxl object representation rather than stable formula text.
That known input defect must be handled explicitly before VEPR U0 opens adjacent
profiles.

## Frozen correction

Before eligibility, overlap matching, controls, labels, or folds are computed,
VEPR validates every formula row in every profile. A valid formula is a string
whose end-trimmed form starts with `=`. If any profile in an evolution group has
an invalid formula row, the complete evolution group is excluded from every
VEPR ranking transition, control, overlap comparison, feature, and model stage.

U0 must report the number of audited profiles and groups, the number of excluded
groups, and only salted hashes of excluded group identities. It must verify that
zero row from an invalid-profile group survives. Raw invalid strings, member
paths, formulas, sheet titles, addresses, and unsalted group IDs must not be
exported.

This amendment changes no sample threshold, transition rule, candidate label,
feature, learner, metric, or later gate. If complete-group exclusion makes any
existing U0 minimum fail, VEPR stops; the invalid group cannot be repaired,
partially retained, or counted with a replacement representation.

