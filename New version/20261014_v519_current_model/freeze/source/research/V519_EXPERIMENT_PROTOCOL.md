# V519 G5 Experiment Protocol

This protocol is recorded before serial measurement and development batches.
The detailed stage plan is V519_G5_PLAN.md. No confirmation seed exists yet.

## Fixed Population And Semantics

Development: 36 cases at 12 candidates (three families x twelve cohorts), plus
15 product scale cases at 16/24/32 candidates with components of size 2/3/4/8/9.
Total 51 workbooks, six modes and two backends = 612 diagnoses. Fixed development
seed is v519-development-01; component9 is intentionally over the 256-state cap.

Confirmation: three families x twelve cohorts x 24/32 candidates x two instances
= 144 workbooks; six modes and both backends = 1728 diagnoses. A fresh random
seed is generated after source/environment/configuration freeze, with commitment
in the release receipt. Every expected case and shard is reconstructed by slot.

Cohorts are pair, chain, fan_in, shared_bridge, candidate_only, coupled_ambiguous,
coupled_no_solution, oversized_component, independent_unique, weak_bounds,
invalid_approval and original_satisfies. Ambiguous cases include independently
declared legal exceptions, so exactly the first three endpoint cells are errors;
the subtotal fixes the coupled pair while multiple equivalent independent fixes
remain. Coupled no-solution adds 0.12345 to the independently computed total.
Candidate-only changes the downstream original reference to a fixed E input;
only the translated repair candidate uses C, which depends on the upstream H.
Its original formula is one bounded reference edit from the candidate, rather
than a manufactured proposal supplied to the solver.

Other cohorts retain all generated true error cells, including budget refusals,
invalid approvals, and errors concealed by already-satisfied totals. No label
changes or population selection based on solver output are allowed after freeze.
Raw seeds include the cohort name for true-dependency variants to avoid reusing
identical workbooks across those contexts. Template/instance correlation remains.

## Modes And Budgets

V518 baseline, V519 main, components_off, low_budget, review_only, reject_all.
Default limits: 10000 nodes, 4096 leaf evaluations, 4096 preparation evaluations,
256 component states. Low-budget changes the node cap to one. V519 counts the
initial satisfaction evaluation in preparation; V518 retains its historical
audit convention. That additional call and the distinct component-node unit are
reported; equal numerical caps do not assert identical CPU work.

No candidate-space reduction, tolerance adjustment, frozen-ranker change, new
external approval privilege, network API, or workbook writeback is introduced.
Numeric bounds retain the reviewed CPython 3.11.16/math binary, binary64 rounding
assumptions, 4096-member cap and 2**500 absolute-magnitude cap from V518/G1.

## Freeze, Predict, Verify, Reveal

Freeze all root formulaguard/scripts/tests Python sources, pyproject and declared
V518/V519 plans/protocols, plus installed dependency versions and numeric runtime
identity. Preserve copies of every frozen file. Prediction requires exact source,
environment, input and approval hashes and reads only public inputs/approvals.
It locks all expected shards before scoring can begin.

Scoring rechecks inventory and hashes, recomputes full rankings/candidate domains,
checks modes/budgets/policies, and independently replays all unique claims. Only
after every workbook passes does it create reveal_authorization and read labels.
Then it checks seed commitment, exact case/slot/stratum population, atomic formula
correctness and full error denominators. Zero unsafe accepted groups and strict
coverage improvement over V518 on each backend are required for a passing gate.
All modes and failures remain in the output. Revealed development data is never
reported as new confirmation; confirmation is not third-party blind evidence.

## Costs

Run the 60-measurement serial benchmark before concurrent batches or full tests:
16/24/32 candidates x two backends x five repetitions x baseline/main. Mode order
alternates; ranking is recomputed per repetition and shared fairly between modes.
Record input construction, ranking, diagnosis, replay, serialization, in-memory
total, certificate bytes, actual search counts and process RSS high-water.
Two separate 32-cell profile observations split candidate and bound/table work
from search/dispatch/initial-check residual. Profiling overhead is explicit and
not mixed into unprofiled medians. No XLSX I/O or production P95 claim is made.

G6 will audit chronology, frozen sources/data, all original accepted transactions,
full denominators, stage gates and final full pytest/Ruff before commit/push.
