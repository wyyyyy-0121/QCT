# V5 successor revealed-trial replication protocol

Date fixed: 2026-08-30
Status: fixed before the old 240+120 package is available in Linux

## Data identities

The historical folder named
`FormulaGuard_V5_PSL_240+120_六制题人最终交付` is no longer confidential at the
owner's direction. It is permanently classified as `revealed_trial`: it may be
used for schema checks, interface tests, failure analysis and one fixed
development replication. It must not be called blind, independent, external
confirmation, six-person validation or evidence of final promotion.

The new dataset being prepared by the independent custodian has the separate
identity `held_out_successor_confirmation`. Its templates, workbooks, labels,
case rationales and archive contents remain unavailable to the developer and
the repository. Before candidate lock, only future archive commitment hashes
may be released. It must not reuse any template from the 90 public-development
cases or the revealed-trial package.

## Receipt and storage

The old folder is copied unchanged to
`data/external/v5_psl/revealed_trial/FormulaGuard_V5_PSL_240+120_六制题人最终交付/`.
That directory is Git-ignored. Before extraction or normalization, the project
records a recursive file inventory, sizes and SHA-256 hashes. Existing receipts
are evidence about package construction only; personnel counts and independence
claims are not accepted without separately auditable proof.

The first pass checks archive safety, workbook counts, schema, duplicate
templates, formula-set preservation, license declarations and overlap with all
revealed development data. Failed design checks downgrade the package further
to interface smoke data; cases are not silently deleted to satisfy quotas.

The immutable intake command is:

```bash
python scripts/audit_v5_successor_revealed_trial.py \
  --package-root data/external/v5_psl/revealed_trial/FormulaGuard_V5_PSL_240+120_六制题人最终交付 \
  --output results/v5_successor_revealed_trial_intake.json
```

It recognizes the historical v1 PUBLIC/SECRET format from Git history, verifies
both archive hashes and the PUBLIC-to-SECRET precommit, audits member paths and
schemas without extraction, and records a recursive directory hash inventory.
It does not invoke FormulaGuard. Declared creator/reviewer counts are checked as
package structure, but personnel identity and independence remain unverified.

## Single fixed replication

The only successor signal evaluated is the already observed rule:

> Use frozen V4-R1's complete ranking. Act on exactly one cell only when exactly
> one cell in V4 Top-5 has `diagnostic_status=strong_counterfactual`; otherwise
> abstain. Candidate or label information cannot change the complete ranking.

No threshold, candidate budget, Top-K value, evidence label or tie rule is
changed. V4-R1, V4.2-Review-B and the rule above are computed without reading
case labels. Even if the package already exposes labels, prediction workers
receive only workbook paths and anonymous instance IDs. Scoring starts only
after all complete rankings and source hashes are fixed.

The replication reports source-hit rate, acted-error precision, clean-control
action rate, inspected-cell efficiency, template-cluster intervals and all
design deviations. For a complete 240+120 design, mechanism support requires:

- source-hit rate at least 30% of error cases;
- acted-error case precision at least 75%;
- clean-control action rate at most 15%;
- efficiency not below frozen V4 Top-5;
- at least 80% of template clusters have nonzero source hits without exceeding
  25% control actions in that cluster.

These thresholds determine only whether the fixed mechanism is stable enough
to justify a separately named preregistration. They cannot convert the old
package into confirmation evidence and cannot override the failed 90-case
diagnostic. If package design differs from 240+120 or lacks reliable template
IDs, the corresponding gates are reported as not evaluable rather than waived.

## Consequence

If the fixed rule fails, it is rejected and the paper system remains V4-R1 with
V4.2 as an auxiliary review module. If it passes, a new architecture document
must still be written and committed before any final candidate implementation
or access to the new custodian set. The unseen custodian confirmation remains
the only evidence capable of promoting a future main model.
