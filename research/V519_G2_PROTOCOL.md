# G2 Round Plan And Execution Protocol

This round implements `V519_G2_PLAN.md` on the frozen G1 baseline. The initial
model draft exists; no G2 acceptance evidence or API route has been published.
Before further implementation, this protocol records the execution order.

1. Finish per-diagnosis budget accounting and remaining-budget fallback.
2. Complete deterministic component search, full original-domain mapping and
   independent partition replay; retain original ranking and candidate portfolio.
3. Add counter, ambiguity, unknown evaluation, fallback and certificate attack
   tests, including 81/144-state multi-option domains.
4. Run all 72 G1 workbooks on both backends, verify their saved input/oracle hashes,
   and require all 24 predeclared pair/chain 4/8-cell workbooks to finish uniquely
   at default budgets with successful replay. Preserve every other result.
5. Audit results and record the G2 gate before beginning G3. No unified API route
   is added until the G3 gate passes.

Budget limits remain nodes=10000, leaf evaluations=4096, preparations=4096,
component states=256. Initial evaluation consumes preparation budget. Frozen
preparers alternate satisfaction and direct evaluation attempts; their reported
attempt counts are reconciled with a per-model wrapper's actual evaluator calls.
Failures before entering the evaluator remain visible as attempts minus actual
calls. Fallback never resets any counter. Replay has its own resource limits.

Certificate identity binds version/rule/runtime, input/approval/date, trusted
configuration, backend/policy, original domain, deterministic component mapping
and exact-float table digest. Replay reconstructs these from the actual model.
Terminal prefix intervals partition the entire mixed-radix component space;
the rebuilt bijection carries that coverage back to the complete original domain.
Every surviving leaf is re-evaluated with original satisfaction semantics.
All decision cells and atomic actions must match the unique assignment. Complete
ranking recomputation is mandatory in outer experiment verification.

The G2 code may be revised during development with failures retained. Later
G3, G4, G5 and G6 each receive a round plan before their work begins. G5 freezes
sources and protocols before new confirmation seeds are generated; no tuning
is allowed after that freeze.
