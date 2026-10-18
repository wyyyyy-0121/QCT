# Exact training-fold reconstruction

Per-case selected options, folds and all SHA-256 locks are committed. Five
training files repeat these options four times; they are local derived copies
and are omitted from Git. Rebuild before auditing or running the learner:

```bash
/home/ayaka/hybridguard/.venv/bin/python qa/rebuild_absolute_training_files_dev24.py
```

This preserves case order, key order, gzip filename/mtime and compression level,
and asserts byte-for-byte SHA-256 equality with the frozen preparation lock.
Existing files are verified, never overwritten. The program also accepts
`--output-root PATH --fold ID` to test reconstruction in a fresh directory.

The source case states are development labels. The learner may open only its
current training-fold file. Author options and other-fold files stay forbidden
even for hashing in the learner process. Reconstruct in a separate process.
