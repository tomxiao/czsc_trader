"""Calmar diagnostics over declared, authenticated account observations."""

from collections import defaultdict
from dataclasses import replace
import math

import numpy as np

from . import research_models as m
from .research_acceptance import _calmar, _calmar_value


def _value(metric, value, reason, sources):
    return m.DiagnosticValue(
        metric, m.MetricUnit.RATIO,
        m.DiagnosticStatus.AVAILABLE if value is not None else m.DiagnosticStatus.INSUFFICIENT_DATA,
        value, None if value is not None else reason, sources,
    )


def _session_curves(evidence):
    sessions = tuple(x.session for x in evidence.account)
    if evidence.equity is None or evidence.equity.drawdown_basis == "SESSION_CLOSE":
        return ({x.session: (x.equity,) for x in evidence.account},
                {day: (value,) for day, value in zip(sessions, evidence.benchmark_equity, strict=True)})
    from .equity_assessment import read_ledger

    curves = []
    for encoded in (evidence.equity.candidate_ledger, evidence.equity.benchmark_ledger):
        grouped = defaultdict(list)
        for point in read_ledger(encoded)["account_points"]:
            grouped[point["session"]].append(point["equity"])
        m.require(tuple(grouped) == sessions, "rolling Calmar observation sessions differ")
        curves.append(grouped)
    return tuple(curves)


def _window_calmar(curve, starting_equity, days):
    if starting_equity <= 0:
        return None
    peak, drawdown = starting_equity, 0.0
    last = starting_equity
    for value in curve:
        last = value
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    try:
        annual = (last / starting_equity) ** (252 / days) - 1
    except OverflowError:
        return None
    return _calmar_value(annual, drawdown)


def rolling_calmar_excess(evidence, protocol):
    metric = m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10
    if evidence is None:
        return _value(metric, None, "MISSING_BASELINE", ())
    sources = (evidence.evaluation_id,)
    if not evidence.benchmark_equity:
        return _value(metric, None, "MISSING_BENCHMARK", sources)
    sessions = tuple(x.session for x in evidence.account)
    size = protocol.rolling_window_days
    starts = range(0, len(sessions) - size + 1, protocol.rolling_step_days)
    if len(starts) < protocol.minimum_rolling_windows:
        return _value(metric, None, "INSUFFICIENT_ROLLING_WINDOWS", sources)
    strategy, benchmark = _session_curves(evidence)
    excess = []
    for start in starts:
        window = sessions[start:start + size]
        initial = evidence.initial_cash if start == 0 else evidence.account[start - 1].equity
        benchmark_initial = evidence.initial_cash if start == 0 else evidence.benchmark_equity[start - 1]
        left = _window_calmar((v for day in window for v in strategy[day]), initial, size)
        right = _window_calmar((v for day in window for v in benchmark[day]), benchmark_initial, size)
        if left is None or right is None or not math.isfinite(left - right):
            return _value(metric, None, "UNAVAILABLE_ROLLING_CALMAR_WINDOW", sources)
        excess.append(left - right)
    with np.errstate(over="ignore", invalid="ignore"):
        quantile = float(np.quantile(excess, .1, method="linear"))
    if not math.isfinite(quantile):
        return _value(metric, None, "UNAVAILABLE_ROLLING_CALMAR_QUANTILE", sources)
    return _value(metric, quantile, None, sources)


def stress_calmar_loss(row):
    metric = m.ResearchMetric.STRESS_CALMAR_LOSS
    baseline = _calmar({x.metric: x for x in row.diagnostics})
    facts, scene = row.stress_performance, row.baseline_scenario
    sources = tuple(dict.fromkeys((*baseline.evaluation_ids,
                                  *((facts.evaluation_id,) if facts is not None else ()))))
    if (facts is None or scene is None or facts.scenario != row.stress_scenario
            or scene.measurement_tier not in {"FORMAL", "SCREENING"}
            or facts.scenario.measurement_tier != "STRESS"
            or facts.scenario.one_way_cost <= scene.one_way_cost
            or replace(facts.scenario, one_way_cost=scene.one_way_cost,
                       measurement_tier=scene.measurement_tier) != scene):
        return _value(metric, None, "MISSING_OR_INCOMPARABLE_STRESS", sources)
    pressure = _calmar_value(facts.annual_return, facts.drawdown)
    loss = None if baseline.value is None or pressure is None else baseline.value - pressure
    if loss is None or not math.isfinite(loss):
        return _value(metric, None, "UNAVAILABLE_STRESS_CALMAR", sources)
    return _value(metric, loss, None, sources)
