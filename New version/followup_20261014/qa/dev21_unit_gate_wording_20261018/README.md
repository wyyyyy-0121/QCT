Terminology correction only. The archived audit used the field
`unique_compatible_correct_candidate_exists` for candidates that were merely
not rejected as explicitly incompatible. This included unknown unit states.
Unknown was never used as a known-compatible feature or a correctness label.

The canonical audit now uses
`unique_correct_candidate_not_rejected_by_unit_gate`. Prediction files, model
parameters, scores and the numerical necessary-condition bound are unchanged.
These files preserve the originally published audit source, result, log and
checkpoint receipt; the Python file is a historical source snapshot.
