"""Declared auxiliary/session inputs: causal slicing, identity and isolation."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import pandas as pd
import pytest
from dataflows import BarFrequency, TimeInterval, TradingSession
from strategy_runtime import StrategyRuntime
from packages.strategy_runtime.tests.context_fixture_support import (
    make_candidate,
    fixture,
    build,
)


def test_SRT_15_C03_public_plan_context_causal_slice_halfday_and_isolation(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    context = build(value, data)
    assert len(context.auxiliary_histories["market"]) == 2
    assert context.session.segments[-1].end.hour == 18
    assert context.session_available_at == data[3].AvailableDate.iloc[0].to_pydatetime()
    with pytest.raises(TypeError):
        context.auxiliary_histories["new"] = data[1]
    first = value.decide(context)
    second = value.decide(context)
    assert first == second
    assert context.auxiliary_histories["market"].Close.iloc[-1] == 11.0
    assert data[1].Close.tolist() == [10.0, 11.0, 10.0]
    with pytest.raises(ValueError, match="V5 DFLS step contract"):
        StrategyRuntime(execution_spec=value.definition.execution_spec).create(value)


def test_SRT_15_C05_daily_auxiliary_at_intraday_decision_uses_completed_prior_day(tmp_path):
    value, data = make_candidate(tmp_path), fixture(date(2025, 12, 1), close_hour=21)
    declaration = replace(
        value.definition.auxiliary_inputs[0],
        instrument=value.instrument,
        frequency=BarFrequency.DAILY,
        warmup_bars=1,
        max_age_seconds=72 * 3600,
    )
    value = replace(value, definition=replace(value.definition, auxiliary_inputs=(declaration,)))
    dates = [
        datetime(2025, 11, 27, 21, tzinfo=timezone.utc),
        datetime(2025, 11, 28, 18, tzinfo=timezone.utc),
        datetime(2025, 12, 1, 21, tzinfo=timezone.utc),
    ]
    daily = pd.DataFrame(
        {
            "Date": dates,
            "AvailableDate": dates,
            "Open": 10.0,
            "High": 11.0,
            "Low": 9.0,
            "Close": [10.0, 11.0, 10.0],
            "Volume": 100.0,
        }
    )
    context = build(value, data, auxiliary_histories={"market": daily})
    assert context.auxiliary_histories["market"].Date.tolist() == dates[:2]
    assert context.auxiliary_histories["market"].Close.iloc[-1] == 11.0
    # Calendar age includes the weekend; no automatic trading-day tolerance.
    tight = replace(
        value,
        definition=replace(
            value.definition, auxiliary_inputs=(replace(declaration, max_age_seconds=48 * 3600),)
        ),
    )
    with pytest.raises(ValueError, match="STALE"):
        build(tight, data, auxiliary_histories={"market": daily})
    delayed = daily.copy(deep=True)
    delayed.loc[1, "AvailableDate"] = data[2].decision_at + timedelta(seconds=1)
    with pytest.raises(ValueError, match="STALE"):
        build(value, data, auxiliary_histories={"market": delayed})
    with pytest.raises(ValueError, match="future auxiliary"):
        value.decide(replace(context, auxiliary_histories={"market": daily}))


def test_SRT_15_C04_execution_interval_requires_exact_calendar_segment(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    context = build(value, data)
    first = context.session.segments[0]
    wrong = TradingSession(
        context.session.session_date,
        context.session.timezone,
        (TimeInterval(first.start, first.start + timedelta(minutes=30)),),
    )
    with pytest.raises(ValueError, match="exact execution interval"):
        value.decide(replace(context, session=wrong))


def test_SRT_15_C06_shared_session_calendar_conflict_rejected(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    table = data[3].copy(deep=True)
    table["SessionDate"] = "2025-03-11"
    with pytest.raises(ValueError, match="calendar evidence"):
        build(value, data, sessions=table)


def test_SRT_16_C04_auxiliary_warmup_precedes_strategy(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    delayed = data[1].copy(deep=True)
    delayed.loc[1, "AvailableDate"] += timedelta(seconds=1)
    with pytest.raises(ValueError, match="WARMUP_INSUFFICIENT"):
        build(value, data, auxiliary_histories={"market": delayed})
