# R2 related-work evidence map

This is the paper-writing companion to `V5_CORE_R2_NOVELTY_AUDIT.md` and
`REFERENCES_R2.bib`.  It separates facts supported by prior work from the
bounded claim made by FormulaGuard R2.  It is not an experimental result.

| Existing line | What the original source establishes | What R2 must not claim | R2-specific gap addressed |
|---|---|---|---|
| Formula-pattern and region anomaly detection: ExceLint | Static analysis can use local rectangular regularity and information-theoretic surprise to identify formula anomalies. | Formula-region anomaly detection or formula repair candidates are not R2 inventions. | R2 asks which anomaly is the upstream propagation source, and its initial rank does not require a repair candidate. |
| Style-adaptive clustering: CUSTODES and WARDER | Formula AST/dependency structure and style-aware clusters can detect smells; WARDER refines clusters with validity properties. | AST families, dependency representations, clustering, and validity checks are not new. | R2 turns regime/graph similarity into a matched **observational null distribution**, rather than treating minority membership as a fault verdict. |
| Test- or goal-based spreadsheet diagnosis: GoalDebug, Hofer et al., FaultySheet Detective, MUSSCO | Expected values, failing/passing tests, cones, and distinguishing tests can localize or disambiguate spreadsheet faults. | R2 is not a replacement for test-driven or expected-output diagnosis, and it cannot describe its no-oracle result as better than those settings. | R2 assumes none of those signals are available; it emits a complete review ranking plus abstention when evidence is insufficient. |
| Mutation/intervention fault localization: Metallaxis-FL and AID | Mutants and interventions can carry localization information when a system has test outcomes or repeated executions. | Mutation-based fault localization and causal intervention are not new. | R2 compares a candidate formula edit with similar edits on matched formulas (**placebo intervention null**), without passed/failed tests, and limits any reorder to the observationally uncertain set. |
| Formula repair: MUSSCO, LaMirage, FLAME | Candidate generation, symbolic constraints, neural ranking, and formula completion/repair are active areas. | Candidate generation and learned formula repair are not R2's central contribution. | R2 uses repair as an explanatory probe only: source ranking remains defined when the correct repair is missing from the pool. |
| Input metamorphic testing: SEDMR | Input transformations and metamorphic relations can reveal spreadsheet errors without a traditional output oracle. | Metamorphic testing and no-output error detection are not new. | R2 intervenes on the **formula** and evaluates directed propagation recovery; it does not declare an error solely from a relation violation. |

## Safe contribution statement for the paper

> FormulaGuard R2 studies silent formula-source localization when correct
> outputs, test spectra, and error labels are unavailable.  It first produces a
> repair-candidate-independent source ranking using a regime- and graph-matched
> observational null model.  Candidate edits then act only as explanatory
> interventions, calibrated against edits at matched formulas and allowed to
> reorder only observationally indistinguishable candidates.  The system may
> explicitly abstain.  To our knowledge from the documented literature search,
> we did not find the same complete combination in prior spreadsheet work.

This sentence intentionally does **not** assert that any component in
isolation is first introduced here.  Cite the individual prior works when
describing their mechanisms, and use the final independent confirmation set
for all performance claims.

## Claim-to-citation guidance

- Cite `barowy2018excelint` for rectangular/static formula-anomaly detection.
- Cite `cheung2016custodes` and `huang2020warder` for formula/dependency
  clustering and style/validity refinement.
- Cite `abraham2007goaldebug`, `hofer2013empirical`,
  `abreu2014faultysheet`, and `abreu2015mussco` when explaining why
  expected outputs, test spectra, or distinguishing tests are different from
  the no-output setting.
- Cite `papadakis2015metallaxis` and `fariha2020aid` to delimit the existing
  mutation and intervention traditions.
- Cite `bavishi2022lamirage` and `joshi2024flame` only for repair/completion
  context, not as a localization baseline unless their original implementation
  is run under a compatible protocol.
- Cite `yang2026sedmr` for input metamorphic testing; do not call SEDMR a
  formula-replacement or source-localization method.
