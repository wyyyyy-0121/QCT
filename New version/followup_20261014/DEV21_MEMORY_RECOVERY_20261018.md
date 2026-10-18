# dev21 interrupted training and memory recovery

The previous run did not finish its first fold and has no model, prediction or
prediction lock. Its source lock is preserved in `qa/dev21_interrupted_attempt/`.
The previous-boot kernel journal explicitly records an OOM kill at 17:19 on
2026-10-18: Python PID 25768 had 13,351,036 KiB anonymous RSS, with swap exhausted.
The selected-row audit was also running at the time. Raw OOM lines are preserved
in `qa/RELATIVE_LEARNING_DEV21_OOM_20261018.log`.

Recovery keeps all original selections, ordering, hierarchical weights,
float32 feature subtraction, mirrored examples, HGB parameters, gates and
thresholds. Only matrix storage changes. Float32-rounded values are written to a
temporary float64 NumPy memory map, then reopened read-only. This matches HGB's
existing float64 validation values without retaining both a complete float32 and
float64 anonymous matrix. Candidate payloads and label dictionaries are released
before fit. Temporary matrices are hashed by streaming and removed after fitting.
Training and the full training-selection audit run sequentially.

An equivalence test compares every matrix entry, fitted model probabilities,
sample weights and selected suggestions with the original in-memory procedure.
This is an implementation recovery before predictions exist, not a new choice of
method based on held-out scores. Final-data eligibility remains false.
