# Protected-data search incident

Date: 2026-09-02
Status: current protected package quarantined from blind evaluation

During a delegated, read-only feasibility task, a malformed memory-search command
used `/` as an `rg` search root instead of restricting the search to the QCT
repository:

```text
rg -n -i "QCT|metamorphic|invariant|607|input-only|formula" / reasons?:[]/home/ayakaBots?
```

The command ran for 10.2 seconds. Its recorded output was heavily truncated: the
tool reported roughly 859 MB of omitted output. The retained output contains no
visible path or content from `/home/ayaka/code/FormulaGuard_240_120`, and the command
had no redirection or output-file argument. It therefore produced no known workspace
artifact. However, because `rg` recursively reads candidate files and the complete
output is unavailable, it is not possible to prove that protected files were not
opened or that protected text was absent from the omitted output.

Consequences:

1. Previous claims that the current protected package had zero content access are
   withdrawn.
2. The current package is not eligible to support a one-shot blind or independent
   validation claim. It remains prohibited as a development or model-selection
   input and must not be opened again.
3. Results from the delegated feasibility task are quarantined from model selection.
   Any public-mechanism conclusion must be re-established solely from QCT public
   files and committed receipts.
4. A formal protected evaluation now requires a fresh custodian-generated package,
   created and withheld until after the complete model and prediction lock is
   committed.

Corrective boundary:

- all discovery and search commands must use an explicit allowlisted root under
  `/home/ayaka/QCT`;
- filesystem-root searches are prohibited for this project;
- the protected directory must not be listed, searched, hashed, parsed, copied, or
  scored during continued public model development.
