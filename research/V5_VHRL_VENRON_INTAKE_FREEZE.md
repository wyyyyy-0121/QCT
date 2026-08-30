# FormulaGuard VHRL VEnron intake freeze

Date: 2026-08-31
Protocol: `formulaguard_vhrl_venron_intake_freeze_v1`
Status: frozen before VEnron download or workbook inspection
Research name: `VHRL` (Version-History Responsibility Localizer; not a formal version name)

## 1. Decision boundary

`V4-R1` remains the only frozen main ranker. FCRL stopped at U1 corpus coverage
before training because only 125 of 219 frozen structure groups retained a formula
target. VHRL is a separate feasibility study, not a retry of FCRL and not `V5-R1`.

The existing 90-case public-pressure version pairs cannot validate a history model:
every error case contains exactly one direct formula-text edit. Address order,
V4-restricted formula diff, and dependency-root rules therefore all obtain a trivial
100% result. Those pairs remain regression tests but are forbidden as evidence for
the new mechanism.

VHRL asks a narrower question on real version histories:

> Within a change containing multiple direct formula edits, can a fixed five-cell
> review budget rank which edits are responsible for a mechanically observable
> regression proxy, while separating user edits from structural or generated
> rewrites and accounting for rollback interactions?

This intake freeze authorizes only acquisition and a corpus-resource audit. It does
not authorize feature engineering, model implementation, threshold selection, or
protected evaluation.

## 2. Prior-art and claim boundary

The following are prior work and cannot be claimed as FormulaGuard inventions:

- VEnron's collection and organization of real spreadsheet version histories;
- prediction of spreadsheet and formula evolution from version history;
- automatically inferred spreadsheet invariants for regression-fault detection;
- formula differencing, dependency graphs, rollback, program slicing, causal
  responsibility, interaction analysis, and learning-to-rank in their general forms.

The only candidate increment is the combined task definition and evidence contract:
cell-level responsibility ranking inside real multi-formula-edit transitions, a
change-dependency frontier, explicit exclusion or labeling of system-generated
rewrites, rollback-interaction evidence, and a fixed five-cell review budget without
expected outputs at prediction time. Novelty remains unproven until the literature
review and experiments both support it.

VEnron does not provide author-intent or silent-error ground truth. Explicit Excel
errors, short-horizon reversion, later correction, invariant violation, and rollback
effects are regression **proxies** only. They must never be reported as human-
confirmed spreadsheet errors or as evidence that an edited formula was unintended.

## 3. Frozen public artifact

- Article API: `https://api.figshare.com/v2/articles/4797943`
- Article ID: `4797943`
- Title: `VEnron1.0`
- DOI: `10.6084/m9.figshare.4797943.v1`
- License: `CC0`
- File ID: `7889947`
- File name: `VEnron1.0.7z`
- Bytes: `64,878,068`
- MD5: `15a3430526b01a3ace679225a450cc1e`
- Download URL: `https://ndownloader.figshare.com/files/7889947`

The acquisition tool must fetch fresh structured API metadata and reject any change
to these fields. It writes the archive only under the ignored path
`data/external/model_discovery/raw/venron/VEnron1.0.7z`, computes SHA-256, and writes
an immutable receipt under `results/venron_intake_v1/`. Raw workbooks, archive member
names, and detailed manifests remain local and are not committed.

## 4. V0 resource gate

After acquisition, a separate audit may enumerate and extract the public archive.
Before any model is implemented, all conditions must hold:

1. at least 300 version groups and 6,000 spreadsheet versions are present;
2. at least 150 groups and 1,000 adjacent transitions contain a direct formula-text
   edit after successful format conversion;
3. at least 100 adjacent transitions across at least 30 groups contain two or more
   direct formula-text edits;
4. at least 80% of spreadsheet versions can be converted and parsed without using
   cached-value differences as formula edits;
5. direct user formula edits, structural moves, bulk copies, format-only changes,
   recalculation-only changes, and unsupported transitions have separate counts;
6. no protected, Enron Error Corpus label, Modified EUSES label, expected-output,
   `V4` ranking, or FormulaGuard trial input is read.

Any failed condition stops VHRL before model implementation. The thresholds may not
be lowered after inspecting the corpus, and single-edit transitions may not be
duplicated or synthetically merged to satisfy the multi-edit gate.

## 5. V1 label-feasibility gate

Only after V0 passes may deterministic proxy labels be constructed. Before model
training there must be at least 60 nontrivial labeled regression-proxy transitions
across at least 30 version groups and at least 60 time- and group-matched controls.
Every positive must contain at least two direct formula edits and a mechanically
reproducible proxy whose affected cells can be recomputed. At least one candidate
edit must change the proxy under isolated rollback; multi-edit interactions must be
recorded instead of assigning all affected edits the same label.

Proxy families and their exact ordering, horizon, recomputation engine, exclusions,
matching rules, and adjudication rules must be frozen in a new protocol before any
label is materialized. V1 failure stops the line. It is forbidden to inspect failures
and then add a proxy family merely to recover sample size.

## 6. Leakage and protected-data boundary

Splits are by complete VEnron version group. No version, renamed copy, structural
near-duplicate component, or future state from a test group may enter training or
calibration. Labels, future versions, rollback outcomes, and proxy status are scoring
inputs only; the eventual prediction contract must state exactly which past states
are visible.

The protected directory `/home/ayaka/code/FormulaGuard_240_120/` is inaccessible
throughout V0, V1, model development, public calibration, and public testing. Before
the final candidate and complete public prediction lock are committed, no directory
enumeration, filename or schema inspection, hash, read, extraction, overlap check, or
test run is allowed.

The user has authorized Codex to run the protected evaluation without another reply
only after those lock conditions are satisfied. The evaluation is one-shot, cannot
tune the model, and must keep confidential artifacts and row-level results outside
Git. This authorization does not lower any public gate.

## 7. Next authorized operation

After this protocol, acquisition code, and tests are committed and pushed, run the
pinned download once and retain its SHA-256 receipt. V0 then has two ordered stages:

1. write, test, commit, and push a manifest-only audit before enumerating archive
   members; it may record path structure and extensions but may not extract or open a
   workbook;
2. use that immutable manifest to write, test, commit, and push the conversion and
   adjacent-transition audit before extraction.

This staging fixes the safety checks without guessing the unpublished archive layout.
An archive reader and its version must be recorded in each receipt. Protected data
remains untouched.
