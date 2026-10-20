"""Synthetic contract checks: no market provider, account execution, or publication."""

from datetime import date
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from strategy_runtime import (
    HistoryCalculationContext,
    ParameterSet,
    SignalHistoryMode,
    TradableWindow,
)


ROOT = Path(__file__).resolve().parents[5]
OLD_SOURCE = ROOT / "research/S014/assets/candidates/C9521/source/92a9fa2441693c564487b46200a2feb994147cc97ad818f2239b7ce922591bf6/strategy_runtime/strategies/trend_permission.py"
NEW_SOURCE = Path(__file__).parent / "c9522/strategy_runtime/strategies/trend_permission.py"


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture_inputs():
    dates = pd.bdate_range("2019-12-31", periods=120)
    # Alternating rising/falling periods force completed cycles and feedback.
    close = 10 + np.arange(len(dates)) * .01 + np.sin(np.arange(len(dates)) / 3) * .6
    market = pd.DataFrame({"Date": dates, "Open": close, "High": close * 1.015,
                           "Low": close * .985, "Close": close})
    raw = market.copy()
    limits = pd.DataFrame({"Date": dates, "DownLimit": close * .9, "UpLimit": close * 1.1})
    status = pd.DataFrame({"Date": dates, "Status": "TRADING"})
    return dates, {"market": market, "raw": raw, "limits": limits, "status": status}


def context(dates, start=0, mode=SignalHistoryMode.WINDOW):
    selected = tuple(x.date() for x in dates[start:])
    calculation = tuple(x.date() for x in dates)
    # Execution sessions are the next synthetic business sessions.
    end = (dates[-1] + pd.offsets.BDay(1)).date()
    window = TradableWindow((dates[start] + pd.offsets.BDay(1)).date(), end)
    return HistoryCalculationContext(mode, window, selected, calculation)


def test_full_window_and_continuous_exact_original_history():
    old = load_source("c9521_window_old", OLD_SOURCE)
    new = load_source("c9522_window_new", NEW_SOURCE)
    dates, inputs = fixture_inputs()
    config = {"permission_profile": "AGE_PRIOR_TREND_PERMISSION"}
    original = old.history(inputs["market"], inputs["raw"], inputs["limits"],
                           inputs["status"], old.PermissionConfig.parse(config))
    successor = new.TrendPermissionStrategy(ParameterSet(config))
    for mode in SignalHistoryMode:
        actual = successor.calculate_context_history(inputs, context(dates, mode=mode))
        pd.testing.assert_frame_equal(actual, original.astype({
            k: float for k in successor._observed
        }), check_names=False, check_index_type=False, check_exact=True)


def test_later_window_resets_state_but_retains_indicator_anchor():
    new = load_source("c9522_window_reset", NEW_SOURCE)
    dates, inputs = fixture_inputs()
    successor = new.TrendPermissionStrategy(ParameterSet({
        "permission_profile": "AGE_PRIOR_TREND_PERMISSION"
    }))
    continuous = successor.calculate_context_history(inputs, context(dates))
    candidates = np.flatnonzero(continuous.held_at_close.to_numpy() > 0)
    assert len(candidates), "Fixture must expose historical open-position state"
    start = int(candidates[0])
    window = context(dates, start=start)
    fresh = successor.calculate_context_history(inputs, window)
    first = fresh.iloc[0]
    assert first.held_at_close == 0
    assert first.pending_inherited == 0
    assert first.last_completed_sign == 0
    assert first.pause_armed == 0
    assert first.shock_state_assessed == 0
    assert first.warmup_sessions == continuous.iloc[start].warmup_sessions
    assert first.ma20_prior == continuous.iloc[start].ma20_prior
    assert first.support_floor == continuous.iloc[start].support_floor
    assert list(fresh.index) == list(window.sessions)
    pd.testing.assert_frame_equal(
        fresh, successor.calculate_context_history(inputs, window), check_exact=True
    )
    resumed = successor.calculate_context_history(
        inputs, context(dates, start=start, mode=SignalHistoryMode.CONTINUOUS)
    )
    pd.testing.assert_frame_equal(resumed, continuous, check_exact=True)


def test_missing_anchor_and_noncontiguous_state_refused():
    new = load_source("c9522_window_errors", NEW_SOURCE)
    dates, inputs = fixture_inputs()
    config = new.PermissionConfig.parse({"permission_profile": "AGE_PRIOR_TREND_PERMISSION"})
    with pytest.raises(ValueError, match="indicator anchor"):
        new.history(inputs["market"].iloc[1:], inputs["raw"].iloc[1:], inputs["limits"],
                    inputs["status"], config, dates[1:])
    with pytest.raises(ValueError, match="contiguous"):
        new.history(inputs["market"], inputs["raw"], inputs["limits"], inputs["status"],
                    config, dates[[70, 72]])


def test_scope_keeps_original_feature_requests_for_late_window():
    new = load_source("c9522_window_scope", NEW_SOURCE)
    successor = new.TrendPermissionStrategy(ParameterSet({
        "permission_profile": "AGE_PRIOR_TREND_PERMISSION"
    }))
    dates = tuple(x.date() for x in pd.bdate_range("2019-12-01", "2026-10-19"))
    scope = successor.derive_calculation_scope(
        TradableWindow(date(2026, 6, 1), date(2026, 10, 19)), dates
    )
    assert scope.calculation_dates[0] == date(2019, 12, 31)
    assert scope.signal_dates[date(2026, 6, 1)] == date(2026, 5, 29)
    assert scope.signal_dates[date(2026, 10, 19)] == date(2026, 10, 16)
    assert str(scope.inputs["market"].start) == "2019-12-31"
