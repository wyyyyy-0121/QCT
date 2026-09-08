# V5-PSL public corpus workspace

`corpus_registry.json` is the tracked source and license inventory. Raw archives,
repositories, converted workbooks, and extracted files remain local and must not
be committed.

Validate the registry:

```bash
python scripts/prepare_v5_psl_public_corpora.py show --json
```

Download one pinned source only after reviewing and accepting its terms:

```bash
python scripts/prepare_v5_psl_public_corpora.py download \
  --corpus info1 \
  --root data/external/v5_psl/raw \
  --accept-terms
```

Create a hash-only inventory after acquisition or conversion:

```bash
python scripts/prepare_v5_psl_public_corpora.py adapt \
  --corpus info1 \
  --source data/external/v5_psl/raw/info1/extracted \
  --output results/v5_psl_corpus_inventory/info1
```

The SFL-corpus adapters intentionally leave legacy sheet-number coordinates in
`source_cells_raw` and mark them pending. Mapping those labels to converted
sheet names and deciding whether a multi-fault case is identifiable require a
manual, recorded review. FoRepBench remains repair-only and SpreadsheetBench
remains parser-stress-only.

Run the two supplemental role audits separately from localization scoring:

```bash
python scripts/audit_v5_psl_supplemental_corpora.py \
  --registry data/external/v5_psl/corpus_registry.json \
  --corpus forepbench --source data/external/v5_psl/raw/forepbench/repository \
  --output results/v5_psl_corpus_roles/forepbench
python scripts/audit_v5_psl_supplemental_corpora.py \
  --registry data/external/v5_psl/corpus_registry.json \
  --corpus spreadsheetbench --source data/external/v5_psl/raw/spreadsheetbench/repository \
  --output results/v5_psl_corpus_roles/spreadsheetbench
```

The formal SpreadsheetBench role audit cannot use `--limit`; `--limit` exists
only for an engineering smoke run. The final public-pressure audit requires all
six `inventory_audit.json` files, both `role_audit.json` files, the completed
pressure run, and `research/V5_PSL_MECHANISM_REVISION_LOG.json`.
