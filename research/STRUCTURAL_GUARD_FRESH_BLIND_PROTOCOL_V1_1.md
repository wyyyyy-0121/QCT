# Structural Guard fresh blind comparison protocol v1.1

This protocol inherits every model, dataset, metric, promotion gate, and execution
rule from `STRUCTURAL_GUARD_FRESH_BLIND_PROTOCOL_V1.md`.

## Pre-reveal correction

Attempt 1 was terminated before SECRET reveal because the V4-R1 prediction
shards included the diagnostic field `localization_seconds`.  Two otherwise
identical executions therefore produced different byte hashes.  A label-free
comparison found no differing ranking, score, candidate formula, or other
evidence field; only wall-clock timing differed.

Version 1.1 removes `localization_seconds` from serialized prediction evidence.
Runtime is not a declared evaluation metric.  No model source tree, parameter,
dataset composition, scoring definition, bootstrap setting, or promotion gate is
changed.

Attempt 1 PUBLIC and SECRET are retired without scoring.  Version 1.1 requires a
new random seed and a newly generated 360-case PUBLIC/SECRET pair after the
corrected runner and lock are committed and pushed.

