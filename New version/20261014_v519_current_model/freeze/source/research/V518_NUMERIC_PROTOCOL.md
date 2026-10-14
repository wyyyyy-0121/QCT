# V518 numeric protocol: conditional binary64 enclosures

## Unchanged semantics

The acceptance predicate remains V515 `_satisfaction`: evaluate the original
workbook with simultaneous formula overrides, convert member outputs to float,
call `math.fsum`, then `math.isclose(..., rel_tol=1e-10, abs_tol=1e-8)`.
Fractions below denote the exact rational values of those floats, not intended
decimal values. No rounding to cents, rescaling, new tolerance, or replacement
workbook evaluator is introduced.

## Reviewed implementation and assumptions

Source: https://github.com/python/cpython/blob/v3.11.16/Modules/mathmodule.c
The `math_fsum` section (lines 1340-1555) states IEEE-754, half-even arithmetic
requirements, explains the volatile hi/yr/lo stores preventing excess precision,
and specifies an exact partial expansion followed by correctly rounded collapse.
In particular, after the magnitude swap, FastTwoSum stores rounded x+y and its
exact residual; retaining both preserves the sum. The nonoverlapping expansion
is collapsed until the first inexact addition, with the remaining sign used to
resolve the half-even boundary. This is the implementation guarantee used here,
not a guarantee for every implementation called `fsum`.

The bound path is conditional on that implementation and IEEE binary64 nearest-
even operations with gradual underflow, no fast-math reassociation and no excess
precision. Runtime support is limited to the reviewed CPython 3.11.16 Linux
x86_64 math extension SHA-256
`bc6564c5ecb5fc7363fe917cd76aec5148af2cab7a8c29e7e79e2b6e2a4e97ec`.
Recorded CFLAGS contain no fast-math option. Guards check the version, binary,
float format, current `fegetround()==FE_TONEAREST`, unmodified math callables, and
regression probes. These checks establish the declared deployment boundary;
they are not a formal verification of the compiler or machine hardware.
Any different binary requires separate review and a new rule/approval, otherwise
the algorithm uses exhaustive fallback. Generic documentation warnings about
other-platform double rounding must not be treated as a universal one-ULP bound.

At most 4096 aggregate contributions and sum of maximum absolute values <=2**500
are admitted to the new bound path. This leaves ample distance to intermediate
binary64 overflow in the exact nonoverlapping partial expansion. Nonfinite or
unknown member values invalidate preparation. Other ranges use exhaustive
fallback. Allocation failures are not evidence of infeasibility.

## Independence and complete domain

Use the union reference graph over original and every candidate formula. Each
aggregate member must have no reachable other candidate, including through
unchanged formulas; candidate self-cycles also fail. The existing evaluator has
explicit, deterministic references and unsupported functions are rejected.
Evaluating every individual option therefore gives its value in every joint
assignment under this independence condition. If the condition fails, do not
compose independent deltas or remove candidates: fall back.

## Sum enclosure

For every independent member and every original option retain its exact float
value as a rational. A prefix fixes some choices. Define L as the sum of fixed
contributions and each remaining contribution's minimum; define U analogously
with maxima. For every full assignment below that prefix, its exact sum S obeys
L <= S <= U. The finite option sets still include no-change and every V517 option.

Under the reviewed correctly rounded summation contract, RN(S) lies between
floor_float(L) and ceil_float(U), including subnormal outputs and cancellation.
The endpoint routine checks its direction using exact rational comparison;
it cannot silently accept a conversion on the wrong side. No guessed ULP error
allowance is used. Denote the resulting float interval by [l,h].

## Rounded tolerance enclosure

If target t lies inside [l,h], keep the branch. Otherwise let D be the exact
rational distance from t to the nearer endpoint and M=max(|l|,|h|,|t|).
Let r be the exact rational value of the binary64 constant `1e-10`.

For any possible output a in the interval:

- Exact |a-t| >= D; rounded subtraction followed by abs is at least
  floor_float(D), by monotonicity of IEEE rounding.
- Each rounded relative tolerance, r*|a| or r*|t|, is at most ceil_float(r*M).
- The absolute tolerance is exactly the existing float constant `1e-8`.

Thus if floor_float(D) > max(ceil_float(r*M), 1e-8), every actual predicate is
false. The comparison is strict; equality is retained. This avoids assuming
that a heuristic endpoint call to isclose proves monotonic acceptance under
all rounded intermediate calculations. Nonfinite/overflowing bound conversions
do not prune. Exact equality a==t is already protected by the inside-interval
check. All terminal surviving assignments still run original `_satisfaction`.

## Validation and failure boundary

G1 requires the preceding conditional derivation plus executable checks of
outward rounding, cancellation, subnormals, large/small mixtures, tolerance
neighbors and every completion under each pruned small prefix. Tests compare
against actual math.fsum/isclose; they check the implementation, not replace
the derivation. Different numeric environments must fail the optimization guard.

Proof certificates must bind this rule and runtime identity, and reconstruction
must use the current approved environment. A claimed complete flag, saved bounds,
or source hash alone cannot establish uniqueness. Unknown evaluation, resource
limits, unreviewed environments and unproven dependency structures never justify
a new unique joint action.
