# V519 G6 Final Acceptance Record

Status: G6 audit and validation complete; Git delivery is being prepared.
The stage plan was recorded before execution in `V519_G6_PLAN.md`.

## Requirement Evidence

| Requirement | Authoritative evidence | Verification |
| --- | --- | --- |
| G2 fixed population and minimum capability | `V519_G2_V1/result.json`, 144 raw diagnoses; G1 oracle and input hashes | Preliminary raw audit passed: 72 workbooks, 24 minimum cases, all unique groups correct |
| G2 budget accounting and refusal after one solution | `tests/test_v5_1_9_development.py`, `V519_G2_PROTOCOL.md` | Final suite pending; focused checks passed |
| Full original domain, equal-value multiplicity, cross-sheet and fixed-member dependencies | `tests/test_v519_components.py`, `tests/test_v5_1_9_development.py`, G1/G2 receipts | All-assignment mapping and small-space differential tests, including 81/144 states |
| Bounds respect original float/member semantics | `V519_G1_PROTOCOL.md`, `tests/test_v518_numeric_bounds.py`, component tests | Exhaustive prefix enclosure checks and double-rounding counterexample |
| Certificate reconstructs inputs/tables/partition and atomic group | `formulaguard/v5_1_9_development.py:verify_unique_solution`, model/boundary tests | Context, partition, counts, table, ranking and group tampering must fail |
| G3 complete historical regression | `V519_G3_V1/result.json`, all 384 saved diagnoses | Preliminary raw audit preserved 84 previous unique groups; all 192 workbooks retained |
| G3 API aliases, backend and policy compatibility | `tests/test_v519_api.py`, `formulaguard/api.py` | 18 focused cases passed; final suite pending |
| G4 fixed real-dependency milestone | `V519_G4_V1/` raw inputs, diagnoses, V516 references and hashes | Preliminary raw audit passed all 24 comparisons; 12 workbooks, 196608 oracle states |
| G5 full development population | `V519_DEVELOPMENT_VALIDATION_V1/` | 51 workbooks, 612 diagnoses; preliminary raw audit matches all denominators and groups |
| G5 source/config/environment freeze then fresh confirmation seed | `results/v519_freeze_v1/source_lock.json`, confirmation release receipt | 454 frozen files verified; source freeze precedes input generation |
| G5 exact predictions before reveal, independent unique-proof replay | Confirmation prediction lock and `V519_VALIDATION_V1/reveal_authorization.json` | 1,728 shards verified; 480 unique proofs replayed |
| G5 zero unsafe groups and strict coverage gain on each backend | `V519_VALIDATION_V1/result.json`, final raw audit strata | Gate passed; 192 accepted groups checked, zero unsafe |
| Costs and ablations | `V519_SERIAL_BENCH_V1/result.json`, G5 six-mode records | 60 serial measurements, five repetitions per condition, two separately profiled runs |
| Full suite, Ruff and source preservation | `V519_CHECKS/`, frozen/current source comparison, staged allowlist | 1,196 passed, 1 skipped, 91 subtests; Ruff passed; audit passed |
| Commit, push and remote equality | Git commit and `git ls-remote origin refs/heads/codex/linux-migration` | Pending GitHub authentication/push |

## Reproduction Boundaries

The G2/G3/G4 source snapshots contain 440/443/448 files respectively. API dispatch
was intentionally added after G3, so those earlier evidence locks are checked
against their own preserved snapshots. No old model or G1 component source is
edited. The final audit script is outside the frozen solver/test/protocol source
inventory and records its own digest.

The first confirmation prediction was interrupted by a session environment loss
with 1328 shards and no prediction lock. It is retained separately under
`results/v519_confirmation_predictions_interrupted_v1/`. A complete new run uses
the identical frozen source, runtime, input population and seed, before reveal.
This is execution recovery, not selection of a new confirmation population.

Known-generator synthetic confirmation and five serial timing repetitions do not
establish arbitrary-workbook safety, third-party blind validation, cross-platform
numerical equivalence or production P95 latency. The local Python API provides
ranked diagnostics and repair decisions; it neither calls an external service nor
writes changes back to XLSX files.
