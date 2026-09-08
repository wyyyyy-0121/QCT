# G6 Round Plan: Final Audit And Delivery

Recorded before G6 work; execution follows G5 scoring and includes any required
failure disposition. A passing intermediate gate is not complete V519 delivery.

1. Audit every gate against V519_DEVELOPMENT_PLAN.md and V519_G2_PLAN.md: fixed
   populations, minimum successes, oracle comparisons, original-domain identity,
   unchanged ranking/candidates, budgets, refusal states, policies and proofs.
2. Recheck the confirmation source snapshot and current files, runtime identity,
   all input/approval/label hashes, complete prediction inventory, and chronology
   freeze < seed/input generation < prediction lock < reveal < scoring.
3. Re-read all raw accepted transactions against now-authorized labels, verify
   group identities/sizes and formula equality, and retain the whole error
   denominator. Distinguish independent workbooks from backend/seed repetition.
4. Run final full-repository pytest and Ruff, with saved logs. Verify the actual
   local Python API aliases on both backends and policies. Do not describe this
   API as an external network service or Excel writeback mechanism.
5. Publish stage results and a complete final report: successes, ambiguity,
   no solution, already satisfied, invalid approval, numeric/structural fallback,
   unknown evaluation, budget refusal, applicability and full measured costs.
   Explain runtime-specific numeric assumptions and synthetic-evidence limits.
6. Version compact inputs/evidence, source locks, receipts and scripts; retain
   large raw results/source snapshots in their independent ignored results paths.
   Stage only the explicit V519/API allowlist, commit, push the current branch
   and verify remote HEAD equality and absence of unexplained worktree changes.
7. Mark the active G2-G6 goal complete only after the full audit succeeds. If a
   gate genuinely fails, preserve the failed experiment and state the unresolved
   criterion; do not re-label a partial implementation as full completion.
