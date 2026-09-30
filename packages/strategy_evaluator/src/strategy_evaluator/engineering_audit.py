from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .audit_models import (
    AuditFinding,
    AuditStatus,
    ExecutionEvidence,
    StressScenario,
    StressScenarioResult,
)
from .models import (
    CandidateDescriptor,
    CandidateProfile,
    MetricObservation,
    Record,
    TrialRecord,
)


@dataclass(frozen=True)
class StressComparison(Record):
    scenario_id: str
    window_id: str
    metric: str
    standard_advantage: float | None
    stress_advantage: float
    advantage_shrinkage: float | None


@dataclass(frozen=True)
class StressAudit(Record):
    status: AuditStatus
    comparisons: tuple[StressComparison, ...]
    reason_codes: tuple[str, ...] = ()


def _finding(audit_id: str, status: AuditStatus, *reasons: str, **details: object) -> AuditFinding:
    return AuditFinding(audit_id, status, tuple(reasons), tuple(sorted(details.items())))


def audit_execution(evidence: ExecutionEvidence) -> AuditFinding:
    try:
        dates = tuple(date.fromisoformat(value) for value in evidence.dates)
    except ValueError:
        return _finding("execution", AuditStatus.FAIL, "INVALID_EXECUTION_DATE")
    if (
        not dates
        or tuple(sorted(dates)) != dates
        or len(set(dates)) != len(dates)
        or len(dates) != len(evidence.target_positions)
        or len(dates) != len(evidence.factor_scores)
    ):
        return _finding("execution", AuditStatus.FAIL, "INVALID_EXECUTION_INDEX")
    targets = np.asarray(evidence.target_positions, dtype=float)
    scores = np.asarray(evidence.factor_scores, dtype=float)
    if (
        not np.isfinite(targets).all()
        or not np.isfinite(scores).all()
        or np.any(targets < 0.0)
        or np.any(targets > 1.0)
    ):
        return _finding("execution", AuditStatus.FAIL, "INVALID_EXECUTION_VALUES")
    locations = {value: index for index, value in enumerate(evidence.dates)}
    by_id = {event.event_id: event for event in evidence.events if event.event_id}
    if len(by_id) != sum(bool(event.event_id) for event in evidence.events):
        return _finding("execution", AuditStatus.FAIL, "DUPLICATE_EVENT_ID")
    expected_types = {"Buy": ("Entry", "Increase"), "Sell": ("Reduce", "Exit")}
    for order in evidence.orders:
        location = locations.get(order.signal_date, -1)
        if location < 0 or location + 1 >= len(evidence.dates):
            return _finding("execution", AuditStatus.FAIL, "SIGNAL_WITHOUT_NEXT_SESSION")
        if order.execution_date != evidence.dates[location + 1]:
            return _finding("execution", AuditStatus.FAIL, "EXECUTION_NOT_NEXT_SESSION")
        before = 0.0 if location == 0 else float(targets[location - 1])
        after = float(targets[location])
        if order.is_initial:
            if after <= 0.0:
                return _finding("execution", AuditStatus.FAIL, "INVALID_INITIAL_ENTRY")
            continue
        allowed = expected_types.get(order.side)
        if allowed is None:
            return _finding("execution", AuditStatus.FAIL, "INVALID_ORDER_SIDE")
        matches = [
            event
            for event in evidence.events
            if (order.event_id and event.event_id == order.event_id)
            or (
                not order.event_id
                and event.signal_date == order.signal_date
                and event.event_type in allowed
            )
        ]
        if len(matches) != 1:
            return _finding("execution", AuditStatus.FAIL, "ORDER_EVENT_NOT_UNIQUE")
        event = matches[0]
        if event.signal_date != order.signal_date or event.event_type not in allowed:
            return _finding("execution", AuditStatus.FAIL, "ORDER_EVENT_MISMATCH")
        transition_ok = (
            (event.event_type == "Entry" and before == 0.0 and after > 0.0)
            or (event.event_type == "Exit" and before > 0.0 and after == 0.0)
            or (event.event_type == "Reduce" and before > after > 0.0)
            or (event.event_type == "Increase" and 0.0 < before < after)
        )
        if not transition_ok:
            return _finding("execution", AuditStatus.FAIL, "INVALID_POSITION_TRANSITION")
        if abs(event.before_position - before) > 1e-12 or abs(event.after_position - after) > 1e-12:
            return _finding("execution", AuditStatus.FAIL, "EVENT_POSITION_MISMATCH")
        if event.factor_score is not None and abs(event.factor_score - scores[location]) > 1e-12:
            return _finding("execution", AuditStatus.FAIL, "EVENT_SCORE_MISMATCH")
    return _finding(
        "execution",
        AuditStatus.PASS,
        windows_checked=evidence.window_count,
        orders_checked=len(evidence.orders),
        positions_checked=len(evidence.dates),
    )


def _observation_key(item: MetricObservation) -> tuple[str, str, str, str]:
    return item.candidate_id, item.window_id, item.scenario_id, item.measurement_tier


def audit_reproducibility(
    formal: tuple[MetricObservation, ...],
    repeated: tuple[MetricObservation, ...],
    tolerance: float = 1e-12,
) -> AuditFinding:
    if not formal or not repeated:
        return _finding("reproducibility", AuditStatus.INSUFFICIENT, "MISSING_RECOMPUTE")
    expected = {_observation_key(item): item for item in formal}
    actual = {_observation_key(item): item for item in repeated}
    if len(expected) != len(formal) or len(actual) != len(repeated):
        return _finding("reproducibility", AuditStatus.FAIL, "DUPLICATE_RECOMPUTE_KEY")
    if set(expected) != set(actual):
        return _finding("reproducibility", AuditStatus.INSUFFICIENT, "RECOMPUTE_KEY_MISMATCH")
    numeric = (
        "net_cagr",
        "total_return",
        "max_drawdown",
        "calmar",
        "profit_factor",
        "turnover",
        "cost_drag",
    )
    exact = ("calmar_status", "profit_factor_status", "closed_trades")
    for key, left in expected.items():
        right = actual[key]
        for name in numeric:
            first, second = getattr(left, name), getattr(right, name)
            if first is None or second is None:
                if first is not second:
                    return _finding("reproducibility", AuditStatus.FAIL, "RECOMPUTE_VALUE_MISMATCH")
            elif abs(float(first) - float(second)) > tolerance:
                return _finding("reproducibility", AuditStatus.FAIL, "RECOMPUTE_VALUE_MISMATCH")
        if any(getattr(left, name) != getattr(right, name) for name in exact):
            return _finding("reproducibility", AuditStatus.FAIL, "RECOMPUTE_STATUS_MISMATCH")
        left_objectives = dict(left.objective_values)
        right_objectives = dict(right.objective_values)
        if set(left_objectives) != set(right_objectives) or any(
            abs(left_objectives[name] - right_objectives[name]) > tolerance
            for name in left_objectives
        ):
            return _finding("reproducibility", AuditStatus.FAIL, "RECOMPUTE_VALUE_MISMATCH")
    return _finding("reproducibility", AuditStatus.PASS, observations_checked=len(expected))


def audit_trial_ledger(
    champion_id: str,
    candidates: tuple[CandidateDescriptor, ...],
    trials: tuple[TrialRecord, ...],
    profiles: tuple[CandidateProfile, ...],
) -> AuditFinding:
    candidate_by_id = {item.candidate_id: item for item in candidates}
    if len(candidate_by_id) != len(candidates) or champion_id not in candidate_by_id:
        return _finding("trial_ledger", AuditStatus.FAIL, "INVALID_CANDIDATE_IDENTITY")
    trial_ids = {item.candidate_id for item in trials}
    if set(candidate_by_id) - trial_ids:
        return _finding("trial_ledger", AuditStatus.INSUFFICIENT, "INCOMPLETE_TRIAL_LEDGER")
    for trial in trials:
        candidate = candidate_by_id.get(trial.candidate_id)
        if candidate is None or trial.strategy_hash != candidate.candidate_hash:
            return _finding("trial_ledger", AuditStatus.FAIL, "TRIAL_HASH_MISMATCH")
        if candidate.behavior_hash and trial.behavior_hash != candidate.behavior_hash:
            return _finding("trial_ledger", AuditStatus.FAIL, "TRIAL_BEHAVIOR_MISMATCH")
    champion_profiles = [item for item in profiles if item.candidate_id == champion_id]
    if len(champion_profiles) != 1 or not champion_profiles[0].eligible:
        return _finding("trial_ledger", AuditStatus.FAIL, "CHAMPION_NOT_ELIGIBLE")
    return _finding(
        "trial_ledger",
        AuditStatus.PASS,
        candidates_checked=len(candidates),
        trials_checked=len(trials),
    )


def required_stress_scenarios() -> tuple[StressScenario, ...]:
    """Return the fixed total one-way cost scenarios required as audit evidence.

    The 15bp scenario is the default blocking pressure tier.  Higher-cost tiers
    are retained as diagnostics; policy decides which scenario ids are gates.
    """
    return (
        StressScenario("total_cost_15bp", 1.5, 0),
        StressScenario("total_cost_20bp", 2.0, 0),
        StressScenario("total_cost_30bp", 3.0, 0),
        StressScenario("total_cost_50bp", 5.0, 0),
    )


def _metric_value(item: MetricObservation, metric: str) -> float | None:
    value = getattr(item, metric)
    return None if value is None else float(value)


def audit_stress_results(
    champion_id: str,
    incumbent_id: str,
    execution_policy_hash: str,
    standard: tuple[MetricObservation, ...],
    results: tuple[StressScenarioResult, ...],
) -> StressAudit:
    received = {item.scenario_id for item in results}
    current = {item.scenario_id for item in required_stress_scenarios()}
    legacy = {"fee_x2", "slippage_15bp", "slippage_30bp", "slippage_50bp"}
    if not (current <= received or legacy <= received):
        return StressAudit(AuditStatus.INSUFFICIENT, (), ("MISSING_STRESS_SCENARIO",))
    if any(item.execution_policy_hash != execution_policy_hash for item in results):
        return StressAudit(AuditStatus.FAIL, (), ("STRESS_EXECUTION_HASH_MISMATCH",))
    standard_by_key = {(item.candidate_id, item.window_id): item for item in standard}
    rows: list[StressComparison] = []
    metrics = ("net_cagr", "max_drawdown", "calmar", "profit_factor")
    windows = {
        item.window_id for item in standard if item.candidate_id in {champion_id, incumbent_id}
    }
    for result in results:
        by_key = {(item.candidate_id, item.window_id): item for item in result.observations}
        for window in sorted(windows):
            champion = by_key.get((champion_id, window))
            incumbent = by_key.get((incumbent_id, window))
            standard_champion = standard_by_key.get((champion_id, window))
            standard_incumbent = standard_by_key.get((incumbent_id, window))
            if None in (champion, incumbent, standard_champion, standard_incumbent):
                return StressAudit(
                    AuditStatus.INSUFFICIENT, tuple(rows), ("MISSING_STRESS_OBSERVATION",)
                )
            for metric in metrics:
                left, right = _metric_value(champion, metric), _metric_value(incumbent, metric)
                base_left = _metric_value(standard_champion, metric)
                base_right = _metric_value(standard_incumbent, metric)
                if None in (left, right):
                    continue
                stress_advantage = float(left - right)
                standard_advantage = (
                    None if None in (base_left, base_right) else float(base_left - base_right)
                )
                shrinkage = None
                if standard_advantage is not None and standard_advantage > 0.0:
                    shrinkage = 1.0 - stress_advantage / standard_advantage
                rows.append(
                    StressComparison(
                        result.scenario_id,
                        window,
                        metric,
                        standard_advantage,
                        stress_advantage,
                        shrinkage,
                    )
                )
    return StressAudit(AuditStatus.PASS, tuple(rows))
