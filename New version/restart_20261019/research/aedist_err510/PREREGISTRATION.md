# AEDIST Err:510 natural-error development replication

Registered 2026-10-19 before running the frozen model. This is a disclosed development replication, not a blind test: the public author commit and repository documentation already identify the affected source row and the same-day correction.

## Source and version lineage

- Repository: `MinhHaDuong/aedist-technical-report`, repository license metadata `CC-BY-4.0`.
- Defective snapshot: `data/reference/raw/pipeline-2026-06-05.ods`, Git blob `260d4b56bc9fb7586aebb8477d0a9b5311225f0d`, present at commit `9ba17cd3f7caba49ebd6bdcaa8d9dff55974805e` (2026-06-05 10:35:30 UTC).
- Corrected snapshot: same path, Git blob `380fa58e1149e88ce3ec09d8a4a39e1e47b4b0f5`, recaptured at commit `2ad5b210d71707a7d5171284319ece12546d6bcc` (2026-06-05 11:50:52 UTC). The commit message explicitly identifies the same-day `Err:510` capacity fix; `data/reference/PROVENANCE.md` documents the defective and corrected snapshot lineage.
- The public history discloses the defect location and repair. Therefore this source is permanently ineligible for final validation and may only be reported as disclosed natural development evidence.
- Original and corrected ODS snapshots are held only under ignored `source_evidence/raw/aedist_err510/`. LibreOffice-converted XLSX files are used only to exercise the frozen XLSX inference interface. No workbook body or full formula map will be committed.

## Frozen inference and scoring

- Run the unchanged `HybridGuard_V5_handoff_20260904` paper model through `tools/predict_workbook.py` on both converted snapshots; keep dev11 output as a separately reported comparator.
- No model, candidate-generation, threshold, or rule changes are permitted in this replication.
- The only certified error targets are `Power plants!N254` and `Power plants!N255`, as documented by the source author. For these two cells, report exact corrected-formula suggestion reach and exact repair count separately. Both targets remain in the coverage denominator even if there is no suggestion, parsing failure, rejection, or unsupported status.
- Do not compute whole-workbook suggestion precision or accuracy: no independent labels exist for all other formulas or suggestions. Do not count cache-value agreement alone as formula correctness.
- The corrected snapshot is a source-authored version control, not an independent validation workbook. Formula and cached-value parity across ODS-to-XLSX conversion must be checked at both target cells before model output is scored.
- Run the same two frozen inputs at 1 and 8 workers, compare per-task prediction hashes, and record wall time, summed child CPU time, sampled aggregate peak RSS, throughput, and speedup. This two-task run is a functional/resource check only; it cannot establish scaling to large batches or an 8-worker CPU utilization target.

## Decision rules

- Keep natural-source and template-family final-validation counts unchanged because the author disclosure predates this audit.
- A correct result requires the proposed formula to be textually identical to the author-corrected formula at the target cell. A missing, rejected, unknown, unsupported, failed, or timed-out target is not correct and remains in the two-cell coverage denominator.
- Do not tune from these results. Use any outcome only to refine the failure taxonomy and prioritize the next independently sourced experiment.
