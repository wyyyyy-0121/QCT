# AEDIST Err:510 frozen-model replication

Run date: 2026-10-19. The preregistration was committed before inference. This is disclosed natural development evidence because the public author history and provenance notes identify the affected cells and same-day correction.

## Input and execution integrity

- The original and corrected XLSX exports each contained 5,484 formula cells. The target formulas survived ODS-to-XLSX conversion: original `Power plants!N254` and `N255` were malformed nested `of:=` formulas; the corrected formulas were `=1330/2` and `=N254`, respectively. The original export produced `#VALUE!` caches and the corrected export produced `665` at both cells; cache agreement is not used as a correctness label.
- Input SHA-256: original `c4f362478121f50771341e4dcc72c307201fee1598ae8adf3f3691b204f459cf`; corrected `a7191b168c0bacfb249bd48b783d4b59b0e9bdd5dbc69e4e3d93d03f9b1fec7e`.
- All four inference tasks (two snapshots at each worker setting) completed. The prediction interface reports `original_unchanged: true`, reads no scoring labels, and produced the same per-input output hashes at 1 and 8 requested workers: original `048e0e04cc8582dd2bff34e89477754d1a9c51b7137e9b661a822766d1b8dc74`; corrected `892a465a32d0b4c890b3bb82fc2c4f60c27e42fddbfdc7d93de863cf95c806de`.
- Raw workbooks, predictions, and runtime logs remain in the ignored `source_evidence/raw/aedist_err510/` directory; only this bounded report and manifests are tracked.

## Target results

| Target | Author-corrected formula | Paper-model output on defective snapshot | Exact repair | dev11 output |
|---|---|---|---:|---|
| `Power plants!N254` | `=1330/2` | local anomaly; suggests `=of:=of:=N253` from `Power plants!N255` | No | abstain; no qualified candidate |
| `Power plants!N255` | `=N254` | local anomaly; suggests `=of:=of:=1330/2` from `Power plants!N254` | No | abstain; no qualified candidate |

Paper-model exact repair coverage is `0/2`; dev11 exact repair coverage is `0/2`. Candidate reach for the author-corrected formulas is `0/2` for both. Both targets remain in the denominator. These target-only figures do not estimate whole-workbook suggestion precision or accuracy.

## Runtime

The same two workbooks were run with numeric-library thread limits fixed to one. One-worker batch wall time was 13.98 s, child CPU sum 13.77 s, sampled aggregate peak RSS 148,697,088 bytes, and throughput 0.143 tasks/s. The eight-worker batch wall time was 7.34 s, child CPU sum 14.49 s, sampled aggregate peak RSS 297,066,496 bytes, and throughput 0.272 tasks/s, for a 1.90x speedup over the one-worker batch. Since the batch contained only two tasks, at most two workers were active; this does not measure 8-way saturation or large-batch scaling. The observed summed CPU/wall ratio was about 1.97 in the concurrent batch, not 8-10 cores.

## Interpretation and disposition

The frozen detector localized both disclosed defects but ranked reciprocal formulas from the defective neighbor as repair candidates. The selector abstained, protecting against an unsupported repair but leaving both known errors unrepaired. This is evidence of a candidate-selection/execution gap on this disclosed two-cell case; it does not establish prevalence or general performance. Keep the source permanently excluded from blind final validation, do not tune on it, and leave final-validation source/template counts unchanged at `0/0`.
