# FormulaGuard SFRI shared-formula integrity preregistration

Date frozen: 2026-09-03

Status: public label-free feasibility protocol; no model or formal version is
authorized by this document

Protocol: `formulaguard_shared_formula_region_integrity_v1`

## 1. Research question

An OOXML shared-formula master can declare a rectangular `ref` whose members
must translate the master's formula.  This experiment asks whether a single
ordinary formula occupying the only missing member of an otherwise complete
declared region provides a target-independent structural certificate that can
safely rescue a V4 Top-5 miss.

This is not another peer-majority score.  The region and candidate formula must
come from the package's shared-formula master while the prospective target
formula is masked.  The observed target is read only after the certificate has
been constructed, and only to classify agreement or disagreement.

## 2. Prior label-free observation

Before this protocol was written, a read-only package probe inspected the same
Enron and public observed workbooks used by the header-partition V2 scan.  It did
not read `source_cells`, correct formulas, case kinds, error types, or protected
inputs.  Across 115 path instances representing 96 byte-unique workbooks, it
found 50 declared shared-formula groups: 42 complete and 8 with exactly one
missing shared member occupied by an ordinary formula.  The eight cases belong
to two public Integer-corpus structure clusters.  No label-based hit, V4 rank,
or repair-accuracy result was inspected.

These counts justify one prospective feasibility run.  They may not be used to
relax the rules below after scoring.

## 3. Inputs and isolation

The label-free prediction run reads only these fields from
`results/core_reset_b_phase0/scoring_groups.csv`:

- `cohort`;
- `workbook`;
- `workbook_sha256`;
- `structure_cluster_id`.

The fixed cohorts are `enron`, `public:info1`, `public:integer_corpus`, and
`public:modified_euses`.  Byte-identical workbooks are scanned once.  Historical
100, both `240+120` packages, answer workbooks, source labels, paired originals,
and correct formulas are not prediction inputs.

Every prediction shard and a completion receipt must be atomically written and
hash-locked before any revealed label is opened.  The prediction metadata must
record an empty `label_inputs` list and an empty `protected_data_inputs` list.

## 4. Frozen certificate

A region is eligible only when every condition below holds:

1. one valid shared-formula master has a forward rectangular `ref` containing
   the master;
2. the declared region contains at least five cells;
3. exactly one declared cell is absent from that shared group, every observed
   group member lies inside the declared region, and every other declared cell
   is a member of the same group;
4. the missing member is a visible, unmerged, ordinary formula cell and does not
   belong to an array, data-table, or another shared-formula region;
5. translating the masked master formula to the missing address succeeds,
   parses under FormulaGuard, and does not require the observed target formula;
6. the translated candidate differs from the observed target formula after
   normalization;
7. exactly one eligible disagreement exists in the workbook.

Malformed indexes, missing or multiple masters, missing master refs, overlapping
special-formula regions, multiple holes, non-formula holes, invisible targets,
and multiple eligible disagreements force abstention.  A complete shared group
or a translated candidate equal to the observed formula is an audited agreement,
not an action.

The certificate identifies a package-schema disagreement and a candidate repair.
It does not prove author intent.  Automatic workbook edits are outside scope.

## 5. Frozen ranking rule

Two outputs are scored:

- `sfri_certificate`: the one certified target, or abstention;
- `v4_sfri_fifth`: preserve the frozen V4 ranking exactly unless one SFRI
  disagreement target is outside V4 Top-5; then keep V4 ranks 1-4, place the
  SFRI target at rank 5, and append the displaced V4 cells in their original
  order with no duplicates.

SFRI does not read V4 scores to create its certificate.  V4 is used only by the
fixed post-certificate ranking adapter.  No threshold, weight, cohort gate, or
address-based evidence is permitted.

## 6. Prospective scoring and gates

After the prediction lock, a separate scorer may read the already revealed
public/Enron labels and the existing frozen V4 shards.  It must report event and
structure-group macro Top-1/Top-5/MRR, paired rescues and losses, certificate
precision, exact candidate-formula agreement when a correct formula is available,
control action rate, and results by cohort.

Implementation is valid only if two independent prediction runs are byte
identical and all source/input/shard hashes verify.  The mechanism advances to a
bounded candidate version only if every gate passes:

1. at least six certified disagreement workbooks from at least two structure
   clusters;
2. certified target precision at least 90% and no false certificate on a
   control workbook;
3. exact candidate-formula agreement at least 90% on cases with an available
   correct formula;
4. `v4_sfri_fifth` has at least two net Top-5 rescues and at least one newly hit
   structure cluster;
5. there are zero Top-5 losses overall and zero losses in every reported cohort;
6. Enron Top-5 and MRR do not decrease, and public control action rate is 0%;
7. prediction and scoring integrity audits pass without protected input.

Failure of any gate stops SFRI v1.  The eight observed workbooks may not be used
to add exceptions, change the minimum region size, allow multiple holes, move the
candidate above rank 5, or introduce a cohort-specific rule.

## 7. Claim boundary

Passing the gates would authorize one narrowly scoped V4-plus-SFRI candidate
file for shared-formula package inconsistencies.  It would establish improvement
only on the named revealed development inputs, not a formal `V5-R1`, natural-error
generalization, or protected-set superiority.  Independent shared-formula cases
would still be required before a broad successor claim or protected evaluation.
