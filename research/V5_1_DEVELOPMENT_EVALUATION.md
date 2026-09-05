# V5.1-development disclosed development evaluation

This is a development diagnostic on the already disclosed Structural Guard
fresh cohort. It is not a new blind result and must not be used as confirmation
evidence.

## Result

On 180 repair-required workbooks (2,190 error cells), V5.1-development produced:

| Metric | Development result |
| --- | ---: |
| Repair-case macro AP | 100.00% |
| Exact candidate repair coverage | 100.00% |
| Candidate location precision | 100.00% |
| Accepted-group exact coverage | 100.00% |
| Accepted-group precision | 100.00% |
| Control workbook candidate rate | 0.00% |
| Ambiguous workbook candidate rate | 0.00% |
| Unsafe accepted groups | 0 |

The result is intentionally treated as a development pass only. The cohort is
generated from one regular tabular family, and V5.1 explicitly contains
semantic reconstruction rules for the same revenue/margin roles used by that
generator. A perfect development score therefore demonstrates that the new
pipeline can recover the declared failure modes; it does not establish
performance on naturally occurring or structurally novel workbooks.

## What changed from V5-R2

V5.1 is a separate module, `formulaguard.v5_1_development`, and leaves the
frozen R2 file untouched. Its pipeline is:

1. workbook-level anomaly gate;
2. robust per-column template consensus;
3. semantic candidate synthesis for product and difference roles;
4. contiguous-region consensus and propagation;
5. strict singleton evidence requirements;
6. explicit abstention for low-support or tied templates.

The stable API exposes it as `v5.1-development`, `v5_1_development`, or
`formulaguard_v5_1_development`.

## Required next validation

Before calling this model stronger, freeze the V5.1 source, parameters, scorer,
and thresholds; generate a new cohort with multiple workbook families,
multi-sheet references, legal exceptions, hidden/merged regions, and natural
formula functions; then run a fresh PUBLIC/SECRET blind comparison. The
absolute safety gates should remain primary: control workbook candidate rate at
most 5–10%, zero unsafe accepted groups, accepted-group precision at least 95%,
and meaningful block/systematic repair coverage.

