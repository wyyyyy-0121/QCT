# G3 Round Plan

G2 finished all 72 G1 workbooks on both backends: 144 unique diagnoses with
successful replay, including all 24 predeclared minimum workbooks. The initial
83 tests passed. This plan is recorded before G3 implementation/execution.

1. Expand boundary tests: missing/cyclic/nonfinite computation, runtime fallback,
   leaf errors, exact node budgets, and changed approval/date/trusted configuration.
2. Revalidate the entire already-revealed V518 population: 48 development plus
   144 former confirmation workbooks, both backends. Verify release/input/label
   and saved prediction hashes, recompute complete ranks, compare old portfolios,
   replay all former unique claims and every new unique claim.
3. Keep every original error cell in the denominator; preserve original accepted
   groups, require zero unsafe groups and unchanged rankings/candidates. Record
   every status, engine, budget and full transaction. Old inputs are regression
   evidence, not new confirmation or independent workbooks across backends.
4. Preserve the G1 exhaustive differential and G2 81/144-state multi-option
   checks. Run the new model/components and V518 focused suite together.
5. Only after these gates pass, add the local Python `api.localize` V519 method
   aliases and test all aliases, backends and policies. No HTTP service, external
   model call, default-ranker switch, or automatic workbook write is introduced.
6. Record the G3 result and prepare a separate G4 plan before the milestone.

Limits remain nodes=10000, leaves=4096, preparations=4096 and component states=256.
No cohort reduction, result-based seed selection or baseline source edits.
