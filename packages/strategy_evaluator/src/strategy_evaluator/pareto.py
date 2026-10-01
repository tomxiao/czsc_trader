from dataclasses import replace
import math

from .models import CandidateProfile


def _dominates(left: CandidateProfile, right: CandidateProfile) -> bool:
    a = dict(left.worst_scores)
    b = dict(right.worst_scores)
    keys = set(a)
    return bool(keys) and all(a[key] >= b[key] for key in keys) and any(a[key] > b[key] for key in keys)


def pareto_layers(profiles: tuple[CandidateProfile, ...]) -> tuple[CandidateProfile, ...]:
    if not isinstance(profiles, tuple) or any(not isinstance(x, CandidateProfile) for x in profiles):
        raise TypeError("pareto_layers requires tuple[CandidateProfile, ...]")
    if len({x.candidate_id for x in profiles}) != len(profiles):
        raise ValueError("duplicate candidate ID")
    expected = None
    for profile in profiles:
        keys = [key for key, _ in profile.worst_scores]
        if not keys or len(set(keys)) != len(keys) or any(not isinstance(key, str) or not key for key in keys):
            raise ValueError("Pareto metrics must be nonempty and unique")
        if any(type(value) not in (float, int) or not math.isfinite(value) for _, value in profile.worst_scores):
            raise ValueError("Pareto metric values must be finite numbers")
        if expected is not None and set(keys) != expected:
            raise ValueError("Pareto metric keys must match exactly")
        expected = set(keys)
    remaining = list(profiles)
    result: list[CandidateProfile] = []
    layer = 1
    while remaining:
        front = [item for item in remaining if not any(_dominates(other, item) for other in remaining if other != item)]
        result.extend(replace(item, pareto_layer=layer) for item in front)
        remaining = [item for item in remaining if item not in front]
        layer += 1
    return tuple(result)
