# V4 static-fifth public revision confirmation result

Date scored: 2026-09-03

Status: stopped negative result; no bounded candidate or formal version is
authorized

Protocol: `formulaguard_static_fifth_public_revision_score_v1`

## 1. Locked prediction evidence

The before-only prediction runner was frozen at commit
`9b6ebda1b90dc84458a01e1a03317c54fadae470`.  Two formal runs processed all
four preregistered `before.xlsx` workbooks:

- `results/static_fifth_revision_predictions_run_a`;
- `results/static_fifth_revision_predictions_run_b`.

Both runs recorded empty `label_inputs`, `label_members_read`, and
`protected_data_inputs`.  Their completion receipts, complete predictions, and
four per-workbook shards were byte identical.  Both receipts recorded:

- record set SHA-256:
  `230096b005f94fe33e29fe583db2c6f9dfc694b36070f97a9ad67b8009073d4c`;
- shard inventory SHA-256:
  `b68267a39ccabd4c560a3a01c4bb68e9e50ce3c1681b0954ff37f31dabd2735d`;
- completion receipt SHA-256:
  `c0127bd7e019bd856e4406afaa3092bbbed16c22d68972a90229ec51c9533f1f`.

The runner read only the four preregistered `before.xlsx` payloads before the
prediction lock.  It did not read `cases.csv`, `manifest.json`, any
`after.xlsx`, or either protected `240+120` package.

## 2. Independent revealed scoring

The independent scorer was frozen at commit
`21eed00ba117b95327e82b9cf6b397283e7ab352`.  Before opening labels, it
verified the two prediction locks, their byte equality, the archive hash, all
source hashes, all shard hashes, and ranking inventory parity.

Only after that verification did the scorer open `cases.csv`, `manifest.json`,
and the four `after.xlsx` payloads.  It independently reproduced all four
workbook revisions and all eight changed formula cells.  The immutable score is
in `results/static_fifth_public_revision_score`:

- `score_summary.json` SHA-256:
  `44c525243fdbf57875ccb9c3eb09b4fbad04210ad00b4dc564c43d9418f2a261`;
- `revision_scores.jsonl` SHA-256:
  `a0bf85a4ea14b68b56d663436c7d06f8bef26da44c13b3938d6118357d811019`;
- revision score set SHA-256:
  `5bc9898979103c8c47dfa9573fafc6505cec35fb40d2b8d9c001a27f0975e59f`.

No protected `240+120` input was read.  This four-revision archive is now
revealed and cannot be reused as a blind confirmation set for a newly selected
rule.

## 3. Results

| Measure | V4-R1 | V4 static-fifth |
| --- | ---: | ---: |
| Revision events | 4 | 4 |
| Event Top-1 | 0/4 | 0/4 |
| Event Top-5 | 0/4 | 0/4 |
| Event MRR | 0.08178626149131768 | 0.08178626149131768 |
| Changed formula cells in Top-5 | 0/8 | 0/8 |

The two methods assigned the same best changed-cell rank in every revision:
89, 11, 8, and 10 for `PWR001` through `PWR004`.  Static-fifth produced zero
Top-5 rescues, zero Top-5 losses, and zero per-revision regressions.

## 4. Frozen gate decision

| Gate | Result |
| --- | --- |
| Prediction and scoring integrity | Pass |
| Four revisions and eight formula changes reproduced | Pass |
| Same complete inventory and five-cell review budget | Pass |
| At least one net Top-5 rescue and strictly higher Top-5 | **Fail: 0 rescues; 0/4 versus 0/4** |
| Zero Top-5 losses and per-revision regressions | Pass: 0 |
| Event MRR non-degradation | Pass: equal |
| No protected input | Pass |

Because the preregistration requires every gate to pass, this confirmation
stops here.  The zero-action result does not authorize changing the rule,
lowering the gate, or selecting another peer-consensus variant on the revealed
revisions.  No
`research/V4_STATIC_FIFTH_REVISION_CONFIRMED_CANDIDATE.json` was created, and
this result does not authorize `V5-R1` or protected evaluation.
