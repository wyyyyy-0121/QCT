# V5.1.2 pre-reveal serialization amendment

The first frozen runner serialized V4's `localization_seconds` evidence field.
All 144 V4 fixture shards differed between the two runs. A recursive comparison
of every shard found this was the only differing field. Rankings, scores,
candidate formulas, and other evidence were identical.

No held-out labels or scored results were read before this amendment. It changes
only prediction serialization: omit the exact `localization_seconds` field and
declare the exclusion in metadata. Model source, parameters, scoring formulas,
and gates are unchanged. The first-run artifacts remain untouched.

Freeze a second source snapshot, generate a fresh fixture seed, copy the same
retrospective real-workbook inventory, and run both predictions again. The second
snapshot is the evaluation snapshot. This is a reproducibility correction, not
model tuning on held-out outcomes.
