"""Explicit Calmar self-check mathematics, unavailable data, and version isolation."""

from dataclasses import fields, replace
from datetime import date, timedelta

import numpy as np
import pytest

import strategy_evaluator as se
from strategy_evaluator import research_models as m
from test_calmar_ranking import assessed, request as ranking_request
from test_equity_assessment import evidence as equity_evidence
from test_research_assessment import candidate, evidence


def protocol(window=3, step=2, minimum=1):
    return se.CalmarSelfCheckProtocol(
        "calmar-test", "full", "standard", "pressure", window, step,
        m.QuantileMethod.LINEAR, minimum, 8, 2, 17, 1e-8,
        se.ParameterNeighborhoodProtocol(), pbo_blocks=2,
    )


def ordinary(values, benchmark):
    base = evidence()
    sessions = tuple((date(2024, 1, 2) + timedelta(days=i)).isoformat() for i in range(len(values)))
    account = tuple(m.AccountPoint(day, value if i == len(values) - 1 else 0.0,
        0 if i == len(values) - 1 else 1, value, value) for i, (day, value) in enumerate(zip(sessions, values)))
    return replace(base, account=account, benchmark_equity=tuple(benchmark),
        fills=(m.AssessmentFill("cycle", sessions[0], m.FillSide.BUY, 1, 1000.0, 0.0),
               m.AssessmentFill("cycle", sessions[-1], m.FillSide.SELL, 1, values[-1], 0.0)),
        closed_cycles=(m.ClosedCycle("cycle", sessions[-1]),))


def panel(value, selected=None):
    return se.assess_candidates(m.CandidateAssessmentRequest(
        (value.candidate,), selected or protocol(), (), (value,),
    ))


def window_calmar(values, initial, window):
    wealth = np.r_[initial, values]
    drawdown = max(1 - wealth / np.maximum.accumulate(wealth))
    return ((values[-1] / initial) ** (252 / window) - 1) / drawdown


def v6(req, rolling=(0.0, 0.0), stress=((.18, .2), (.15, .05))):
    rows = []
    for item, value, pressure in zip(req.panel.rows, rolling, stress):
        diagnostic = m.DiagnosticValue(m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10, m.MetricUnit.RATIO,
                                      m.DiagnosticStatus.AVAILABLE, value, None, ())
        facts = m.PerformanceFacts(item.candidate, "f" * 64, item.stress_scenario,
                                   *pressure, .1, .1)
        rows.append(replace(item, rolling_calmar_excess_q10=diagnostic, stress_performance=facts))
    replacements = {
        m.ResearchMetric.ROLLING_EXCESS_Q10: m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10,
        m.ResearchMetric.STRESS_ANNUAL_LOSS: m.ResearchMetric.STRESS_CALMAR_LOSS,
    }
    return replace(req, panel=replace(req.panel, rows=tuple(rows), formula_version="research-assessment-v8"),
                   policy=replace(req.policy, formula_version="research-ranking-v6", bins=tuple(
                       replace(x, metric=replacements.get(x.metric, x.metric)) for x in req.policy.bins)))


def test_rolling_calmar_uses_prior_window_equity_resets_peak_and_linear_all_window_quantile():
    strategy = (1200., 1100., 1110., 1105., 1112., 1108.)
    benchmark = (1100., 1050., 1060., 1055., 1062., 1058.)
    result = panel(ordinary(strategy, benchmark))
    values = []
    for start in (0, 2):
        a = 1000. if start == 0 else strategy[start - 1]
        b = 1000. if start == 0 else benchmark[start - 1]
        values.append(window_calmar(strategy[start:start + 3], a, 3)
                      - window_calmar(benchmark[start:start + 3], b, 3))
    got = result.rows[0].rolling_calmar_excess_q10
    assert got.status is m.DiagnosticStatus.AVAILABLE
    assert got.value == pytest.approx(np.quantile(values, .1, method="linear"))
    assert got.evaluation_ids == (evidence().evaluation_id,)
    assert result.formula_version == "research-assessment-v8"
    assert m.AssessmentPanel.from_dict(result.to_dict()) == result
    assert len(result.rows[0].diagnostics) == 14
    assert len(values) == 2


def test_bar_close_rolling_uses_all_intraday_points_and_never_silently_daily_drawdown():
    daily = equity_evidence("SESSION_CLOSE", days=3)
    bar = replace(daily, equity=replace(daily.equity, drawdown_basis="BAR_CLOSE"),
                  metric_version="equity-assessment-v4:BAR_CLOSE:MAX_SINGLE")
    daily_value = panel(daily, protocol(2, 1)).rows[0].rolling_calmar_excess_q10
    bar_value = panel(bar, protocol(2, 1)).rows[0].rolling_calmar_excess_q10
    assert daily_value.value is None and daily_value.reason == "UNAVAILABLE_ROLLING_CALMAR_WINDOW"
    assert bar_value.status is m.DiagnosticStatus.AVAILABLE
    assert bar_value.value == 0.0  # Same journals; each has nonzero intraday drawdown.


@pytest.mark.parametrize("changes", ["benchmark", "strategy"])
def test_unavailable_rolling_window_is_not_dropped(changes):
    strategy = (1000., 990., 1010., 1005., 1012.)
    benchmark = (1000., 995., 1005., 1000., 1007.)
    if changes == "strategy":
        strategy = (1000., 990., 1010., 1020., 1030.)
    else:
        benchmark = (1000., 995., 1005., 1010., 1020.)
    got = panel(ordinary(strategy, benchmark), protocol(3, 2)).rows[0].rolling_calmar_excess_q10
    assert got.status is m.DiagnosticStatus.INSUFFICIENT_DATA
    assert got.reason == "UNAVAILABLE_ROLLING_CALMAR_WINDOW"


@pytest.mark.parametrize("days,minimum", [(2, 1), (5, 3)])
def test_insufficient_complete_windows_has_no_partial_quantile(days, minimum):
    value = ordinary((1000., 990., 1010., 1005., 1015.)[:days], (1000., 995., 1005., 1000., 1010.)[:days])
    got = panel(value, protocol(3, 2, minimum)).rows[0].rolling_calmar_excess_q10
    assert got.value is None and got.reason == "INSUFFICIENT_ROLLING_WINDOWS"


def test_explicit_calmar_protocol_preserves_legacy_panel_bytes_and_rejects_relabeling():
    value = ordinary((1000., 990., 1010.), (1000., 995., 1005.))
    modern = protocol()
    old = se.NeighborhoodSelfCheckProtocol(**{f.name: getattr(modern, f.name) for f in fields(modern)})
    legacy = panel(value, old)
    assert legacy.formula_version == "research-assessment-v7"
    assert legacy.rows[0].rolling_calmar_excess_q10 is None
    assert "rolling_calmar_excess_q10" not in legacy.to_dict()["rows"][0]
    assert m.AssessmentPanel.from_dict(legacy.to_dict()).sha256 == legacy.sha256
    current = panel(value, modern)
    with pytest.raises(ValueError, match="field differs"):
        replace(current, formula_version="research-assessment-v7")
    with pytest.raises(ValueError, match="field differs"):
        replace(legacy, formula_version="research-assessment-v8")
    with pytest.raises(ValueError, match="metric differs"):
        replace(current.rows[0], rolling_calmar_excess_q10=next(
            x for x in legacy.rows[0].diagnostics if x.metric is m.ResearchMetric.ROLLING_EXCESS_Q10))
    request = m.CandidateAssessmentRequest((value.candidate,), modern, (), (value,))
    assert m.CandidateAssessmentRequest.from_dict(request.to_dict()) == request


@pytest.mark.parametrize("inclusive,expected", [(True, "PASSED"), (False, "FAILED")])
@pytest.mark.parametrize("where", ["pressure", "parameter"])
def test_explicit_calmar_bounds_apply_at_parameter_and_pressure_boundaries(where, inclusive, expected):
    item, geometry = assessed(candidate(), point_values=((.15, 1.0),) * 8)
    target = m.ResearchTarget("explicit", m.ResearchMetric.NET_CALMAR, lower=m.BenchmarkBound(1.5, inclusive))
    if where == "pressure":
        target = replace(target, scope=m.TargetScope.STRESS, one_way_cost=.001)
        item = replace(item, stress_performance=m.PerformanceFacts(item.candidate, "f" * 64,
                       item.stress_scenario, .15, 1., .1, 1.))
    else:
        item = replace(item, parameter_performances=tuple(replace(x, benchmark_drawdown=1.) for x in item.parameter_performances))
        target = m.ParameterNeighborhoodTarget("parameter", 1, 1, (target,), (
            m.ResearchTarget("cap", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(1., True)),))
    req = ranking_request((item, geometry))
    checked = se.compare_candidates(replace(req, targets=m.ResearchTargets((target,), 60))).rows[0].target_checks[0]
    assert checked.status.value == expected


@pytest.mark.parametrize("base,annual,dd,multiple", [(0., .01, .1, 1.7), (-.1, -.1, .1, 1.25), (.1, .05, .025, 1.3)])
@pytest.mark.parametrize("where", ["parameter", "pressure"])
def test_calmar_target_has_no_implicit_absolute_or_relative_return_gate(base, annual, dd, multiple, where):
    item, geometry = assessed(candidate(), point_values=((annual, dd),) * 8)
    item = replace(item, parameter_performances=tuple(replace(x, benchmark_return=base) for x in item.parameter_performances))
    atom = m.ResearchTarget("calmar", m.ResearchMetric.NET_CALMAR, lower=m.BenchmarkBound(multiple, True))
    if where == "pressure":
        item = replace(item, stress_performance=m.PerformanceFacts(item.candidate, "f" * 64,
            item.stress_scenario, annual, dd, base, .1))
        goal = replace(atom, scope=m.TargetScope.STRESS, one_way_cost=.001)
    else:
        goal = m.ParameterNeighborhoodTarget("parameter", 1, 1, (atom,), (
            m.ResearchTarget("risk", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(.25, True)),))
    req = replace(ranking_request((item, geometry)), targets=m.ResearchTargets((goal,), 60))
    assert se.compare_candidates(req).rows[0].target_checks[0].status is m.TargetCheckStatus.PASSED


@pytest.mark.parametrize("dd", [0., 1e-12])
def test_unavailable_calmar_pressure_and_parameter_targets_stay_indeterminate(dd):
    item, geometry = assessed(candidate(), point_values=((.2, dd),) * 8)
    item = replace(item, stress_performance=m.PerformanceFacts(item.candidate, "f" * 64, item.stress_scenario,
                                                              .2, dd, .1, .1))
    req = ranking_request((item, geometry))
    goals = (m.ResearchTarget("stress", m.ResearchMetric.NET_CALMAR, lower=m.ConstantBound(0., False),
                              scope=m.TargetScope.STRESS),
             m.ParameterNeighborhoodTarget("points", 1, 1, (
                 m.ResearchTarget("point", m.ResearchMetric.NET_CALMAR, lower=m.ConstantBound(0., False)),
             ), (m.ResearchTarget("risk", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(.25, True)),)))
    checked = se.compare_candidates(replace(req, targets=m.ResearchTargets(goals, 60))).rows[0].target_checks
    assert all(x.status is m.TargetCheckStatus.INDETERMINATE for x in checked)


def test_v6_rolling_calmar_priority_reverses_legacy_return_excess_priority():
    req = ranking_request(assessed(candidate()), assessed(candidate("C0002", "b")))
    rows = tuple(replace(item, diagnostics=tuple(replace(x, value=value) if x.metric is m.ResearchMetric.ROLLING_EXCESS_Q10
                       else x for x in item.diagnostics)) for item, value in zip(req.panel.rows, (.5, .1)))
    req = replace(req, panel=replace(req.panel, rows=rows))
    assert se.compare_candidates(req).rows[0].candidate == req.candidates[0]
    current = v6(req, (.1, .5))
    result = se.compare_candidates(current)
    assert result.rows[0].candidate == req.candidates[1]
    assert result.pairs[0].decisive_metric is m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10
    assert se.CalmarComparisonRequest.from_dict(current.to_dict()) == current


def test_v6_signed_stress_calmar_loss_reverses_annual_loss_priority():
    req = ranking_request(assessed(candidate()), assessed(candidate("C0002", "b")))
    rows = tuple(replace(item, diagnostics=tuple(replace(x, value=value) if x.metric is m.ResearchMetric.STRESS_ANNUAL_LOSS
                       else x for x in item.diagnostics)) for item, value in zip(req.panel.rows, (.02, .05)))
    req = replace(req, panel=replace(req.panel, rows=rows))
    assert se.compare_candidates(req).rows[0].candidate == req.candidates[0]
    result = se.compare_candidates(v6(req))
    assert result.rows[0].candidate == req.candidates[1]
    assert result.pairs[0].decisive_metric is m.ResearchMetric.STRESS_CALMAR_LOSS
    assert result.rows[0].bin_values[3] == -10000  # Pressure Calmar 3 exceeds standard Calmar 2.


@pytest.mark.parametrize("field,value", [("one_way_cost", .0005), ("measurement_tier", "FORMAL"), ("benchmark_id", "other")])
def test_v6_incompatible_stress_is_not_a_numeric_calmar_loss(field, value):
    current = v6(ranking_request(assessed(candidate())), rolling=(0.,), stress=((.1, .1),))
    item = current.panel.rows[0]
    scene = replace(item.stress_scenario, **{field: value})
    item = replace(item, stress_scenario=scene, stress_performance=replace(item.stress_performance, scenario=scene))
    current = replace(current, panel=replace(current.panel, rows=(item,)))
    result = se.compare_candidates(current).rows[0]
    assert result.status is m.ComparisonStatus.INCOMPARABLE
    assert result.bin_values[3] is None


@pytest.mark.parametrize("annual,dd", [(.1, 0.), (.1, 1e-12), (1e308, .01)])
def test_v6_unavailable_stress_calmar_has_no_numeric_loss(annual, dd):
    current = v6(ranking_request(assessed(candidate())), rolling=(0.,), stress=((annual, dd),))
    result = se.compare_candidates(current).rows[0]
    assert result.bin_values[3] is None
    assert result.status is m.ComparisonStatus.INCOMPARABLE


def test_v6_rejects_v7_panel_or_v5_bins_and_cannot_relabel_old_results():
    req = ranking_request(assessed(candidate()))
    current = v6(req, rolling=(0.,), stress=((.1, .1),))
    with pytest.raises(ValueError, match="pair"):
        replace(current, panel=req.panel)
    with pytest.raises(ValueError, match="ranking bins differ"):
        replace(current.policy, bins=req.policy.bins)
    with pytest.raises(ValueError, match="pair"):
        replace(current, policy=req.policy)
