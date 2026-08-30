# V5-PSL public pressure failure 2: repair verification is not discriminative

Date: 2026-08-30
Status: terminal failure of the V5-PSL research line

## Evidence status

The single structural revision fixed in `V5_PSL_MECHANISM_REVISION_1.md` ran
once at commit `ff5e7006d2bc838aa00d946df90b8a4809b3e413` with 24 worker processes.
It completed all 90 revealed public-development cases and all four ablations.
An independent 24-process recomputation audit reproduced the complete semantic
outputs and produced these local, ignored evidence hashes:

- `public_pressure_complete.json`:
  `8a6239f3f6869171599f0a9e6fd7a3e14983ee8d9ea37b3a71be49013cc5c608`;
- public-pressure audit:
  `c5f0c60b80192eae1b3ba3c7099d7e32b4a8c091f5b52994cb96cca42be384c3`;
- events:
  `356dbe172efe96613361a9fc6060e7c3f8551e13995cfda873311750a6d865f5`;
- aggregate shards:
  `aacc095cd8e8c7e8a0f8c491f5b429bd586b7ee79c2731f474451f6d9040a4cc`.

The audit recorded `third_party_confirmation_files_read=[]`. These results are
revealed development evidence, not an independent test, a public-pressure pass,
or evidence of superiority.

## Fixed decision

The revision failed six fixed gates:

- control actionable rate was 36.67%, above the 15% maximum;
- review efficiency was 1.90 source hits per 100 inspected cells, below the
  fixed static Top-5 baseline of 8.54;
- localized coverage was 0%, below 30%;
- localized Top-1 and Top-5 were both 0%, below 75% and 95%;
- only two of five workbook-group folds were stable, below four.

The static-anchor contract itself reproduced exactly: `full` and
`no_perturbation` had identical complete rankings, with 63.33% global error
Top-5 and 36.67% Top-1. This does not rescue the method because the registered
contribution was selective repair verification, not a renamed static ranker.

## Failure mechanism

The failure is no longer candidate coverage. Static Top-5 contained 38 of 60
true sources, and every one of those 38 source rows had a selected candidate;
26 selected candidates exactly matched the formula in the original workbook.
Nevertheless, repair specificity verified only one true source.

The full method produced no `localized` case. Among errors, 49 abstained, ten
entered review and one was unsupported. The ten reviewed errors contained 11
verified repair families, but ten families were attached to non-source cells;
the only verified true source was static rank four and therefore correctly did
not satisfy the localization rule. Among clean controls, 11 of 30 workbooks
entered review from weak repair evidence. Repeated clean controls triggered the
same apparent repairs as related error workbooks, showing that the recovery
measure rewards regular computational structure rather than error correction.

Removing role conditioning did not provide a valid successor: that ablation
localized only 5% of identifiable errors, achieved 33.33% localized Top-1, and
still acted on 16.67% of controls. It failed the fixed coverage, accuracy and
control-action requirements and cannot be selected after observing the result.

## Consequence

This is the failure after the one permitted mechanism revision. V5-PSL is
terminated and must remain a reproducible negative result. No further threshold
tuning, repair-verification amendment, candidate lock, or release of the unseen
240-error plus 120-control confirmation set is permitted for this research
line. Any future main-model attempt must use a separately named and
preregistered architecture with a claim that is not repair-specific response
verification; the 90 cases used here remain revealed development data only.
