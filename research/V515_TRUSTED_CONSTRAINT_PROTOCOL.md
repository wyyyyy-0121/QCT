# V5.1.5 trusted aggregate acceptance experiment

Objective: distinguish corrupted formulas from legal exceptions using additional
approved business evidence, then demonstrate increased safe repair coverage.
Retain complete V513 localization. Do not infer trust from workbook content.

First mechanism: an explicitly approved external aggregate document names at
least two existing formula cells and a finite expected sum. Approval is an
out-of-band pinned document SHA-256, not a self-reported trusted boolean. Bind
the document to the workbook model content and an explicit validity interval.
Malformed, unapproved, stale, mismatched, conflicting or uncomputable evidence
must not authorize new actions. A digest proves identity, not business truth.

The experimental scope is the existing V514 edge candidate portfolio. No formula
answer may appear in constraint documents. Evaluate the original workbook and
each proposed change without writing it. Original aggregate must fail, exactly
one distinct candidate must satisfy all relevant approved constraints, and the
whole proposed change set must jointly satisfy constraints without breaking
previously satisfied constraints. Missing/ambiguous evidence => review.

Paired tests must use identical workbook formulas and input values but different
external aggregate evidence: one reflects the intended healthy calculation,
one reflects a legitimate exception. Structural-only acceptance cannot separate
the pair; trusted constraint acceptance must. Also include absent approvals,
wrong identity, expired documents, contradictory constraints, ambiguous numeric
solutions, unsupported calculations, and multiple interacting errors. These
remain in the denominator and must be reported separately.

Evidence limitation: synthetic approved documents simulate an independently
maintained business source. They do not establish authenticity or correctness of
real documents. No real-world trust or safety claim without user-supplied verified
business constraints. Never present oracle expected formulas as trusted evidence.

Development before freeze: paired examples and adversarial cases, API/invariant
and policy tests; measure population and constraint-qualified coverage separately.
Then freeze source, generator, scoring and this protocol before generating a new
seeded confirmation population. Commit predictions before reading labels. Report
all categories, unsafe groups, group precision, exact repair coverage, candidate
coverage and constraint availability. Same-generator confirmation is not natural
workbook or unseen-family generalization.

Predeclared gates for the synthetic experiment: zero rank/score/coverage changes;
all legal exception pairs preserved; zero unsafe new accepted groups across all
cases; new exact accepted coverage strictly greater than candidate-only baseline;
>=95% accepted group precision. Failure remains visible, no post-reveal tuning.
Passing these gates establishes only conditional synthetic mechanism efficacy.
Constraint evaluation requires explicitly present dependencies, including range
members; missing inputs cannot silently become zeros. Ranges above 10,000 cells
are rejected in this prototype rather than skipping the completeness check.

Fixed populations: 120 development workbooks (six families, two clusters, ten
categories), then 300 confirmation workbooks (five new clusters per family).
Paired error and legal-exception cases have byte-identical workbooks but different
external totals. All missing/stale/unapproved/conflicting/numerically ambiguous or
multi-error cases stay in the full repair denominator. The separately reported
"qualified" subset is predeclared error/clean/legal_exception categories, not a
post-hoc selection of successful outputs and not the overall approval-availability
rate. Report validation status counts separately. Fixed validation date 2026-09-06
is part of the simulated scenario, not the machine's current wall clock.

As with any external-evidence system, an incorrect total approved out-of-band can
still authorize a wrong action. This experiment verifies use of declared valid
evidence; it does not build an oracle that authenticates business truth.
