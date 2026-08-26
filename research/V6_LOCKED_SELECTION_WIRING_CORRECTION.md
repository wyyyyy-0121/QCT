# V6 locked-selection wiring correction

Date: 2026-08-26

## What was found

After V6-A, V6-B and V6-C development predictions were complete, but before
the 360-event locked validation had been run, the implementation was compared
against the frozen method specification. `research/V6_METHOD_SPEC.md` states
that all A/B/C validation predictions must be written before labels are read,
and that variant eligibility is decided from the locked validation gates.

`scripts/select_v6_variant.py` nevertheless contained one additional gate,
`development_round_passed`, which was not listed in the frozen selection
protocol. Because each development round uses the same 240 clean controls,
that extra gate could prevent the registered locked comparison from running at
all. It changed the experimental workflow rather than the model, but it did not
match the preregistration.

## Correction boundary

- Removed `development_round_passed` from the locked selection gate set.
- Preserved the same value as
  `development_round_passed_diagnostic`, together with all failed development
  gate names, so no negative development result is hidden.
- Added an A/B/C comparison receipt that explicitly performs no selection.
- Corrected round-report wording so it does not claim that a development
  diagnostic can replace the locked validation decision.
- Added a protocol regression test that rejects reintroduction of the extra
  development selection gate.

No change was made to `formulaguard/v6.py`, V4, V5.2, any formula score,
candidate, threshold, constant, dataset, label or prediction shard. The fixed
V6 source hash used by all three development rounds remains
`75296073a37c31c422364361d7fde7d6da0a313b816b5e7d7f5cc71b95d2a3c3`.
The locked validation had not been run and its labels had not been read when
this wiring correction was made.

## Consequence

Development results remain diagnostic: all A/B/C rounds have a 16.67% clean
promotion rate on the registered control set, and that failure is retained in
their audits. The one-shot locked validation must still evaluate all fixed
variants and matched ablations; only its preregistered gates may authorize a
freeze. If no variant passes, V6 stops without tuning or a V7.
