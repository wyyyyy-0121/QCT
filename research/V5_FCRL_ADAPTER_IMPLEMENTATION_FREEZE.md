# FormulaGuard FCRL adapter implementation freeze

Date: 2026-08-31
Protocol: `formulaguard_fcrl_adapter_v1`
Status: frozen before any FCRL corpus example is constructed or scored
Parent: `research/V5_FCRL_MECHANISM_SELECTION_AND_PREREGISTRATION.md`

## 1. Purpose and non-claim

The public ForTaP repository consumes proprietary TableSense JSON, not XLSX.  This
record fixes the deterministic XLSX-to-ForTaP adapter before observing any FCRL
corpus result.  The adapter is engineering required to exercise the cited ForTaP
backbone; it is not a claimed research contribution and it may not be tuned against
U1-U4 or protected-data outcomes.

## 2. Workbook and target eligibility

QCT `WorkbookModel` is the only XLSX reader.  A target must be a visible formula cell
accepted by the existing QCT parser.  Formula AST nodes map to the official ForTaP
prefix vocabulary as follows:

- binary and unary nodes: operator followed by operand subtrees;
- function nodes: uppercase function token followed by argument subtrees in order;
- cell: absolute markers removed, token type `CELL`;
- range: start `CELL`, `:` as `SPECIAL`, end `CELL`;
- numeric literal: its text with token type `NUMBER`, which ForTaP maps to `C-NUM`.

Functions and operators absent from the published ForTaP formula-prediction
vocabulary are rejected rather than mapped to `<UNKOP>`.  QCT formulas containing
unsupported syntax are rejected.  Explicit sheet references, including references
back to the current sheet, are rejected because ForTaP has no cross-sheet pointer
contract.  A formula with no cell or range reference is rejected because the fixed
two-stage decoder's range loss would otherwise contain only ignored labels.  A prefix
sequence longer than 64 tokens including `<START>` and `<END>` is rejected.

## 3. Table component and crop

Only visible cells on the target sheet are eligible context.  Occupied rows and
columns include cached cells and formula cells.  The target component is the maximal
contiguous occupied-row band and occupied-column band containing the target.  Every
explicit reference endpoint must fall inside that component; otherwise the target
is rejected as a cross-table reference.

The mandatory rectangle is the bounding box of the target and all explicit
reference endpoints.  Either dimension above 256 is rejected.  Each dimension is
then expanded, without crossing the component boundary, toward 32 cells.  Expansion
is balanced around the target, with the lower row or column receiving the odd extra
cell.  A dimension already wider than 32 is not reduced.  The resulting actual A1
rectangle is passed to the official tokenizer.

The first component row is one flat top-header row only when it remains in the crop;
the first component column is one flat left-header column only when it remains in the
crop.  Otherwise the corresponding header count is zero.  Hierarchical positions
use the official flat fallback: `[-1,-1,-1,local_column]` for the top tree and
`[-1,-1,-1,local_row]` for the left tree.

## 4. Cell values, formats, and leakage boundary

Cell strings use cached XLSX values, never formula text.  Booleans are `TRUE` or
`FALSE`; finite numbers use a locale-independent 15-significant-digit spelling;
non-finite values and missing cached values are empty.  The target cached value is
cleared before tokenization.  The official `FPTokenizer.fp_preprocess` then replaces
the target cell by `[SEP],[FORMULA]`.  The target formula prefix appears only in the
decoder label/scorer and never in encoder tensors.

The 11 published format fields are `[merged_rows, merged_columns, top_border,
bottom_border, left_border, right_border, date, has_formula, bold, white_background,
black_font]`.  QCT fixes unavailable fields to the official neutral defaults:
`[1,1,0,0,0,0,date,has_formula,0,1,1]`.  `date` is derived only from the XLSX number
format; `has_formula` is derived from formula presence and is retained for the masked
target as part of the published formula-cell contract.

No filename, sheet name, raw text, raw number, or embedding may enter a receipt,
prediction lock, test fixture, or Git artifact.  Adapter tests use synthetic in-memory
workbooks.  Replacing only the target formula and cached target value must leave the
complete encoder-tensor hash unchanged.

## 5. Sequence limit and reachability

Cells are emitted in the official row-major order.  Cell strings are limited to eight
tokens and the complete encoder sequence is hard-truncated to 512 tokens, matching
ForTaP's public formula-prediction runner.  Unlike the official loader's dummy-label
fallback, FCRL rejects an example unless both target `[SEP],[FORMULA]` tokens survive.
Reference pointers outside the retained 512 tokens receive the official null range
label and count as unreachable.  U1 reports the aggregate reachable/total gold
reference-token fraction and keeps the preregistered 70% gate.

## 6. Local-peer alternatives

Peer formulas must be visible, parseable formulas in the same component and share
the target row or target column.  They are translated to the target with QCT's fixed
relative/absolute-reference translation, then rechecked under Sections 2 and 3.
Peers are ordered by Manhattan distance, row, and column; candidate strings are
normalized only after translation.

A translated-formula block is a maximal consecutive run of peer cells on one row or
one column producing the same normalized target formula.  A block contributes at
most one independent peer support.  The preregistered support rule remains unchanged:
two independent peer blocks, or agreement between the decoder beam and at least one
peer block.  The observed formula itself is never an alternative.

## 7. Frozen implementation constants

- official source commit: `4de8bba4e9bf6a89b2e131bfb471b4db2c45b951`;
- base checkpoint SHA-256:
  `42c2166afb60fedf833fcdbc4469dd6e23611f786aa7220a20375117c6c5a4a1`;
- backbone: official `BbForTuta`, all 205 tensors loaded by exact key and shape;
- decoder: official `LSTMLM`, three layers, attention enabled, dropout 0.10, new
  parameters initialized with the official `init_tuta_loose` `Normal(0,0.02)` rule;
- input/cell/formula limits: 512 / 8 / 64;
- row/column/tree limits: 256 / 256 / 4, node degrees `32,32,64,256`;
- context target per dimension: 32;
- no TableSense inference, no Enron fine-tuned weight, no `torch_scatter` dependency.

The official aggregate `FPTUTA` import is intentionally not used because
`model/heads.py` unconditionally imports undeclared `torch_scatter`; the selected
backbone and LSTM decoder do not require that package.  Gate U0 must record this
compatibility boundary rather than changing the environment to conceal it.

## 8. Pre-corpus synthetic U0 compatibility amendment

The first synthetic U0 decoder call, before constructing or scoring any FCRL corpus
example, exposed an official layout mismatch under Torch 2.13.  `LSTMLM.sketch_logits`
transposes its LSTM query to sequence-first layout but passes batch-first ForTaP
encoder states as the attention key and value.  With batch size one and sequence
length 24 this fails inside `MultiheadAttention` before producing a score.

The fixed compatibility adapter transposes only encoder key/value from
`[batch,sequence,hidden]` to `[sequence,batch,hidden]` at that official attention
call.  Query, parameters, outputs, loss, initialization, and all data rules are
unchanged.  The same patch is installed on every load and must be reported in U0.
This amendment is frozen after the synthetic exception and before any public or
protected corpus example is constructed.
