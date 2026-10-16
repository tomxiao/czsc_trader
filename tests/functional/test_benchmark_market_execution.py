"""Stock and ETF benchmarks share the same date-specific fill constraints."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from czsc_trader.backtesting.benchmark_contracts import EvaluationBenchmark, LimitBuyHold, NextOpenBuyHold
from czsc_trader.backtesting.benchmarks import replay_benchmarks, replay_buyhold
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.backtesting.signal_replay import SignalReplay
from trading_execution_engine import MarketExecutionRules, SessionPriceLimits, execute_target_positions


def _inputs(tmp_path, symbol):
    dates = pd.bdate_range("2025-01-02", periods=27)
    close = np.r_[np.linspace(9.0, 10.0, 24), 10.8, 10.6, 10.5]
    prices = pd.DataFrame({"dt": dates, "open": close, "close": close})
    prices.loc[24:, "open"] = [11.0, 10.0, 8.0]
    prices["high"] = prices[["open", "close"]].max(axis=1)
    prices["low"] = prices[["open", "close"]].min(axis=1)
    rules = MarketExecutionRules(symbol, tuple(
        SessionPriceLimits(day.date(), 1.0, 11.0 if index == 24 else 20.0)
        for index, day in enumerate(dates)
    ))
    data = BacktestExecutionData(
        root=tmp_path, symbol=symbol, asset_type="stock" if symbol == "600722.SH" else "etf",
        adjusted_daily=prices.copy(), execution_daily=prices,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        fingerprint="a" * 64, cutoff=dates[-1].date(), evaluation_sessions=dates[24:],
        market_rules=rules,
    )
    signals = SignalReplay(
        snapshot=None, strategy_source=None, decisions=pd.DataFrame(),
        calculation_start=dates[0], calculation_end=dates[-1],
        evaluation_start=dates[24], evaluation_end=dates[-1], data_dir=tmp_path,
        data_identity="b" * 64,
        support_data={"mode": "srt_input_contract", "execution_policy": {
            "policy_type": "FROZEN_RULE", "settings": {"capital": {"fee_rate": 0.001}},
        }},
    )
    return signals, data


@pytest.mark.parametrize("symbol", ["600722.SH", "588080.SH"])
def test_next_open_and_ma_retry_blocked_entry_without_counting_attempt_as_fill(tmp_path, symbol):
    signals, data = _inputs(tmp_path, symbol)
    result = replay_benchmarks(signals, data, 10000.0, lot_size=100)
    for prefix in ("buyhold", "ma"):
        attempts = getattr(result, f"{prefix}_attempts")
        fills = getattr(result, f"{prefix}_fills")
        orders = getattr(result, f"{prefix}_orders")
        account = getattr(result, f"{prefix}_account_daily")
        assert attempts.status.tolist() == ["UNFILLED", "FILLED"]
        assert len(fills) == len(orders) == 1
        assert fills.iloc[0].execution_date == data.evaluation_sessions[1]
        assert fills.iloc[0].signal_date == data.evaluation_sessions[0]
        assert account.quantity.tolist() == [0, 900, 900]
        assert account.cash.tolist() == pytest.approx([10000, 991, 991])
        assert account.equity.tolist() == pytest.approx([10000, 10531, 10441])
    assert result.metrics["buyhold"]["metrics"]["closed_trades"] == 0
    assert result.metrics["ma5_ma20"]["metrics"]["closed_trades"] == 0


@pytest.mark.parametrize("lot_size", [1, 100])
def test_unblocked_next_open_ledger_matches_existing_cash_and_lot_semantics(tmp_path, lot_size):
    signals, data = _inputs(tmp_path, "588080.SH")
    unconstrained = replace(data, market_rules=None)
    replay = replay_buyhold(
        signals, unconstrained, 10000.0,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(lot_size)),
    )
    daily = data.execution_daily.iloc[24:]
    expected = execute_target_positions(
        daily, pd.Series(1.0, index=data.evaluation_sessions),
        fee_rate=0.001, initial_cash=10000.0, lot_size=lot_size,
    )
    assert replay.account_daily.quantity.tolist() == expected.state.quantity.tolist()
    assert replay.account_daily.cash.tolist() == expected.state.cash.tolist()
    assert replay.account_daily.equity.tolist() == expected.equity.tolist()
    assert len(replay.attempts) == len(replay.fills) == len(replay.orders) == 1


@pytest.mark.parametrize("symbol", ["600722.SH", "588080.SH"])
def test_limit_buyhold_uses_same_market_boundary_and_keeps_unfilled_cash(tmp_path, symbol):
    signals, data = _inputs(tmp_path, symbol)
    data = replace(data, execution_intraday=pd.DataFrame({
        "dt": [signals.evaluation_start + pd.Timedelta(hours=10)],
        "high": [11.0], "low": [10.8],
    }))
    replay = replay_buyhold(
        replace(signals, evaluation_end=signals.evaluation_start), data, 10000.0,
        benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.09, 0.01, 0.1, 1000000)),
    )
    assert replay.attempts.status.tolist() == ["UNFILLED"]
    assert replay.fills.empty
    assert replay.account_daily.iloc[0].cash == 10000.0
    assert replay.account_daily.iloc[0].quantity == 0
    assert replay.metrics["closed_trades"] == 0
    assert replay.metrics["return"] == 0.0


@pytest.mark.parametrize("symbol", ["600722.SH", "588080.SH"])
def test_ma_blocked_exit_keeps_position_and_retries_current_zero_target(tmp_path, symbol):
    signals, data = _inputs(tmp_path, symbol)
    prices = data.execution_daily.copy()
    prices.loc[24:, "open"] = [9.0, 1.0, 1.1]
    prices.loc[24:, "close"] = [1.0, 1.1, 1.2]
    prices["high"] = prices[["open", "close"]].max(axis=1)
    prices["low"] = prices[["open", "close"]].min(axis=1)
    rules = MarketExecutionRules(symbol, tuple(
        SessionPriceLimits(day.date(), 1.0 if index == 25 else 0.5, 20.0)
        for index, day in enumerate(pd.DatetimeIndex(prices.dt))
    ))
    result = replay_benchmarks(
        signals, replace(data, adjusted_daily=prices.copy(), execution_daily=prices, market_rules=rules),
        10000.0, lot_size=100,
    )
    assert result.ma_attempts.side.tolist() == ["BUY", "SELL", "SELL"]
    assert result.ma_attempts.status.tolist() == ["FILLED", "UNFILLED", "FILLED"]
    assert result.ma_account_daily.quantity.tolist() == [1100, 1100, 0]
    assert result.ma_account_daily.cash.tolist() == pytest.approx([90.1, 90.1, 1298.89])
    assert result.ma_orders.side.tolist() == ["BUY", "SELL"]
    assert len(result.ma_fills) == 2
    assert len(result.ma_trades) == result.metrics["ma5_ma20"]["metrics"]["closed_trades"] == 1
