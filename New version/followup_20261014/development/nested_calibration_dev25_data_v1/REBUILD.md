# Rebuild nested three-source supervision

The ten training files concatenate published dev24 per-case certified options.
They are omitted from Git to avoid duplicating the same state rows many times.
All hashes, case sets and fold exclusions remain in the preparation lock.

```bash
/home/ayaka/hybridguard/.venv/bin/python qa/rebuild_nested_training_dev25.py
/home/ayaka/hybridguard/.venv/bin/python qa/audit_nested_training_dev25.py
```

Existing files are checked without overwrite. Rebuild checks exact SHA-256,
including deterministic JSON key order and gzip metadata. `--output-root PATH
--pair pair_01` supports a separate reconstruction check. Use the same absolute
research-root path when verifying runtime access records from the original run.

This author preparation must run outside learner processes. During training,
only the current pair's three-source training file is allowed. During outer
calibration only the current outer fold's four-source repair-label file is
allowed. Neither process may read final outer answers or old outer predictions.
