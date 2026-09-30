from __future__ import annotations

from statistics import median

from .models import (
    CandidateDescriptor,
    CandidateProfile,
    EvaluationProtocol,
    MetricObservation,
    RankingResult,
    ShortlistResult,
)
from .noninferiority import compare_observation
from .pareto import pareto_layers
from .standards import resolve_margins


def _protocol_comparisons(protocol, candidate, incumbent, margins):
    comparisons = compare_observation(candidate, incumbent, margins)
    if candidate.window_id == "full" or candidate.window_id in protocol.target_windows:
        return comparisons
    return tuple(item for item in comparisons if item.metric != "profit_factor")


def screen_candidates(
    protocol: EvaluationProtocol,
    candidates: tuple[CandidateDescriptor, ...],
    observations: tuple[MetricObservation, ...],
) -> ShortlistResult:
    representatives: dict[str, CandidateDescriptor] = {}
    rejected: list[str] = []
    reason_codes: list[str] = []
    for item in sorted((c for c in candidates if not c.is_incumbent), key=lambda x: x.candidate_id):
        behavior = item.behavior_hash or item.candidate_hash
        if behavior in representatives:
            rejected.append(item.candidate_id)
            reason_codes.append("BEHAVIOR_DEDUPLICATED")
        else:
            representatives[behavior] = item
    ranked: list[tuple[float, CandidateDescriptor]] = []
    screening_profiles: list[CandidateProfile] = []
    if observations:
        margins = resolve_margins(protocol)
        by_key = {
            (item.candidate_id, item.window_id): item
            for item in observations
            if item.scenario_id == "standard"
        }
        for item in representatives.values():
            comparisons = []
            for window in protocol.decision_windows:
                candidate = by_key.get((item.candidate_id, window))
                incumbent = by_key.get((protocol.incumbent_id, window))
                if candidate is None or incumbent is None:
                    continue
                comparisons.extend(_protocol_comparisons(protocol, candidate, incumbent, margins))
            expected = sum(
                4 if window == "full" or window in protocol.target_windows else 3
                for window in protocol.decision_windows
            )
            if len(comparisons) != expected or any(not value.passed for value in comparisons):
                rejected.append(item.candidate_id)
                reason_codes.append("SCREENING_NONINFERIORITY")
                continue
            worst = tuple(
                (
                    metric,
                    min(
                        value.normalized_score
                        for value in comparisons
                        if value.metric == metric and value.normalized_score is not None
                    ),
                )
                for metric in ("net_cagr", "max_drawdown", "calmar", "profit_factor")
            )
            score = median(value for _, value in worst)
            ranked.append((score, item))
            screening_profiles.append(
                CandidateProfile(
                    item.candidate_id,
                    True,
                    True,
                    worst,
                    median_score=score,
                    parameter_distance=item.parameter_distance,
                )
            )
    else:
        ranked = [(0.0, item) for item in representatives.values()]
    ranked.sort(key=lambda pair: (-pair[0], pair[1].parameter_distance, pair[1].candidate_id))
    if observations:
        layered = pareto_layers(tuple(screening_profiles))
        first_front = {item.candidate_id for item in layered if item.pareto_layer == 1}
        front = [item for _, item in ranked if item.candidate_id in first_front]
        remainder = [item for _, item in ranked if item.candidate_id not in first_front]
        capacity = max(0, protocol.shortlist_limit - len(front))
        chosen = [*front, *remainder[:capacity]]
        dropped = remainder[capacity:]
    else:
        chosen = [item for _, item in ranked]
        dropped = []
    selected = tuple(item.candidate_id for item in chosen)
    rejected.extend(item.candidate_id for item in dropped)
    if dropped:
        reason_codes.append("SHORTLIST_LIMIT")
    return ShortlistResult(
        selected, tuple(sorted(set(rejected))), tuple(dict.fromkeys(reason_codes))
    )


def _target_achieved(
    protocol: EvaluationProtocol,
    candidate_id: str,
    by_key: dict[tuple[str, str], MetricObservation],
) -> bool:
    if not protocol.target_requirements:
        return True
    for requirement in protocol.target_requirements:
        found = False
        for window in protocol.target_windows:
            candidate = by_key.get((candidate_id, window))
            incumbent = by_key.get((protocol.incumbent_id, window))
            if candidate is None or incumbent is None:
                continue
            candidate_values, incumbent_values = (
                dict(candidate.objective_values),
                dict(incumbent.objective_values),
            )
            if (
                requirement.metric not in candidate_values
                or requirement.metric not in incumbent_values
            ):
                continue
            difference = candidate_values[requirement.metric] - incumbent_values[requirement.metric]
            if requirement.direction == "minimize":
                difference = -difference
            if difference >= requirement.minimum_improvement:
                found = True
        if not found:
            return False
    return True


def _sort_key(profile: CandidateProfile) -> tuple:
    return (
        not profile.eligible,
        not profile.target_achieved,
        profile.pareto_layer or 10**6,
        -profile.median_score,
        profile.turnover if profile.turnover is not None else float("inf"),
        profile.parameter_distance,
        profile.candidate_id,
    )


def rank_candidates(
    protocol: EvaluationProtocol,
    shortlist: ShortlistResult,
    observations: tuple[MetricObservation, ...],
    candidates: tuple[CandidateDescriptor, ...] = (),
) -> RankingResult:
    margins = resolve_margins(protocol)
    by_key = {
        (item.candidate_id, item.window_id): item
        for item in observations
        if item.scenario_id == "standard"
    }
    descriptors = {item.candidate_id: item for item in candidates}
    profiles: list[CandidateProfile] = []
    for candidate_id in shortlist.candidate_ids:
        comparisons = []
        reasons: list[str] = []
        for window in protocol.decision_windows:
            candidate = by_key.get((candidate_id, window))
            incumbent = by_key.get((protocol.incumbent_id, window))
            if candidate is None or incumbent is None:
                reasons.append(f"MISSING_WINDOW_{window.upper()}")
                continue
            comparisons.extend(_protocol_comparisons(protocol, candidate, incumbent, margins))
        for item in comparisons:
            if not item.passed:
                reasons.append(item.reason_code)
        worst = tuple(
            (
                metric,
                min(
                    item.normalized_score
                    for item in comparisons
                    if item.metric == metric and item.normalized_score is not None
                ),
            )
            for metric in ("net_cagr", "max_drawdown", "calmar", "profit_factor")
            if any(
                item.metric == metric and item.normalized_score is not None for item in comparisons
            )
        )
        scores = [value for _, value in worst]
        descriptor = descriptors.get(candidate_id)
        candidate_observations = [
            item for item in observations if item.candidate_id == candidate_id
        ]
        turnover = max(
            (item.turnover for item in candidate_observations if item.turnover is not None),
            default=None,
        )
        profiles.append(
            CandidateProfile(
                candidate_id,
                not reasons and len(worst) == 4,
                _target_achieved(protocol, candidate_id, by_key),
                worst,
                None,
                median(scores) if scores else float("-inf"),
                turnover,
                descriptor.parameter_distance if descriptor else 0.0,
                tuple(reasons),
            )
        )
    eligible = tuple(item for item in profiles if item.eligible and item.target_achieved)
    layered = {item.candidate_id: item for item in pareto_layers(eligible)}
    profiles = [layered.get(item.candidate_id, item) for item in profiles]
    ordered = tuple(sorted(profiles, key=_sort_key))
    viable = [item for item in ordered if item.eligible and item.target_achieved]
    champion = None
    tied: tuple[str, ...] = ()
    if viable:
        best = viable[0]
        equality_key = _sort_key(best)[:-1]
        tied = tuple(item.candidate_id for item in viable if _sort_key(item)[:-1] == equality_key)
        if len(tied) == 1:
            champion = best.candidate_id
    return RankingResult(protocol.incumbent_id, ordered, champion, tied)
