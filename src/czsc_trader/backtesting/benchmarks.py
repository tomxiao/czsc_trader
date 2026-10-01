from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from czsc_trader.moving_average import moving_average_signals
from czsc_trader.strategy_metrics import closed_trade_ledger, strategy_comparison_metrics
from trading_execution_engine import ExecutionResult, execute_target_positions

from .benchmark_contracts import EvaluationBenchmark, LimitBuyHold, NextOpenBuyHold

from .execution_data import BacktestExecutionData
from .signal_replay import SignalReplay


@dataclass(frozen=True)
class BenchmarkReplay:
    metrics: dict[str, object]
    buyhold_account_daily: pd.DataFrame
    buyhold_orders: pd.DataFrame
    ma_signals: pd.DataFrame
    ma_orders: pd.DataFrame
    ma_account_daily: pd.DataFrame
    ma_trades: pd.DataFrame
    ma_audit_signals: pd.DataFrame


@dataclass(frozen=True)
class BuyHoldReplay:
    """A same-window and same-cost BuyHold benchmark replay."""

    metrics: dict[str, object]
    account_daily: pd.DataFrame
    orders: pd.DataFrame
    benchmark: EvaluationBenchmark
    execution: ExecutionResult | None = None


def _fee_rate(signals: SignalReplay) -> float:
    support = signals.support_data or {}
    if support.get("mode") == "srt_input_contract":
        policy = support.get("execution_policy")
        if not isinstance(policy, dict):
            raise ValueError("SRT replay has no execution policy evidence")
        settings = policy.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("SRT replay execution settings are invalid")
        policy_type = policy.get("policy_type")
        if policy_type == "FROZEN_RULE":
            capital = settings.get("capital")
            if not isinstance(capital, dict) or "fee_rate" not in capital:
                raise ValueError("SRT frozen rule has no fee rate")
            return float(capital["fee_rate"])
        if policy_type == "INTRADAY_OVERLAY" and "one_way_cost" in settings:
            return float(settings["one_way_cost"])
        raise ValueError(f"unsupported SRT execution policy: {policy_type}")
    raise ValueError("benchmark replay requires SRT execution evidence")


def _account_daily(
    prices: pd.DataFrame,
    target: pd.Series,
    initial_target: float,
    initial_signal_date: pd.Timestamp,
    equity: pd.Series,
    state: pd.DataFrame,
) -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.to_datetime(prices["dt"]), name="date")
    desired = target.reindex(index).astype(float)
    execution_target = desired.shift(1)
    execution_target.iloc[0] = float(initial_target)
    signal_dates = pd.Series(index=index, dtype="datetime64[ns]")
    signal_dates.iloc[0] = initial_signal_date
    signal_dates.iloc[1:] = index[:-1].to_numpy()
    return pd.DataFrame(
        {
            "date": index,
            "signal_date": signal_dates.to_numpy(),
            "target_position": execution_target.to_numpy(),
            "close": prices["close"].astype(float).to_numpy(),
            "equity": equity.reindex(index).astype(float).to_numpy(),
            "cash": state["cash"].reindex(index).to_numpy(),
            "quantity": state["quantity"].reindex(index).to_numpy(),
        }
    )


def replay_buyhold(
    signals: SignalReplay,
    execution_data: BacktestExecutionData,
    initial_cash: float,
    *,
    benchmark: EvaluationBenchmark,
) -> BuyHoldReplay:
    """Run the independently funded BuyHold benchmark for a signal window."""

    if type(benchmark) is not EvaluationBenchmark:
        raise TypeError("BuyHold replay requires an EvaluationBenchmark")
    fee_rate = _fee_rate(signals)
    if isinstance(benchmark.execution, LimitBuyHold):
        from ._limit_buyhold import replay_limit_buyhold

        ledger = replay_limit_buyhold(signals, execution_data, initial_cash, benchmark, fee_rate)
        from .metrics import calculate_metrics

        metrics = calculate_metrics(ledger, initial_cash)
        return BuyHoldReplay(metrics, ledger.account_daily, ledger.orders, benchmark, ledger)
    execution = execution_data.execution_daily.copy()
    execution["dt"] = pd.to_datetime(execution["dt"]).dt.normalize()
    evaluation = execution.loc[
        execution["dt"].between(signals.evaluation_start, signals.evaluation_end)
    ].copy()
    evaluation_index = pd.DatetimeIndex(evaluation["dt"], name="dt")
    if evaluation.empty:
        raise ValueError("benchmark interval contains no execution sessions")

    adjusted_dates = pd.DatetimeIndex(
        pd.to_datetime(execution_data.adjusted_daily["dt"])
    ).normalize()
    prior_dates = adjusted_dates[adjusted_dates < signals.evaluation_start]
    if prior_dates.empty:
        raise ValueError("benchmark interval has no prior signal session")
    prior_date = pd.Timestamp(prior_dates[-1])

    target = pd.Series(1.0, index=evaluation_index, name="target_position")
    result = execute_target_positions(
        evaluation,
        target,
        fee_rate=fee_rate,
        initial_cash=initial_cash,
        lot_size=benchmark.execution.lot_size,
    )
    orders = result.orders.copy()
    if not orders.empty:
        orders = orders.rename(columns={"quantity": "size"})
        previous_sessions = pd.Series(
            [prior_date, *evaluation_index[:-1]], index=evaluation_index
        )
        orders.insert(
            0,
            "signal_date",
            pd.to_datetime(orders["execution_date"]).map(previous_sessions),
        )
        orders = orders[
            ["signal_date", "execution_date", "side", "size", "price", "fees"]
        ].reset_index(drop=True)
    else:
        orders = pd.DataFrame(
            columns=["signal_date", "execution_date", "side", "size", "price", "fees"]
        )
    metrics = strategy_comparison_metrics(result.equity, orders, initial_cash)
    metrics["closed_trades"] = 0
    return BuyHoldReplay(
        metrics=metrics,
        account_daily=_account_daily(
            evaluation,
            target,
            1.0,
            prior_date,
            result.equity,
            result.state,
        ),
        orders=orders,
        benchmark=benchmark,
    )


def replay_benchmarks(
    signals: SignalReplay,
    execution_data: BacktestExecutionData,
    initial_cash: float,
    *,
    lot_size: int,
) -> BenchmarkReplay:
    """Run independently funded BuyHold and MA5/MA20 next-open benchmarks."""
    fee_rate = _fee_rate(signals)
    execution = execution_data.execution_daily.copy()
    execution["dt"] = pd.to_datetime(execution["dt"]).dt.normalize()
    evaluation = execution.loc[
        execution["dt"].between(signals.evaluation_start, signals.evaluation_end)
    ].copy()
    evaluation_index = pd.DatetimeIndex(evaluation["dt"], name="dt")
    if evaluation.empty:
        raise ValueError("benchmark interval contains no execution sessions")

    adjusted_signals = moving_average_signals(execution_data.adjusted_daily)
    prior_dates = adjusted_signals.index[adjusted_signals.index < signals.evaluation_start]
    if prior_dates.empty:
        raise ValueError("benchmark interval has no prior signal session")
    prior_date = pd.Timestamp(prior_dates[-1])

    buyhold = replay_buyhold(
        signals, execution_data, initial_cash,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(lot_size)),
    )

    ma_target = adjusted_signals["target_position"].reindex(evaluation_index).astype(float)
    initial_ma_target = float(adjusted_signals.loc[prior_date, "target_position"])
    execution_target = ma_target.shift(1)
    execution_target.iloc[0] = initial_ma_target
    ma = execute_target_positions(
        evaluation,
        execution_target,
        fee_rate=fee_rate,
        initial_cash=initial_cash,
        lot_size=lot_size,
    )
    ma_orders = ma.orders.rename(columns={"quantity": "size"}).copy()
    previous_sessions = pd.Series([prior_date, *evaluation_index[:-1]], index=evaluation_index)
    ma_orders.insert(0, "signal_date", pd.to_datetime(ma_orders["execution_date"]).map(previous_sessions))
    ma_trades = closed_trade_ledger(ma_orders)
    ma_metrics = strategy_comparison_metrics(ma.equity, ma_orders, initial_cash)
    ma_metrics["closed_trades"] = int(len(ma_trades))
    ma_account = _account_daily(
        evaluation,
        ma_target,
        initial_ma_target,
        prior_date,
        ma.equity,
        ma.state,
    )
    visible_signals = adjusted_signals.loc[prior_date : signals.evaluation_end].reset_index()
    visible_signals = visible_signals.rename(columns={"dt": "date"})
    evaluation_start_location = int(adjusted_signals.index.get_loc(evaluation_index[0]))
    audit_start_location = max(0, evaluation_start_location - 20)
    ma_audit_signals = adjusted_signals.iloc[
        audit_start_location : int(adjusted_signals.index.get_loc(evaluation_index[-1])) + 1
    ].reset_index().rename(columns={"dt": "date"})
    return BenchmarkReplay(
        metrics={
            "buyhold": {"metrics": buyhold.metrics},
            "ma5_ma20": {"metrics": ma_metrics},
        },
        buyhold_account_daily=buyhold.account_daily,
        buyhold_orders=buyhold.orders,
        ma_signals=visible_signals,
        ma_orders=ma_orders,
        ma_account_daily=ma_account,
        ma_trades=ma_trades,
        ma_audit_signals=ma_audit_signals,
    )
