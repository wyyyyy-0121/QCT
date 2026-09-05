# FormulaGuard VRER R0 final acquisition result

Date: 2026-09-01  
Protocol: `formulaguard_vrer_r0_audit_v1`  
Preregistration lock: `d9f32e0`  
Second-source freeze: `6bf5017`

## Scope

This result closes the VRER acquisition gate. It records the second independently
licensed source audit and the bounded source-search evidence used to decide whether
continuing acquisition is a defensible model-development activity. It is not a VRER
model result: R0 did not authorize feature fitting, repair-recoverability scoring, or
training.

No protected or revealed FormulaGuard input was listed, opened, hashed, searched, or
used. All cloned public repositories and generated receipts remain under ignored
local acquisition/result directories.

## Second licensed source

The source and candidate identity were committed before workbook inspection. The
candidate was `eoframework/eof-solutions` commit
`858a03921c12b1f7e23992a35f7bab888641c8a5`, with parent
`ea28b09957fb0bdc0684b482408ff404aaecc676` and the public statement:

> Fix Cisco presales issues: circular references, architecture diagrams, and PPTX note

The before and after workbooks have identical sheet inventories, 62 formulas on each
side, no formula additions or removals, and 28 direct same-address formula changes.
All 28 formulas are parseable, but the frozen protocol allows a workbook-level
statement only when there are at most 12 direct changes. The episode is therefore
rejected as `workbook_statement_has_more_than_12_direct_changes`.

The 28 cells cannot be split into smaller episodes, attributed selectively to the
circular-reference phrase, or rescued by changing the statement scope after the
workbook was opened.

## Reproduction

Two separate audit processes produced byte-identical raw receipts:

`results/vrer_r0_batch_b_a/receipt.json`  
`results/vrer_r0_batch_b_b/receipt.json`  
SHA-256: `4b0d5dd96926fc0504372b929dbc3513cb2ac2de03b379fae6a17a3233428c60`

The independent comparison receipt is:

`results/vrer_r0_batch_b/reproduction_receipt.json`  
SHA-256: `d9b788fe641b7269a66c54dc4d23c377464138e7ad6b667fa33cf0448256cca9`

The comparison matched source identity, decision, formulas, hashes, structural group,
and protected/revealed-input boundaries with zero mismatches.

## Bounded acquisition audit

The local acquisition audit cloned 30 public repositories selected from workbook
history and correction-keyword searches. Their histories contain 1,453 commits that
touch an XLS/XLSX/XLSM path and 304 workbook-touching commits whose messages match the
frozen broad correction terms. These are search counts, not accepted corrections.

Manual history and tree audits found genuine formula-correction statements in several
repositories, including `capraCoder/fisherman`, `drjlevi6/Data-Scientist`,
`swallih/Excel_Project`, `markjm5/portfoliomanagement`, both Drachenwald lineages,
`Mistaman/DFS-Stats`, `julisobi/multimedia_retrieval`,
`POLISatDuke/HouseElections`, `JBorden123/ASF`, and
`HaadiaBaig/BearRiverWaterBank`. Their repository trees contain no explicit license
covering the workbook history, so public availability alone does not permit their use
as redistributed VRER training evidence.

The other material with an explicit repository license did not close the diversity
gap:

- `ewcole/tax_worksheets` is the one accepted MIT-licensed lineage;
- `eoframework/eof-solutions` is licensed for research, but the preregistered candidate
  above is an ambiguous 28-cell workbook-level rewrite and the remaining workbook
  leads are from the same repository/template ecosystem;
- `Roche/flexsurvPlus` is Apache-2.0, but its correction commit adds the workbook for
  the first time and therefore has no before-workbook pair;
- repositories whose only license is nested, proprietary, or attached to unrelated
  third-party material do not establish workbook redistribution permission;
- licensed repositories with no workbook history cannot contribute correction or
  ordinary-edit episodes.

This audit does not claim that no qualifying workbook revision exists anywhere on the
public internet. It establishes that broad acquisition has become an open-ended
information-retrieval project and that the frozen requirements are not attainable from
the audited evidence without either using unlicensed artifacts, changing the evidence
scope, or manufacturing independence.

## Final R0 gate

| R0 quantity | Accepted | Required | Status |
| --- | ---: | ---: | --- |
| verified correction episodes | 4 | 60 | failed |
| corrected same-cell formulas | 8 | 80 | failed |
| independent revision groups | 1 | 40 | failed |
| unrelated repositories/projects | 1 | 10 | failed |
| ordinary-edit controls | 0 | 30 | failed |
| control repositories | 0 | 5 | failed |
| maximum repository group share | 100% | <=25% | failed |
| corrected-cell parser coverage | 100% | >=90% | passed |
| independent-process reproduction | identical | required | passed |
| protected/revealed label inputs | 0 | 0 | passed |

## Decision

R0 fails and VRER stops before model implementation under section 5 of the frozen
protocol. The thresholds, license rule, statement scope, revision grouping, and source
diversity requirements remain unchanged. The four accepted episodes remain useful
provenance evidence but are not a training corpus and do not authorize a smaller VRER.

`V4-R1` remains the only formal main ranker. The next admissible research route must
change the inference contract, as already specified in section 13 of the VRER
preregistration. It must be separately named and preregistered before implementation;
it cannot reuse the failed acquisition result as supervision or be presented as a
patched VRER/V5.

