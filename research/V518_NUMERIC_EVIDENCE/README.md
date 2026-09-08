# Numeric implementation provenance

Downloaded upstream sources (unmodified):

- `cpython-3.11.16-mathmodule.c`:
  https://raw.githubusercontent.com/python/cpython/v3.11.16/Modules/mathmodule.c
  SHA-256 `8609ea53918cc5d5523b4ec2d6445e9054af4cf22eb38c655596ca512d14393c`.
- `CPYTHON_LICENSE`:
  https://raw.githubusercontent.com/python/cpython/v3.11.16/LICENSE

Relevant sections are the precision summation implementation at lines 1340-1555
and `math_isclose_impl` at lines 3009-3048. Source comments explicitly state the
IEEE/half-even assumptions, exact partial expansion and rounded collapse; the
isclose source shows the rounded difference and two relative comparisons.

Reviewed local runtime: CPython 3.11.16, conda-forge, GCC 14.4.0, Linux x86_64,
binary64 (radix 2, mantissa 53, max_exp 1024), current fegetround() == 0.
math extension SHA-256:
`bc6564c5ecb5fc7363fe917cd76aec5148af2cab7a8c29e7e79e2b6e2a4e97ec`.
Reported CFLAGS contain -O2, -fwrapv, -fPIC and -fno-merge-constants, with no
fast-math switch. The numeric path is conditional on the implementation contract
and declared IEEE environment; source inspection and regression probes do not
formally verify the compiler or hardware. Unreviewed binaries use fallback.

For the intermediate-overflow precondition, let u=2^-53, eta=2^-1074 and M be
the initial absolute input sum. Each error-free pair replacing x,y by hi,lo has
new absolute norm at most (1+2u)(|x|+|y|)+eta. There are at most n^2 pair steps.
For n<=4096, the geometric growth factor is less than 2, and accumulated
subnormal terms are less than 1. Consequently every intermediate norm is below
2M+1, far below binary64 overflow when M<=2^500. This supports the conservative
domain restriction used with the exact-partial implementation. A new platform
must re-establish the error-free transform assumptions before enabling bounds.
