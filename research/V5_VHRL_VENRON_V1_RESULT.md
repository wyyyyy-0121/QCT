# FormulaGuard VHRL VEnron V1 result

Date: 2026-08-31
Protocol: `formulaguard_vhrl_venron_v1_proxy_v1`
Scan implementation commit: `07011309743c8a98f4a11fe5195dbd0dac764f8f`
Status: failed by a pre-rollback upper bound; VHRL model implementation not authorized

## 1. Evidence identity

- V0 gate-result SHA-256:
  `4743f0a1fb929afc6d98f4ebbfa3ac9b74022fa272c98f84da2f95f8b91b723e`;
- V0 transition-manifest SHA-256:
  `8a8ff6e13fdebc44f28d4abb509357c9475c3badf00a679d8bbf33456cc9a5ee`;
- V1 scan receipt SHA-256:
  `67e19691398c3a7886725e4b22051d93ff3c3e4c225539b80cf59aef8e26876a`;
- V1 candidate-manifest SHA-256:
  `313b8e5d0c248c383e60451afb84ce3cf579234194816fcf1f34e3b93897a1de`;
- explicit-error profile index SHA-256:
  `1a93771dc3a5a726930af6d68c2e98f1ea87f27b49c5d43ea717b4134d9284f8`.

Detailed formula identities, error keys, and candidate rows remain in ignored local
results. No cached non-error value, constant, email field, fault label, V4 input, or
protected input was exported.

## 2. Frozen scan result

- V0 nonbulk multi-direct candidates: 423;
- unique endpoint workbooks error-profiled: 615;
- exact-reversion proxies before rollback: 77 transitions, 21 groups, 4,793 keys;
- transitions introducing at least one new explicit-error key: 33 across 12 groups;
- transitions eligible for isolated rollback under the fixed 2-12 edit rule: 22;
- transitions eligible for pair rollback under the fixed 2-8 edit rule: 16;
- union of exact-reversion and new-error screens: 102 transitions across 29 groups;
- rollback labels materialized: 0.

The large 4,793 reverted-key count does not imply 4,793 errors. It includes bulk
within-transition exact reversions that survived the V0 transition-level bulk rules,
and exact reversion remains a weak proxy only.

## 3. Impossibility proof and stopping decision

V1 Gate 1 requires at least 60 positive proxy transitions across at least 30 groups.
Under the frozen protocol, every eventual positive belongs to one of two sets:

1. an exact-reversion transition already fully determined by the scan; or
2. a rollback-error transition, which must first be one of the observed new-explicit-
   error transitions.

Rollback can remove candidates from the second set but cannot add a transition or
group outside it. Therefore the final positive-group set is a subset of the observed
screen union, whose cardinality is 29. The preregistered 30-group requirement is
mathematically unreachable regardless of any isolated or pair rollback outcome.

The strong-family count is also narrow: at most 22 transitions can enter isolated
rollback, while Gate 2 requires 20 successful transitions. Pair rollback is a subset
of 16 of those candidates and cannot repair the failed 30-group upper bound.

The pipeline therefore stopped before thousands of LibreOffice rollback runs,
control matching, repeat-process audit, feature construction, or model implementation.
This is a protocol failure, not a compute failure.

## 4. Prohibited post-hoc rescue

The following are not allowed on this evidence fold:

- lowering the 30-group gate to 29;
- extending the three-version future horizon;
- adding approximate or address-moved reversions after seeing the count;
- calling every new explicit error a strong label without rollback;
- allowing more than 12 isolated or eight pairwise direct edits;
- importing formula additions/removals, email text, V4 scores, or protected data to
  create labels;
- treating 4,793 reverted keys as confirmed faults.

V0 remains a valid public corpus-resource result: real multi-edit version histories
exist. V1 shows that this particular two-family proxy contract does not provide the
preregistered cross-group label coverage. VHRL under this protocol is stopped and is
not a main-model candidate.

## 5. Protected-data boundary

`/home/ayaka/code/FormulaGuard_240_120/` was not enumerated, hashed, opened,
overlap-checked, or read. The protected one-shot authorization remains unused because
there is no final candidate or complete public prediction lock.
