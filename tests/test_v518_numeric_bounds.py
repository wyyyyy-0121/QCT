import math
import random
from fractions import Fraction
from itertools import product

import pytest

from formulaguard.v518_numeric_bounds import (
    MAX_MAGNITUDE,
    NumericBound,
    excludes_output_interval,
    make_bound,
    outward,
    runtime_identity,
    runtime_supported,
)


def test_reviewed_runtime_and_unsupported_environment(monkeypatch):
    assert runtime_supported()
    from formulaguard import v518_numeric_bounds as module
    identity = runtime_identity()
    monkeypatch.setattr(module, "runtime_identity", lambda: {**identity, "math_sha256": "unknown"})
    assert not runtime_supported()


@pytest.mark.parametrize("value", [Fraction(1, 10), Fraction(-1, 10), Fraction(1, 3), Fraction(1, 2**1075),
                                  Fraction(-1, 2**1075), Fraction(0), Fraction(2**500) + Fraction(1, 10)])
def test_outward_endpoints_enclose_exact_rational(value):
    assert Fraction.from_float(outward(value, upper=False)) <= value <= Fraction.from_float(outward(value, upper=True))


@pytest.mark.parametrize("seed", range(12))
def test_every_pruned_prefix_excludes_every_actual_fsum_completion(seed):
    rng = random.Random(seed)
    pool = [0.1, -0.1, 1/3, -1/3, 1e-8, -1e-8, 1e10, -1e10, 0.0,
            math.ulp(0.0), -math.ulp(0.0), 1e-200, -1e-200, 1.0000000001]
    fixed = tuple(rng.choice(pool) for _ in range(3))
    choices = tuple(tuple(rng.choice(pool) for _ in range(3)) for _ in range(4))
    actual = {a: math.fsum([*fixed, *(choices[i][v] for i, v in enumerate(a))]) for a in product(range(3), repeat=4)}
    sample = actual[(0, 1, 2, 0)]
    targets = [sample, math.nextafter(sample, math.inf), math.nextafter(sample, -math.inf), sample+1e-8, sample-1e-8, 42.123]
    for target in targets:
        bound = make_bound(fixed, choices, target)
        for depth in range(5):
            for prefix in product(range(3), repeat=depth):
                low, high = bound.interval(prefix)
                compatible = [value for a, value in actual.items() if a[:depth] == prefix]
                assert all(low <= value <= high for value in compatible)
                if bound.excludes(prefix):
                    assert not any(math.isclose(value, target, rel_tol=1e-10, abs_tol=1e-8) for value in compatible)


@pytest.mark.parametrize("target", [0.0, -0.0, 1e-8, -1e-8, 1.0, -1.0, 1e10, -1e10, 1e100, -1e100])
def test_isclose_boundary_never_falsely_excluded(target):
    tolerance = max(1e-8, 1e-10*abs(target))
    for value in (target, target+tolerance, target-tolerance):
        for adjacent in (value, math.nextafter(value, math.inf), math.nextafter(value, -math.inf)):
            if math.isclose(adjacent, target, rel_tol=1e-10, abs_tol=1e-8):
                assert not excludes_output_interval(adjacent, adjacent, target)


def test_unsafe_magnitude_and_nonfinite_inputs_rejected():
    with pytest.raises(ValueError):
        NumericBound(Fraction(), ((Fraction(1),),), 0.0, 1, MAX_MAGNITUDE * 2)
    with pytest.raises(ValueError):
        make_bound([math.nan], (), 0.0)
    assert not excludes_output_interval(-math.inf, math.inf, 1.0)
    assert not excludes_output_interval(2.0, 1.0, 0.0)
