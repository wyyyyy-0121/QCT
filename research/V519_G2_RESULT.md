# V519 G2 result

G2 passed the predeclared minimum and complete G1 regression matrix.
All 72 workbooks produced unique solutions on both backends (144 diagnoses),
with independent persisted-certificate replay and full ranking/candidate identity.
The 24 minimum pair/chain 4/8-cell workbooks are included, not extra samples.
The initial focused suite passed 83 tests. See V519_G2_V1/result.json.

The solver preserves the original formula assignment domain, including no-change
and numerically equal but syntactically different choices. A per-diagnosis model
wrapper counts actual evaluate calls; preparation attempts and failed attempts
before evaluation are reported separately. Fallback retains consumed resources.

Proof replay rebuilds the original domain, table, bounds and component bijection;
checks a complete terminal partition; re-evaluates retained leaves; reconstructs
node/evaluation counts; and checks candidate/ranking identity and all atomic
decisions. A caller may supply a freshly recomputed ranking to avoid duplicate
ranker work; otherwise the verifier recomputes it itself.

These are revealed development inputs. No frozen confirmation was run at G2,
and the unified API remains gated on G3. In-memory acceptance decisions do not
write to Excel files. The complete V519 task remains active through G6.
