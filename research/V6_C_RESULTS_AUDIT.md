# FormulaGuard V6-C data-quality and result audit

## Technical summary

V6-C is trustworthy as a completed development diagnostic, but it did not pass its preregistered round gate and is not eligible for freezing. Development macro Top-5 rose from 43.67% to 90.58%; red-team macro Top-5 rose from 40.00% to 85.28%. However, clean false alarms were 40/240 (16.67%) and Enron MRR changed by +0.00000000. Failed gates: clean_false_alarm_at_most_10_percent.

## The gain is large but uneven

On 1,200 development events, MRR improved from 0.2986 to 0.4388, with 563 new Top-5 hits and 0 losses. On 360 red-team events, MRR improved from 0.2345 to 0.3565, with 166 gains and 3 losses. V6-C must be interpreted jointly with A and B: its registered safety constraints are useful only if they reduce harmful promotions while preserving the semantic gains.

## Legitimate exception formulas cause every clean alarm

All 40 alarms occur in the `exception` structure; its false-alarm rate is 100.00%, while every other clean structure is 0%. This is a systematic failure mode rather than diffuse noise: an alternating but intentional MAX/MIN family looks locally inconsistent and receives a strong counterfactual promotion.

## Enron is practically unchanged and passes the exact safety rule

The retrospective Enron set contains 30 supported events from 25 workbooks. 0 event(s) changed rank. Top-5 stayed at 50.00%; the exact non-decrease rule passes because MRR changed by +0.00000000.

## Scope, definitions, and integrity checks

- Grain: one row per `(instance_id, method)` in scored CSV files; one complete-ranking JSON shard per workbook.
- Top-k: the true source formula has rank at most k. MRR is `1/rank`; EXAM is `rank/formula_count`.
- Clean alarm: any semantic promotion on a correct clean workbook.
- Development and red-team raw keys are unique; metric identities and aggregate summaries were independently recomputed.
- All prediction receipts report 24 requested workers, complete non-duplicate rankings and no label files read during localization.
- Enron is retrospective only and cannot be presented as new independent evidence.

## Limitations and robustness

V6-C is the final preregistered development variant. Its result must not trigger another tuning round; eligibility for locked validation follows only from the registered gates and the A/B/C comparison. The corrected Enron comparison uses all 30 evaluation-ready events from the existing corpus and remains retrospective rather than independent evidence.

A one-workbook diagnostic probe found that the fixed A, B and C implementations all promote a candidate on `data/v6_clean/clean/v6_clean_0201.xlsx`. This probe is not a population result, but it warns that the currently registered B/C safeguards may not remove the exception-family false-alarm mechanism.

## Recommended next step

Audit A, B and C together, then run the preregistered one-shot locked internal validation. All A/B/C predictions and matched ablations must be written before labels are read; the locked validation gates then determine whether freezing is allowed.

## Further questions

- Do the C safety constraints reduce clean alarms and harmful red-team promotions?
- Are the registered function and range gains preserved under C?
- Do the fixed ablations confirm that FFC/BSS and the safety constraints each add non-redundant value?
