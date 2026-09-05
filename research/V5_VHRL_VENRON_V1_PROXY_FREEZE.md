# FormulaGuard VHRL VEnron V1 proxy-label freeze

Date: 2026-08-31
Protocol: `formulaguard_vhrl_venron_v1_proxy_v1`
Status: frozen before reading cached formula results or materializing any proxy label
Parent result: `research/V5_VHRL_VENRON_V0_RESULT.md`

## 1. Purpose and claim limit

V0 passed with 423 nonbulk multi-direct formula transitions across 70 groups. V1
tests whether those real histories contain enough mechanically reproducible proxy
events to support a responsibility-ranking experiment. It does not train or select a
model.

VEnron has no author-intent, silent-error, expected-output, or human-confirmed fault
ground truth. The labels below are explicitly named **rollback-error proxies** and
**exact-reversion proxies**. Neither may be called a real spreadsheet error, an
unintended edit, a semantic bug, or proof of human correction.

Explicit errors, future-version mining, rollback testing, regression testing, and
causal responsibility are prior ideas. FormulaGuard may claim no novelty for these
labeling operations. Their only role is to construct an auditable public development
task for the later, narrower multi-edit responsibility-ranking hypothesis.

## 2. Frozen candidate population

The only candidates are the 423 V0 transitions with
`nonbulk_multi_direct=true`. Their group, order, formulas, additions/removals, and
V0 category are immutable. A candidate cannot be added by changing sheet alignment,
formula normalization, bulk thresholds, or order.

For every candidate, direct edit keys are exact `(worksheet title, A1 address)` keys
that contain a formula on both sides and whose end-trimmed formula strings differ.
No sheet rename, address move, formula addition/removal, cached value, text cell,
format, filename meaning, email field, V4 score, or protected datum defines a direct
edit.

## 3. Cached explicit-error profile

For each parsed converted XLSX, the program may reopen it with `data_only=True` and
look only at keys known from the formula-only profile. It exports only the keys whose
cached result is one of these exact error tokens:

`#NULL!`, `#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`, `#NUM!`, `#N/A`,
`#GETTING_DATA`, `#SPILL!`, or `#CALC!`.

No non-error cached value is persisted, counted by magnitude, tokenized, hashed as a
feature, or used for matching. A `new explicit error` is a current-version formula
key in that set that was not in the previous version's set. This is an observable
runtime proxy, not an assertion that the formula is invalid in its business context.

## 4. Strong family: rollback-error proxy

A candidate enters isolated rollback testing only when it introduces at least one new
explicit error and has between 2 and 12 direct edit keys inclusive. For each key:

1. copy the current converted workbook into a temporary ignored workspace;
2. replace only that key's current formula with its exact previous formula;
3. save, recalculate once with the same recorded LibreOffice build and an isolated
   user profile, then collect explicit-error keys under Section 3;
4. label the key an `isolated rollback-error proxy` only if at least one baseline new
   explicit error disappears and the rollback introduces no explicit-error key that
   was absent from the unmodified current workbook.

If no isolated key succeeds and the candidate has 2-8 direct edits, test every
unordered pair under the same rule. A pair is a `joint rollback-error proxy` only if
the pair succeeds and neither member succeeded alone. No triple or larger rollback is
tested. A transition belongs to the strong family if it has at least one isolated or
joint proxy. All attempted, successful, failed, timed-out, and unrecalculable rollback
counts remain visible.

Rollback edits operate only on existing formula cells. They do not restore constants,
formats, added/deleted sheets, formula additions/removals, or cached values. Thus the
proxy measures responsibility under a deliberately narrow intervention.

## 5. Weak family: exact-reversion proxy

For each candidate direct edit `f0 -> f1`, inspect at most the next three author-
ordered versions in the same evolution group. The key must exist as a formula in all
intermediate versions. The key is an exact-reversion proxy if the first later formula
that differs from `f1` is exactly `f0` after end trimming. A third formula, missing
key, renamed sheet, moved address, parse failure, or no change within the horizon is
not a reversion.

Future formulas are label evidence only. They are forbidden prediction features,
training context, candidate-generation inputs, thresholds, or model-selection data.
A reversion can represent an intentional cycle or periodic report change, so this
family is always reported separately from rollback-error proxies.

## 6. Transition labels and controls

A positive transition has at least one strong or weak proxy key. If both occur, both
tags and key sets are retained; no precedence erases evidence. Local detailed labels
may contain opaque group/order IDs, sheet/address keys, proxy family, horizon, and
rollback outcome. They may not contain constant values, cached non-error values,
sender/email fields, original filenames as model features, or protected data.

Controls come from the same 423-candidate population and must have neither proxy
family. Select at most one unique control per positive in stable positive-ID order.
For each positive, minimize this fixed lexicographic tuple among unused controls:

1. same group preferred (`0` versus `1`);
2. absolute difference in direct-edit count;
3. mismatch count for whether additions exist and whether removals exist;
4. absolute difference in `floor(log2(1 + current_formula_count))`;
5. SHA-256 of the control transition ID.

Controls are matching evidence only; same-group controls remain in the same later
train/calibration/test group split. No random resampling or manual replacement is
allowed after counts are observed.

## 7. V1 gates and stopping rule

All conditions must hold:

1. at least 60 positive proxy transitions across at least 30 evolution groups;
2. at least 20 rollback-error proxy transitions across at least 10 groups;
3. at least 20 exact-reversion proxy transitions across at least 10 groups;
4. at least 60 unique matched controls across at least 30 groups;
5. every rollback result is reproducible in a second independent process for a fixed
   10% stable-hash audit sample, with identical explicit-error key hashes;
6. cached non-error values, constants, email data, fault labels, V4, expected outputs,
   and protected inputs are all empty in the receipts.

Any failure stops VHRL before feature construction or model implementation. The error
token set, horizon, direct-edit limits, rollback success condition, pair policy,
matching tuple, and thresholds may not be changed after the first complete V1 score.

Passing V1 authorizes a separate feature/model preregistration only. It is not a
performance result and does not authorize use of the protected 240+120 package.

## 8. Protected-data boundary

`/home/ayaka/code/FormulaGuard_240_120/` remains inaccessible. V1 must not enumerate,
hash, inspect, read, extract, match, or overlap-check it. The user's standing one-shot
authorization applies only after a final candidate and complete public prediction
lock are committed; V1 cannot use it.
