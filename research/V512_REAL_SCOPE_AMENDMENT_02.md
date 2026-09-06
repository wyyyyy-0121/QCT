# Retrospective label-scope audit

All three methods completed both runs on the 25 copied Enron workbooks. Every
run_a/run_b lock pair was byte-identical after the pre-reveal timer correction.
The original strict real scorer then verified prediction hashes, wrote reveal
authorization, loaded labels, and rejected `enron_event_04`: two of its twenty
annotated positions were not in the complete formula ranking. Further audit
found `enron_event_13` has 146 of 337 annotated positions outside that ranking.

The strict scorer and its failed output directory are preserved. No model,
parameter, prediction, source lock, or synthetic gate was changed. A separately
versioned retrospective analyzer (`scripts/evaluate_v512_real_retrospective.py`)
rechecks the original authorization and hashes, and reports:

- All 30 included events. Missing formula labels receive zero credit in the
  full-label AP denominator; no event is silently discarded.
- The 28 events whose labels are completely present in the formula ranking.
- All 148 missing coordinates, per-event rankability, and both AP denominators.
- No repair precision or false-positive rate: Enron's available labels do not
  establish complete correct repair formulas or clean-cell truth.

The results record the supplemental analyzer SHA-256. This amendment was made
after observing a real label-scope error and is retrospective, not preregistered
confirmation. It does not turn these previously used workbooks into unseen data.

The V4 algorithm file matches its historical release, but all methods run on the
common parsing runtime in the current evaluation snapshot. V4's shared a1,
formula, and workbook modules differ from its original full release tree.
