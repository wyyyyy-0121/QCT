# V6 Enron retrospective inventory correction

## Decision

V6 must evaluate all 30 evaluation-ready Enron events as a retrospective safety check. The first V6-A run evaluated only the 20 events in the historical external-test partition because `scripts/run_v6_enron.py` inherited `test_manifest.csv` as its default. This contradicted the V6 preregistration, which specifies 30 existing Enron events and does not use them for V6 model selection.

The correction changes only the V6 Enron orchestration and audit gate:

- default manifest: `data/external/enron/manifest.csv`;
- included events: every row with `include=1`, exactly 30 events;
- required audit gate: both V4 and V6 must contain exactly 30 event rows;
- V4, V5.2 and V6 model source files, thresholds, candidates and ranking logic are unchanged.

## Why 20 appeared

The historical Enron split was created before V6:

- 10 small events were assigned to the old development partition;
- 20 other events were assigned to the old external-test partition;
- the two partitions are disjoint and their union is the 30 evaluation-ready events.

That split remains valid historical evidence for earlier versions. V6, however, preregistered Enron only as a retrospective non-degradation check, so there is no methodological reason to exclude the ten old development events from that check. None of the 30 events is independent V6 evidence and none may be used to tune V6.

## Frozen evidence before correction

| File | SHA-256 |
|---|---|
| `data/external/enron/manifest.csv` | `3eb129423a92320db57c69af667c6d58a25c85e4548fd6adf8ba581054201abd` |
| `data/external/enron/test_manifest.csv` | `00afd8e2136447d120b89d651ceeb1d5f877e234ab4e1901003a097961891533` |
| `data/external/enron/split_lock.json` | `14a28ac3b9aa7f28aaa4f2b8e84e69c0556cde315d234f9c2b928a6e39748893` |
| `formulaguard/v6.py` | `75296073a37c31c422364361d7fde7d6da0a313b816b5e7d7f5cc71b95d2a3c3` |
| `formulaguard/localize.py` | `760fbf8519dce5a4604bcc6ba158e9ca44d9434e7e898c85e9f7bc51c6c99c40` |

The original 20-event V6-A Enron output is retained locally as a historical snapshot. Corrected V6-A Enron predictions are produced in a separate directory, verified, and only then promoted to the canonical V6-A Enron result directory. No development, red-team or clean-control prediction is rerun or replaced.

## Reporting rule

The paper must state that Enron contains 30 evaluation-ready retrospective events originating from a previously inspected corpus. It must not call these cases independent or blind. The corrected 30-event result supersedes the accidental 20-event V6-A safety statistic, while the correction history remains auditable.
