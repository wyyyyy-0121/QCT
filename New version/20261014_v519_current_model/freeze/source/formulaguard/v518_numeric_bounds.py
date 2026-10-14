"""Outward enclosures for the approved CPython binary64 summation environment.

Fractions represent the actual floats, not their intended decimal values. See
research/V518_NUMERIC_PROTOCOL.md for the conditional proof and runtime boundary.
"""

from __future__ import annotations

import ctypes
import hashlib
import math
import platform
import sys
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

RULE_VERSION = "v518-binary64-enclosure-1"
APPROVED_MATH_SHA256 = "bc6564c5ecb5fc7363fe917cd76aec5148af2cab7a8c29e7e79e2b6e2a4e97ec"
MAX_MAGNITUDE = Fraction(2**500)
MAX_MEMBERS = 4096
REL_TOL = Fraction.from_float(1e-10)
ABS_TOL = 1e-8
_FSUM, _ISCLOSE = math.fsum, math.isclose


@lru_cache(maxsize=1)
def runtime_identity():
    return {"implementation": sys.implementation.name, "version": platform.python_version(),
            "machine": platform.machine(), "platform": sys.platform,
            "math_sha256": hashlib.sha256(Path(math.__file__).read_bytes()).hexdigest(),
            "radix": sys.float_info.radix, "mant_dig": sys.float_info.mant_dig,
            "max_exp": sys.float_info.max_exp, "rule": RULE_VERSION}


def runtime_supported():
    try:
        identity = runtime_identity()
        return (identity["implementation"] == "cpython" and identity["version"] == "3.11.16"
                and identity["platform"] == "linux" and identity["machine"] == "x86_64"
                and identity["math_sha256"] == APPROVED_MATH_SHA256
                and (identity["radix"], identity["mant_dig"], identity["max_exp"]) == (2, 53, 1024)
                and ctypes.CDLL(None).fegetround() == 0
                and math.fsum is _FSUM and math.isclose is _ISCLOSE
                and math.fsum([1e16, 1.0, 1e-16]) == 10000000000000002.0
                and math.fsum([1e16, 1.0, -1e16]) == 1.0)
    except (OSError, AttributeError, ValueError):
        return False


def outward(value: Fraction, *, upper: bool) -> float:
    """Return a finite float on the requested side, checking the side exactly."""
    rounded = float(value)
    if not math.isfinite(rounded):
        raise ValueError("nonfinite enclosure")
    represented = Fraction.from_float(rounded)
    if (upper and represented < value) or (not upper and represented > value):
        rounded = math.nextafter(rounded, math.inf if upper else -math.inf)
    if not math.isfinite(rounded):
        raise ValueError("nonfinite outward endpoint")
    represented = Fraction.from_float(rounded)
    if (upper and represented < value) or (not upper and represented > value):
        raise ValueError("float conversion violates enclosure precondition")
    return rounded


def excludes_output_interval(low: float, high: float, total: float) -> bool:
    """Disprove isclose for the whole interval, including its rounded operations."""
    if not all(math.isfinite(v) for v in (low, high, total)) or low > high:
        return False
    if low <= total <= high:
        return False
    target = Fraction.from_float(total)
    distance = Fraction.from_float(low) - target if low > total else target - Fraction.from_float(high)
    largest = max(abs(Fraction.from_float(v)) for v in (low, high, total))
    try:
        # For any result in the interval, rounded subtraction is at least this
        # lower endpoint and both rounded relative tolerances are at most upper.
        distance_lower = outward(distance, upper=False)
        tolerance_upper = max(ABS_TOL, outward(REL_TOL * largest, upper=True))
    except (ValueError, OverflowError):
        return False
    return distance_lower > tolerance_upper


@dataclass(frozen=True)
class NumericBound:
    constant: Fraction
    contributions: tuple[tuple[Fraction, ...], ...]
    total: float
    member_count: int
    magnitude: Fraction

    def __post_init__(self):
        if not 1 <= self.member_count <= MAX_MEMBERS or not 0 <= self.magnitude <= MAX_MAGNITUDE:
            raise ValueError("numeric enclosure outside reviewed domain")
        if not math.isfinite(self.total) or any(not row for row in self.contributions):
            raise ValueError("invalid numeric bound")

    def interval(self, prefix):
        fixed = self.constant + sum((self.contributions[i][v] for i, v in enumerate(prefix)), Fraction())
        remaining = self.contributions[len(prefix):]
        low = fixed + sum((min(values) for values in remaining), Fraction())
        high = fixed + sum((max(values) for values in remaining), Fraction())
        return outward(low, upper=False), outward(high, upper=True)

    def excludes(self, prefix):
        low, high = self.interval(prefix)
        return excludes_output_interval(low, high, self.total)


def make_bound(fixed, contributions, total):
    fixed = tuple(Fraction.from_float(float(v)) for v in fixed)
    contributions = tuple(tuple(Fraction.from_float(float(v)) for v in values) for values in contributions)
    magnitude = sum(map(abs, fixed), Fraction()) + sum((max(map(abs, row)) for row in contributions), Fraction())
    return NumericBound(sum(fixed, Fraction()), contributions, float(total), len(fixed) + len(contributions), magnitude)
