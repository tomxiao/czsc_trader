# Risk ownership: TDR-06
"""Stock and ETF benchmarks share the same date-specific fill constraints."""

from dataclasses import replace

import numpy as np
import pandas as pd

from czsc_trader.backtesting.benchmarks import valuation_prices
from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.backtesting.signal_replay import SignalReplay
from execution_channels.historical import MarketExecutionRules, SessionPriceLimits


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




def test_TDR_06_C05_valuation_projection_retains_halted_price_source_and_isolates_values(tmp_path):
    signals, data = _inputs(tmp_path, "588080.SH")
    halted = data.evaluation_sessions[1]
    daily = data.execution_daily.loc[data.execution_daily.dt.ne(halted)].copy()
    daily.attrs = {"quality": {"scope": "original"}}
    expected = pd.DataFrame(daily, copy=True)
    value = valuation_prices(replace(data, execution_daily=daily), signals.evaluation_start, signals.evaluation_end)
    assert value.dt.tolist() == list(data.evaluation_sessions)
    assert pd.isna(value.loc[1, "open"])
    assert value.loc[1, "close"] == value.loc[0, "close"]
    assert value.loc[1, "valuation_source_date"] == data.evaluation_sessions[0]
    value.loc[0, "close"] = -1.
    value.attrs["projection"] = True
    assert daily.attrs == {"quality": {"scope": "original"}}
    pd.testing.assert_frame_equal(pd.DataFrame(daily, copy=False), expected)
