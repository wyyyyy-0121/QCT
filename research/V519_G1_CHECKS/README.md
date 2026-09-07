# G1 execution checks

- `regression.log`: focused G1 and V518 pytest run, exit status 0.
- `test_inventory.log`: collected test identities for that run (128 tests).
- `matrix.log`: all 72 predeclared workbooks completed successfully.
- `ruff.log`: final repository Ruff check.
- `archive_audit.log`: exact saved population, tables, hashes and source snapshot audit.

The pytest invocation used the repository's quiet option plus `-q`, so its
progress log suppresses the count summary; the separate collection records
the exact 128 test identities. This is not a claim of a new full-repository
pytest run. G1 has no public repair acceptance API.
