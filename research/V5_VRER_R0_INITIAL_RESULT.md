# FormulaGuard VRER R0 initial acquisition result

Date: 2026-09-01  
Protocol: `formulaguard_vrer_r0_audit_v1`  
Preregistration lock: `d9f32e0`  
Source candidate manifest: `research/V5_VRER_SOURCE_CANDIDATES.json`

## Scope

This is the first independently acquired source batch after the VRER protocol was
committed. It validates acquisition, formula differencing, correction-statement
screening, license receipts, and independent-process reproduction. It is not the
complete R0 acquisition, a training corpus, a model result, or permission to implement
the VRER ranker.

The only accepted upstream in this batch is the canonical MIT-licensed
`ewcole/tax_worksheets` repository pinned at
`b9197d95e0040936720893587b4bc64551905eff`. All third-party workbooks remain in ignored
local result directories. Git retains only source URLs, immutable commits, parent
commits, paths, public correction statements, and the license hash.

## Result

| R0 quantity | Observed | Required | Status |
| --- | ---: | ---: | --- |
| verified correction episodes | 4 | 60 | not yet met |
| corrected same-cell formulas | 8 | 80 | not yet met |
| independent revision groups | 1 | 40 | not yet met |
| unrelated repositories/projects | 1 | 10 | not yet met |
| ordinary-edit controls | 0 | 30 | not yet met |
| control repositories | 0 | 5 | not yet met |
| maximum repository group share | 100% | <=25% | not yet met |
| corrected-cell parser coverage | 100% | >=90% | passed |
| independent-process reproduction | identical | required | passed |
| protected/revealed label inputs | 0 | 0 | passed |

The four accepted episodes contain one, one, one, and five direct same-cell formula
changes. They have identical worksheet inventories across the before/after pair and no
formula additions or removals. The eight corrected formulas are all parseable by the
frozen FormulaGuard parser.

An additional keyword lead, `BjornV1/FoodSecurityFlowChart` commit
`c353d0eaf4502d0fd9169c249e08d2bb25ac1d05`, was inspected and excluded before corpus
entry because it changes JavaScript/JSX only and contains no workbook artifact. Keyword
search hits are not counted as candidates or evidence.

## Reproduction

Two separate invocations of `scripts/prepare_vrer_r0.py` produced byte-identical
receipts:

`d937d3d1692fc095af5cbb5087a9ea1ad327b707fa850b44e576b41ca750bf72`

The independent comparison receipt is:

`results/vrer_r0_initial/reproduction_receipt.json`  
SHA-256: `b118288a5fa1fcfef2294244bdf366119783805a1470456a45e041611d4dd666`

The verifier selected the frozen 20% stable-hash sample (one of four episodes) and
matched identity, repository/revision group, formulas and diffs, commit evidence,
workbook hashes, license hash, and boundary receipts with zero mismatches. The complete
primary and recheck receipts were also byte-identical.

Commands:

```bash
.venv/bin/python scripts/prepare_vrer_r0.py \
  --sources research/V5_VRER_SOURCE_CANDIDATES.json \
  --source-root data/external/model_discovery/raw/vrer \
  --output results/vrer_r0_initial_a
.venv/bin/python scripts/prepare_vrer_r0.py \
  --sources research/V5_VRER_SOURCE_CANDIDATES.json \
  --source-root data/external/model_discovery/raw/vrer \
  --output results/vrer_r0_initial_b
.venv/bin/python scripts/verify_vrer_r0_reproduction.py \
  --primary results/vrer_r0_initial_a/receipt.json \
  --recheck results/vrer_r0_initial_b/receipt.json \
  --output results/vrer_r0_initial/reproduction_receipt.json
```

## Decision

R0 remains open but has not passed. VRER feature fitting, repair-recoverability scoring,
ranker implementation, Enron evaluation, and protected `240+120` access remain
forbidden. Acquisition must continue with unrelated licensed projects and matched
ordinary-edit controls under the unchanged acceptance rules. The four current episodes
remain one revision group; they cannot be split to manufacture independence.

If the frozen scale and diversity thresholds cannot be reached after systematic public
source acquisition, VRER stops before model implementation. That outcome would confirm
that the current no-oracle main-ranker route lacks defensible natural correction
supervision and would trigger the preregistered new-input-contract branch instead of a
smaller or post-hoc training set.

## Verification

VRER unit tests: `9 passed`.  
Full repository suite with 24 workers:
`461 passed, 1 skipped, 37 subtests passed in 32.56s`.

No protected directory was listed, hashed, opened, searched, or used. No Enron,
Historical 100, public N2, old revealed-trial, SpreadsheetBench 2, or other revealed
FormulaGuard label entered R0.
