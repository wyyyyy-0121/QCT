# HybridGuard paper protocol v1 — frozen before supplementary predictions

Scope: September 4 handoff, unchanged original source. Six original and 33 paired synthetic derivatives. Not independent or third-party evidence. No V519 solver.

Primary endpoints: workbook AP and exact candidate coverage. Secondary: all-proposal precision, harmful suggestions on correct cells, accepted groups with any wrong proposal, fixed-budget recall. Clean AP/recall undefined. No score-driven tuning, no significance or population-safety claim.

Data: 6 original, 6 corrected controls, lengths {1,10,100,500,1499} on clean seeds {101,202,303}, and shared-majority/single-sheet/legitimate-heterogeneity/interior-exception on these same three seeds. Construction is specified by prepare.py. Formula caches invalidated in derivatives; model evaluates formula graph from current XML. Expected formulas exist for all formula cells, including clean legitimate exceptions. Nonformula cell XML is verified unchanged. Single-sheet variants remove the other active workbook sheets; their orphan ZIP parts are not active model inputs.

Prediction input: input.xlsx, public.json (parallel sheet names only), configuration. Prediction audit hook rejects opening any truth JSON. Prediction hashes locked before scoring. Original labels are already known, so this separation is engineering hygiene, not blind validation.

Configs: full, no_sg (score and candidate fallback removed), no_fg (score/candidate removed, parser/evaluator retained), no_groups, no_validation (group accepted, validation score fixed to 1). All 39 inputs. Sensitivity only original six: supports 4/5 vs3; weight .5/.8 vs .65 with complementary run-strength coefficient; representatives1/5 vs3, evenly spaced integer-floor, deduplicated, strict majority. One representative is the midpoint. Other components untouched. No validation is an oracle-free ablation, not a deployable recommendation.

Expected: 231 Hybrid configuration/input pairs plus 78 baseline pairs, 348 compressed prediction files including 39 formula maps. Shared base features may be cached for ablations. End-to-end timing uses 18 separate cold Python processes (6 originals x3), no feature cache, sequential runs, perf_counter and Linux ru_maxrss /1024 MiB. Timing cannot be compared as a hardware-normalized speedup with original Windows numbers.

A repair proposal is nonempty and different from current formula. Exact repair compares the literal = prefixed formula with the expected formula. Precision denominator includes ALL changed proposals, including correct-cell damage. Coverage denominator is labeled errors. Harmful-proposal rate denominator is all originally correct formula cells. Accepted-group unsafe count uses each group's actual consensus suggestion against full expected formulas, not group name alignment. Cell and group counts are not independent trials. No-error AP is null.

Validation: source hashes; 5 original tests; input/data assertions; default adapter vs original functions and original saved ranking; formula parsing/evaluation; audit hook truth rejection; unit metric examples with harmful proposals; locked inventory/hash verification; serial repeat determinism; figure-table-body agreement; DOCX ZIP/OMML checks; PDF text/fonts/page renders. Failed variants stay in results; baseline changes forbidden to rescue claims.
