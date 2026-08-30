# V5-PSL bounded parameter comparison failure 1

Date: 2026-08-30

## Evidence status

The comparison fixed by `V5_PSL_DEVELOPMENT_AMENDMENT_1.md` ran at commit
`c60b7ae440b9d6734cf3ba17345f9ec114786ffa` with 24 worker processes. It
completed 90 cases, 12 parameter profiles, the fixed `no_perturbation`
baseline, and 1,170 complete-ranking shards. All shard, metadata and event
hashes reproduced before this record was written:

- `tuning_complete.json`: `34598d31e4e46f41eca89bd5591ff42d3db7912a33acdf185c7df36f678f36e8`;
- metadata: `55f4f5346f8a365b3bde0a22b7d29b7711e24113f8e8751616ee9b5f3b501687`;
- events: `8ede62e89e613ab9e4cd6b3d61f3227ddc9517dc25a051728582c39540deca63`;
- aggregate shards: `6861952bd1fcb0f44835368a8b5d0b4e3b7158a4dd78677538e7345dcd9afd96`.

These files are ignored development results under
`results/v5_psl_parameter_tuning/`. They are revealed development evidence,
not a preregistered pass, independent validation, or superiority evidence. No
third-party confirmation file was read.

## Fixed decision

No profile was eligible. The best observed error Top-5 was 38.33%, every
profile retained a 30.00% control actionable rate, and the best eligible-style
efficiency among the conservative profiles was 6.06 source hits per 100
inspected cells. The fixed `no_perturbation` baseline retained 63.33% Top-5
and 8.54 hits per 100 cells. All profiles failed the Top-5, control-action,
efficiency and four-of-five-fold gates. `selected_profile=null` is therefore
final for this comparison. No near-miss is selected and parameter tuning stops.

## Failure surface and root cause

The result rules out a threshold-only explanation:

1. Response-first lexicographic ranking removed 22 errors from the static
   Top-5 and rescued only five under the default profile. Mean source rank
   worsened by 8.83 positions. Even the strict profile removed 19 and rescued
   four, with a mean worsening of 7.15 positions.
2. The median top-cell identifiability index was 1.73 for errors and 1.75 for
   clean controls. General response strength therefore identifies responsive
   workbook structure, not an error-specific source signal.
3. In 35 source cells with a same-original clean comparison, the response
   identifiability index was unchanged in 27, increased in three and decreased
   in five. Static anomaly score increased in 22. The injected formula change
   is usually visible to static structure but not to the current input-response
   fingerprint.
4. Localization margins 0.15 and 0.25 produced identical results. Tightening
   response thresholds reduced error reviews but did not remove any of the
   nine control actions.
5. Candidate repair probing used at most eight placebo edits while strong
   evidence required an empirical tail at most 0.10. With the finite-sample
   correction, the smallest attainable tail was `1/9`, so repair evidence was
   mathematically unable to become strong.

The candidate generator itself is not the primary bottleneck. Static ranking
placed 38 of 60 true sources in Top-5; 34 of those 38 had the known repair in
the first two label-free candidates. The single permitted mechanism revision
therefore anchors the complete ranking to static evidence and uses perturbation
only to verify repair specificity within that bounded review set.

## Consequence

This comparison does not consume the single structural mechanism revision,
but it fixes the evidence used to justify it. The revision is specified in
`V5_PSL_MECHANISM_REVISION_1.md`. After implementation it receives one fresh
public development run. If that run fails any fixed gate, the V5-PSL line
stops and the unseen 240+120 confirmation set remains unopened.
