# V518 experiment protocol v1

Preserve the V517 input domain, full localization and legacy authority boundary.
The numeric environment and enclosure rule are specified in V518_NUMERIC_PROTOCOL.

G4: 24 fixed engineering workbooks (3 families x 2 constraint structures x 4
seeds), 13 binary candidate cells each, both backends. Same default budgets for
V517/V518. The separate V516 oracle enumerates all 8192 states. At least 12
different workbooks must improve on both backends, across all three families.

Development scaling: 48 workbooks, 16/24/32 cells. Each size has product/ratio/
weighted unique and mixed-subtotal cases, plus the remaining ten product cohorts.
Run all six modes on both backends. These are known development seeds.

Confirmation: freeze all sources and this protocol first, then generate a fresh
seed. Three families x twelve cohorts x two sizes (24/32) x two repetitions =
144 workbooks; six modes x two backends = 1728 diagnoses. Use all predeclared
slots. Derive case identities from a public seed commitment and slot, checking
the full expected manifest and shard inventory before labels are opened.

Modes: V517 baseline, V518 numeric, V518 numeric_off, V518 max_nodes=1, V518
review_only, V518 reject_all. All other budgets stay at max_nodes=10000,
max_evaluations=4096, max_preparations=4096. Do not increase a budget based on a
case label. Both policy ablations still produce the full search evidence.

Cohorts: unique, mixed_subtotals, ambiguous, cancel_total, no_solution, clean,
legal, numeric_collision, tolerance_boundary, invalid_approval,
candidate_dependency, weak_bounds. Unknown evaluator behavior uses unit-test
fault injection rather than a claimed natural confirmation case. Invalid approval
retains the existing legacy fallback; no legacy action is represented as numeric
authorization. All corrupted cells, including abstention cases, remain in the
coverage denominator. Correctness of each accepted transaction is separately
checked, and any action on an abstain/no-action cohort is unsafe.

Generate inputs and hidden labels separately. Prediction code receives public
workbooks, documents and approval context only. Lock all shards and sources before
scoring; verification checks actual hashes, mode/configuration, full localization,
candidate domain, unique certificates and atomicity before label authorization.
After freeze do not replace failed instances, alter totals or tune parameters.
New seeds from known families are not independent third-party blind evidence.

Batch prediction and replay may use multiple worker processes; their elapsed
times are throughput-context measurements. A separate serial repeated benchmark
must report median/tail time, ranking versus diagnosis versus replay time,
certificate bytes and process memory high-water mark. Do not call process RSS an
isolated allocation measurement for the solver. Count preparation and leaf calls
separately; initial checks and ranking/candidate preparation are not leaf calls.

Gates: G1 numeric derivation, G2/G3 unit and exhaustive differential checks, G4
paired milestone, then complete development scaling. Confirmation requires zero
unsafe accepted groups, zero localization/candidate changes, valid complete
uniqueness proofs for every unique claim, and intact source/population locks.
Report actual coverage and all refusals; zero observed unsafe groups is not a
population safety guarantee. Preserve every failed result under a new run path.
