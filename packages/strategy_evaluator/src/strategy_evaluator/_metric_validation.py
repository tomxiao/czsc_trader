"""Typed comparison of recomputed audit metrics."""
from math import isfinite
from numbers import Real


def metric_matches(actual: object, expected: object, tolerance: float) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if isinstance(expected, int):
        return type(actual) is int and actual == expected
    return (
        isinstance(actual, Real) and not isinstance(actual, bool)
        and isfinite(actual) and abs(float(actual) - float(expected)) <= tolerance
    )
