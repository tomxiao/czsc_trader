"""Window accounting and fixed-universe selection remain causally separated."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

import strategy_evaluator as se
from strategy_evaluator import research_models as m


def plan(n=122, split=61):
    calendar = tuple((date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(n))
    return se.SelectionWindowPlan(calendar, m.digest(calendar), (
        se.SelectionWindowPair("pair", se.SelectionWindow("selection", calendar[0], calendar[split-1]),
                               se.SelectionWindow("observation", calendar[split], calendar[-1])),), ())


def projection(p, values, source="account", market="CN", basis="BAR_CLOSE", cycles=(), intraday=False):
    suffix = "+08:00" if market == "CN" else "-05:00"
    times = ("10:00:00", "15:00:00") if intraday else ("15:00:00",)
    expected = tuple(se.WindowObservationTime(f"{s}T{t}{suffix}", s) for s in p.calendar for t in times)
    observed = tuple(se.WindowEquityPoint(t.time, t.session, float(v)) for t, v in zip(expected, values))
    return se.EquityWindowProjectionRequest(source, market, "CNY" if market == "CN" else "USD", basis,
                                            100.0, p.calendar[0], observed, cycles, expected, p, 60, 3)


def metrics(fact):
    return {x.metric: x.value for x in fact.diagnostics}


def fact(p, source, window, annual, drawdown=.1):
    w = p.windows[window]
    ds = tuple(m.DiagnosticValue(metric, m.MetricUnit.RATIO,
                               m.DiagnosticStatus.AVAILABLE, value, None, (source,))
               for metric, value in ((m.ResearchMetric.NET_ANNUAL_RETURN, annual),
                                     (m.ResearchMetric.DRAWDOWN_MAGNITUDE, drawdown)))
    return se.AccountWindowFacts(source, w, se.WindowCoverageStatus.COMPLETE, None, 61, 61,
                                 100.0, 110.0, .1, ds, None)


def analysis(values=(.3, .2), targets=None, order=None):
    p = plan()
    sources = tuple(se.SelectionCandidateSource(
        m.AssessmentCandidate(f"S018-C{i+1:04}", str(i+1)*64), f"a{i}", "buyhold", "d"*64,
        m.EvaluationScenarioContext(.001, "FORMAL", "BUYHOLD", "BUYHOLD", "e"*64))
        for i in range(len(values)))
    rule = se.SelectionRule("v1", "f"*64, targets or se.SelectionNoFilter(), order or (
        se.SelectionMetricOrder(m.ResearchMetric.NET_ANNUAL_RETURN, se.SelectionDirection.MAXIMIZE),))
    facts = tuple(fact(p, s.source_id, w, float(v if w == 0 else -.1*i))
                  for i, (s, v) in enumerate(zip(sources, values)) for w in (0, 1)) + (
                      fact(p, "buyhold", 0, .1), fact(p, "buyhold", 1, .1))
    return se.SelectionStabilityRequest(p, rule, sources, facts)


@pytest.mark.risk_cases('SE-21-C01')
def test_SE_21_C01_cn_window_inherits_complete_prior_close():
    _, observation = se.project_equity_windows(projection(plan(4, 2), (110.,120.,90.,130.), market='CN'))
    assert observation.opening_equity == 120.
    assert observation.period_return == pytest.approx(130/120-1)

@pytest.mark.risk_cases('SE-01-C04')
def test_SE_01_C04_cn_us_annualization_uses_252_actual_session_count():
    values = (110.,120.,90.,130.)
    cn = se.project_equity_windows(projection(plan(4,2), values, market='CN'))[1]
    us = se.project_equity_windows(projection(plan(4,2), values, market='US'))[1]
    expected = (130/120)**(252/2)-1
    assert metrics(cn)[m.ResearchMetric.NET_ANNUAL_RETURN] == pytest.approx(expected)
    assert metrics(us)[m.ResearchMetric.NET_ANNUAL_RETURN] == pytest.approx(expected)


@pytest.mark.risk_cases('SE-21-C02')
def test_SE_21_C02_us_utc_timestamp_keeps_market_local_session():
    p = plan(4, 2)
    request = projection(p, (110., 120., 90., 130.), market="US")
    # 00:30 UTC belongs to the preceding New York date. This projection tests
    # date ownership; it makes no claim about regular-session market bars.
    stamps = tuple(f"{(date.fromisoformat(s) + timedelta(days=1)).isoformat()}T00:30:00+00:00"
                   for s in p.calendar)
    request = replace(request,
        observations=tuple(replace(point, time=stamp) for point, stamp in zip(request.observations, stamps, strict=True)),
        expected_points=tuple(replace(point, time=stamp) for point, stamp in zip(request.expected_points, stamps, strict=True)))
    selection, observation = se.project_equity_windows(request)
    assert selection.opening_equity == 100.
    assert observation.opening_equity == 120.
    assert observation.period_return == pytest.approx(130 / 120 - 1)


@pytest.mark.parametrize('days,total', [
    pytest.param(59, 0, id='SE-03-C01'),
    pytest.param(60, 1, id='SE-03-C02'),
    pytest.param(61, 2, id='SE-03-C03'),
])
@pytest.mark.risk_cases('SE-03-C01', 'SE-03-C02', 'SE-03-C03')
def test_frequency_complete_windows_and_exit_attribution(days, total):
    p = plan(days * 2, days)
    cycles = tuple(m.ClosedCycle(str(i), p.calendar[days+i]) for i in (0, 1, 2))
    observation = se.project_equity_windows(projection(p, [100.]*(days*2), cycles=cycles))[1]
    assert observation.frequency_coverage.total_windows == total
    assert observation.frequency_coverage.covered_windows == (1 if total else 0)
    assert metrics(observation)[m.ResearchMetric.FREQUENCY_MEDIAN] == (None if not total else 3. if total == 1 else 2.5)
    assert metrics(observation)[m.ResearchMetric.FREQUENCY_Q10] == (None if not total else 3. if total == 1 else 2.1)
    assert metrics(observation)[m.ResearchMetric.NET_CALMAR] is None


@pytest.mark.risk_cases('SE-21-C05')
def test_missing_later_data_does_not_change_projection_of_selection():
    p = plan(4, 2)
    request = projection(p, (110., 120., 90., 130.))
    full = se.project_equity_windows(request)
    truncated = se.project_equity_windows(replace(request, observations=request.observations[:2]))
    assert full[0] == truncated[0]
    assert truncated[1].status is se.WindowCoverageStatus.INSUFFICIENT_DATA
    assert truncated[1].observed_sessions == 0


@pytest.mark.risk_cases('SE-21-C03')
def test_prior_close_missing_is_not_replaced_by_initial_cash():
    p = plan(4, 2)
    request = projection(p, (110., 120., 90., 130.))
    result = se.project_equity_windows(replace(request, observations=request.observations[2:]))
    assert result[1].reason == "MISSING_PREVIOUS_SESSION_CLOSE"


@pytest.mark.risk_cases('SE-21-C04')
def test_previous_intraday_gap_does_not_invalidate_boundary_close():
    p = plan(4, 2)
    request = projection(p, (105., 110., 80., 120., 60., 90., 100., 130.), intraday=True)
    request = replace(request, observations=tuple(x for i, x in enumerate(request.observations) if i != 2))
    before, after = se.project_equity_windows(request)
    assert before.status is se.WindowCoverageStatus.INSUFFICIENT_DATA
    assert after.status is se.WindowCoverageStatus.COMPLETE
    assert after.opening_equity == 120.
    session = se.project_equity_windows(replace(request, drawdown_basis="SESSION_CLOSE"))
    assert all(f.status is se.WindowCoverageStatus.COMPLETE for f in session)








@pytest.mark.risk_cases('SE-23-C03')
def test_overlapping_windows_are_reported_without_double_counting_exit_rows():
    p = plan(122, 61)
    second = se.SelectionWindowPair("second", se.SelectionWindow("selection2", p.calendar[1], p.calendar[61]),
                                    se.SelectionWindow("observation2", p.calendar[62], p.calendar[-1]))
    p = replace(p, pairs=(*p.pairs, second))
    cycles = tuple(m.ClosedCycle(str(i), p.calendar[i]) for i in (0, 1, 2, 61, 62, 63))
    facts = se.project_equity_windows(projection(p, [100.]*122, cycles=cycles))
    assert len(facts) == 4
    assert facts[0].frequency_coverage.total_windows == 2
    assert facts[2].frequency_coverage.total_windows == 2
    assert metrics(facts[2])[m.ResearchMetric.FREQUENCY_MEDIAN] == 2.


@pytest.mark.risk_cases('SE-22-C05')
def test_exact_ties_and_later_missing_peer_keep_selection_but_block_ranking():
    request = analysis((.3, .3))
    full = se.assess_selection_stability(request)
    assert len(full.decisions[0].selected) == 2
    assert full.observations[0].rank_min == 1
    assert full.observations[1].rank_min == 2
    partial = se.assess_selection_stability(replace(request, facts=tuple(
        f for f in request.facts if not (f.source_id == "a1" and f.window.window_id == "observation"))))
    assert partial.decisions == full.decisions
    assert partial.observations[0].primary_value == 0.
    assert partial.observations[0].rank_reason == "INCOMPLETE_OBSERVATION_REFERENCE"
    assert partial.status is se.SelectionAnalysisStatus.PARTIAL
    assert se.SelectionStabilityResult.from_dict(partial.to_dict()) == partial
    assert se.SelectionStabilityRequest.from_dict(request.to_dict()) == request


@pytest.mark.risk_cases('SE-23-C02')
def test_bins_keep_all_ties_without_id_tiebreak():
    order = (se.SelectionMetricOrder(m.ResearchMetric.NET_ANNUAL_RETURN, se.SelectionDirection.MAXIMIZE,
             m.MetricBinSpec(m.ResearchMetric.NET_ANNUAL_RETURN, .1, 0., m.BinRounding.FLOOR)),)
    result = se.assess_selection_stability(analysis((.31, .39), order=order))
    assert len(result.decisions[0].selected) == 2


@pytest.mark.risk_cases('SE-23-C01')
def test_observation_tie_interval_and_input_order_invariance():
    request = analysis((.3, .3))
    facts = tuple(replace(f, diagnostics=tuple(replace(d, value=0.)
        if d.metric is m.ResearchMetric.NET_ANNUAL_RETURN else d for d in f.diagnostics))
        if f.window.window_id == "observation" and f.source_id != "buyhold" else f for f in request.facts)
    request = replace(request, facts=facts)
    result = se.assess_selection_stability(request)
    assert [(o.rank_min, o.rank_max) for o in result.observations] == [(1, 2), (1, 2)]
    reversed_result = se.assess_selection_stability(replace(request, sources=tuple(reversed(request.sources)),
                                                          facts=tuple(reversed(request.facts))))
    assert reversed_result.decisions == result.decisions
    assert reversed_result.observations == result.observations


@pytest.mark.parametrize('covered,expected', [
    pytest.param(15, se.SelectionStatus.NO_ELIGIBLE_CANDIDATE, id='SE-03-C06'),
    pytest.param(16, se.SelectionStatus.SELECTED, id='SE-03-C05'),
])
@pytest.mark.risk_cases('SE-03-C05', 'SE-03-C06')
def test_frequency_coverage_uses_exact_inclusive_integer_gate(covered, expected):
    request = analysis(targets=m.ResearchTargets((m.FrequencyCoverageTarget("freq", 60, 3, 4, 5),), 60))
    facts = tuple(replace(f, frequency_coverage=m.FrequencyCoverageFacts(60, 3, 20, covered, (f.source_id,)))
                  for f in request.facts)
    assert se.assess_selection_stability(replace(request, facts=facts)).decisions[0].status is expected




@pytest.mark.risk_cases('SE-22-C01')
def test_missing_potential_winner_prevents_partial_universe_selection():
    request = analysis()
    request = replace(request, facts=tuple(f for f in request.facts if not (
        f.source_id == "a1" and f.window.window_id == "selection")))
    decision = se.assess_selection_stability(request).decisions[0]
    assert decision.status is se.SelectionStatus.INSUFFICIENT_SELECTION_EVIDENCE
    assert not decision.selected


@pytest.mark.risk_cases('SE-22-C02')
def test_known_hard_failure_overrides_missing_unneeded_ordering():
    targets = m.ResearchTargets((m.ResearchTarget("dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                                                upper=m.ConstantBound(.2, True)),), 60)
    request = analysis(targets=targets)
    altered = tuple(replace(f, diagnostics=tuple(replace(x, value=.4) for x in f.diagnostics
                    if x.metric is m.ResearchMetric.DRAWDOWN_MAGNITUDE))
                    if f.source_id == "a1" and f.window.window_id == "selection" else f for f in request.facts)
    result = se.assess_selection_stability(replace(request, facts=altered))
    assert result.decisions[0].status is se.SelectionStatus.SELECTED
    assert result.decisions[0].checks[1].status is m.TargetCheckStatus.FAILED
    assert result.observations[0].rank_reason == "SINGLE_ELIGIBLE_CANDIDATE"


@pytest.mark.parametrize('minimum,eligible', [
    pytest.param(.4, False, id='SE-22-C03'),
    pytest.param(.1, True, id='SE-22-C04'),
])
@pytest.mark.risk_cases('SE-22-C03','SE-22-C04')
def test_selection_eligibility_and_observation_competitor_set(minimum, eligible):
    targets = m.ResearchTargets((m.ResearchTarget('positive', m.ResearchMetric.NET_ANNUAL_RETURN,
        lower=m.ConstantBound(minimum, True)),),60)
    result = se.assess_selection_stability(analysis(targets=targets))
    if not eligible:
        assert result.no_eligible_windows == 1
        assert result.insufficient_selection_windows == 0
        assert not result.observations
    else:
        assert result.observations[0].acceptance_status is m.TargetCheckStatus.FAILED
        assert result.observations[0].reference_size == 2
        assert result.observations[0].rank_min == 1




@pytest.mark.risk_cases('SE-23-C04')
def test_SE_23_C04_calendar_digest_mismatch_rejects_plan():
    with pytest.raises(se.ValidationError, match='calendar digest'):
        replace(plan(), calendar_sha256='0'*64)
