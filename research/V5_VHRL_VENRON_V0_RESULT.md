# FormulaGuard VHRL VEnron V0 result

Date: 2026-08-31
Protocol: `formulaguard_vhrl_venron_gate_v0`
Implementation commit: `fd9221a086dbe909f397fc59dbcf64bf8260cd82`
Status: all frozen V0 resource gates passed; V1 not yet authorized

## 1. Evidence identity

- public archive SHA-256:
  `15f1b134157e65ea68f7e262a73b1571fd9f3f5e1256ab3aa52bfdea87628d98`;
- prepare receipt SHA-256:
  `87db20e5233a77b64030fddff6c95c0781662bb7c07d607e8f2c87230cedded8`;
- profile receipt SHA-256:
  `54b24336912fa0ce4d50f55ef1897bef4e7ed40e1d7313a9a17fff6fcba924e0`;
- gate-result SHA-256:
  `4743f0a1fb929afc6d98f4ebbfa3ac9b74022fa272c98f84da2f95f8b91b723e`;
- transition-manifest SHA-256:
  `8a8ff6e13fdebc44f28d4abb509357c9475c3badf00a679d8bbf33456cc9a5ee`.

Raw archives, extracted workbooks, converted workbooks, formula profiles, member
names, and transition rows remain under ignored local paths. They are not committed.

## 2. Corpus and conversion result

- 360 evolution groups and 7,294 author-ordered group workbooks;
- 7,294/7,294 converted and parsed successfully: 100% coverage;
- 4,465 workbooks contain formulas; 2,829 contain zero formulas after conversion;
- 9,191,387 formula-cell observations across all versions;
- 6,934/6,934 adjacent transitions have two parsed endpoints;
- zero conversion or parse failures and zero ineligible adjacent transitions.

The publisher metadata contains 7,232 byte-matching MD5 identities and 62 mismatches
across 29 groups. All mismatches remain bound by the fixed archive SHA-256, exact
member path, actual MD5, and actual SHA-256. Their stable discrepancy-set hash is
`86820c36e03b3c52823d21856a200be874ff4df6602b21955ffbe11a891e42ff`.
This upstream quality issue is reported separately and is not a model feature.

## 3. Frozen transition counts

| Mechanical category | Transitions |
|---|---:|
| Any same-sheet, same-address direct formula-text change | 1,190 |
| Exactly one direct change | 137 |
| At least two direct changes, before bulk exclusions | 1,053 |
| Nonbulk multi-direct candidate | 423 |
| Bulk direct rewrite | 60 |
| Bulk formula addition/removal | 1,293 |
| Address-only exact-formula move | 67 |
| Any formula addition | 2,031 |
| Any formula removal | 1,729 |
| No formula-text change, addition, or removal | 4,316 |

Direct formula changes span 152 groups. Nonbulk multi-direct candidates span 70
groups. Categories can overlap except where their definitions explicitly exclude one
another; they must not be added as a partition total.

## 4. Gate decision

All preregistered V0 gates passed:

1. `360 >= 300` groups and `7,294 >= 6,000` workbooks;
2. `1,190 >= 1,000` direct-change transitions across `152 >= 150` groups;
3. `423 >= 100` nonbulk multi-direct transitions across `70 >= 30` groups;
4. parse coverage `100% >= 80%`;
5. all required change and failure categories were reported separately;
6. fault labels, protected data, cached-value differences, expected outputs, and V4
   inputs were all empty.

The direct-change group margin is narrow: 152 observed versus a gate of 150. This
must be reported rather than described as broad coverage.

## 5. Claim boundary and next step

V0 establishes only that the public corpus contains enough real, ordered, nonbulk
multi-formula changes to attempt a responsibility-ranking study. It does not show
that any transition contains an unintended error, that a changed cell caused a
regression, that VHRL can rank responsibility, or that VHRL improves over `V4-R1` or
prior academic methods.

V1 remains blocked until a new protocol freezes the exact regression-proxy families,
recomputation engine, future-version horizon, isolated and joint rollback semantics,
control matching, exclusions, minimum label counts, and privacy-safe output schema.
No proxy label has been materialized and no VHRL model has been implemented.

The protected `/home/ayaka/code/FormulaGuard_240_120/` directory was not enumerated,
hashed, opened, overlap-checked, or otherwise accessed. The existing one-shot
authorization remains conditional on a final committed candidate and complete public
prediction lock.
