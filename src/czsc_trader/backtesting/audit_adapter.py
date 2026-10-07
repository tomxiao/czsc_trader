from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd
from strategy_evaluator import BenchmarkEvidence, ReplayEvidence

from .execution_data import BacktestExecutionData
from .result import BacktestResult
from .signal_replay import SignalReplay
from .benchmarks import BenchmarkReplay


def _records(frame: pd.DataFrame, date_columns: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    value = pd.DataFrame(frame, copy=False).copy()
    for column in date_columns:
        if column in value:
            value[column] = value[column].map(
                lambda item: None if pd.isna(item) else pd.Timestamp(item).isoformat()
            )
    value = value.replace({float("nan"): None})
    return tuple(value.to_dict(orient="records"))


def build_replay_evidence(
    signals: SignalReplay,
    data: BacktestExecutionData,
    result: BacktestResult,
    initial_cash: float,
    metrics: dict[str, object],
) -> ReplayEvidence:
    daily_prices = pd.DataFrame(data.execution_daily, copy=False).copy()
    if data.pricing.basis.value == "UNADJUSTED":
        daily_prices["unadjusted_close"] = daily_prices["close"]
    else:
        raw = data.raw_execution_daily.set_index("dt")["close"]
        daily_prices["unadjusted_close"] = daily_prices["dt"].map(raw)
    daily_prices["price_scale"] = daily_prices["close"] / daily_prices["unadjusted_close"]
    support = signals.support_data or {}
    evaluation_sessions = tuple(
        pd.to_datetime(
            daily_prices.loc[
                daily_prices["dt"].between(
                    signals.evaluation_start, signals.evaluation_end
                ),
                "dt",
            ]
        )
        .dt.normalize()
        .dt.date.astype(str)
    )
    srt_policy = support.get("execution_policy")
    if support.get("mode") != "srt_input_contract":
        raise ValueError("replay audit requires SRT execution evidence")
    if not isinstance(srt_policy, dict):
        raise ValueError("SRT replay has no execution policy evidence")
    policy_type = srt_policy.get("policy_type")
    settings = srt_policy.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("SRT replay execution settings are invalid")
    overlay_settings = settings if policy_type == "INTRADAY_OVERLAY" else None
    frozen_settings = settings if policy_type == "FROZEN_RULE" else None
    if overlay_settings is None and frozen_settings is None:
        raise ValueError(f"unsupported SRT execution policy: {policy_type}")
    if overlay_settings is not None:
        if data.execution_five_minute is None:
            raise ValueError("intraday overlay audit requires 5m execution data")
        daily = daily_prices.loc[
            daily_prices["dt"].le(signals.evaluation_end)
        ].rename(columns={"dt": "date"})
        minute_prices = pd.DataFrame(data.execution_five_minute, copy=False)
        intraday = minute_prices.loc[
            minute_prices["dt"].between(
                signals.evaluation_start,
                signals.evaluation_end + pd.Timedelta(days=1),
            )
        ].rename(columns={"dt": "time"})
        return ReplayEvidence(
            strategy_hash=signals.snapshot.content_hash,
            data_hash=data.fingerprint,
            initial_cash=float(initial_cash),
            evaluation_sessions=evaluation_sessions,
            execution_spec={
                "pricing": data.pricing.to_dict(),
                "mode": "CORE_EVENT_INTRADAY_ROTATION",
                "fee_rate": overlay_settings["one_way_cost"],
                "lot_size": overlay_settings["lot_size"],
                "core_fraction": overlay_settings["core_fraction"],
                "event_fraction": overlay_settings["event_fraction"],
                "entry_checkpoint": overlay_settings["entry_checkpoint"],
                "exit_checkpoint": overlay_settings["exit_checkpoint"],
                "t_plus_one_inventory_rotation": overlay_settings[
                    "t_plus_one_inventory_rotation"
                ],
                "order_semantics": (
                    "SRT_PLAN"
                    if support.get("mode") == "srt_input_contract"
                    else "LEGACY_REPLAY"
                ),
            },
            decisions=_records(result.decisions, ("signal_date", "valid_session")),
            orders=_records(result.orders, ("signal_date", "execution_date")),
            fills=_records(result.fills, ("signal_date", "fill_time")),
            account_daily=_records(result.account_daily, ("date", "signal_date")),
            trades=_records(result.trades, ("entry_date", "exit_date")),
            metrics=metrics,
            execution_daily=_records(daily, ("date",)),
            execution_intraday=_records(intraday, ("time",)),
        )
    if frozen_settings is not None:
        entry = frozen_settings.get("entry")
        exit_rule = frozen_settings.get("exit")
        capital = frozen_settings.get("capital")
        instrument = frozen_settings.get("instrument")
        if not all(
            isinstance(item, Mapping)
            for item in (entry, exit_rule, capital, instrument)
        ):
            raise ValueError("SRT frozen execution policy is structurally incomplete")
        entry_order_type = support.get("entry_order_type")
        exit_order_type = support.get("exit_order_type")
        if not all(
            isinstance(item, str) and item.strip()
            for item in (entry_order_type, exit_order_type)
        ):
            raise ValueError("SRT replay has no effective order-type evidence")
        execution_spec = {
            "pricing": data.pricing.to_dict(),
            "decision_coverage": "COMPLETE",
            "entry_limit_parameter": entry["limit_parameter"],
            "exit_limit_ratio": exit_rule["limit_ratio"],
            "entry_order_type": entry_order_type,
            "exit_order_type": exit_order_type,
            "fee_rate": capital["fee_rate"],
            "capital_mode": capital["mode"],
            "allocation_fraction": capital.get("allocation_fraction", 1.0),
            "instrument": {
                "lot_size": instrument["lot_size"],
                "price_tick": instrument["price_tick"],
                "price_limit_ratio": instrument["price_limit_ratio"],
                "maximum_order_quantity": instrument["maximum_order_quantity"],
            },
        }
    start = signals.calculation_start
    end = signals.evaluation_end
    daily = daily_prices.loc[daily_prices["dt"].between(start, end)].rename(
        columns={"dt": "date"}
    )
    minute_prices = pd.DataFrame(data.execution_intraday, copy=False)
    intraday = minute_prices.loc[
        minute_prices["dt"].between(start, end + pd.Timedelta(days=1))
    ].rename(columns={"dt": "time"})
    return ReplayEvidence(
        strategy_hash=signals.snapshot.content_hash,
        data_hash=data.fingerprint,
        initial_cash=float(initial_cash),
        evaluation_sessions=evaluation_sessions,
        execution_spec=execution_spec,
        decisions=_records(result.decisions, ("signal_date", "valid_session")),
        orders=_records(result.orders, ("signal_date", "execution_date")),
        fills=_records(result.fills, ("signal_date", "fill_time")),
        account_daily=_records(result.account_daily, ("date", "signal_date")),
        trades=_records(result.trades, ("entry_date", "exit_date")),
        metrics=metrics,
        execution_daily=_records(daily, ("date",)),
        execution_intraday=_records(intraday, ("time",)),
    )


def build_benchmark_evidence(
    benchmarks: BenchmarkReplay,
    signals: SignalReplay,
    data: BacktestExecutionData,
    initial_cash: float,
    *,
    lot_size: int,
) -> dict[str, BenchmarkEvidence]:
    evaluation = data.execution_daily.loc[
        data.execution_daily["dt"].between(
            signals.evaluation_start, signals.evaluation_end
        )
    ].rename(columns={"dt": "date"})
    sessions = tuple(pd.to_datetime(evaluation["date"]).dt.date.astype(str))
    support = signals.support_data or {}
    policy = support.get("execution_policy")
    if support.get("mode") == "srt_input_contract":
        if not isinstance(policy, Mapping) or not isinstance(policy.get("settings"), Mapping):
            raise ValueError("SRT benchmark evidence has no execution settings")
        settings = policy["settings"]
        if policy.get("policy_type") == "FROZEN_RULE":
            fee_rate = float(settings["capital"]["fee_rate"])
        elif policy.get("policy_type") == "INTRADAY_OVERLAY":
            fee_rate = float(settings["one_way_cost"])
        else:
            raise ValueError("SRT benchmark evidence has unsupported execution policy")
    else:
        raise ValueError("benchmark audit requires SRT execution evidence")
    empty_trades: tuple[dict[str, Any], ...] = ()
    prices = _records(evaluation, ("date",))
    return {
        "buyhold": BenchmarkEvidence(
            "BUYHOLD",
            float(initial_cash),
            fee_rate,
            sessions,
            prices,
            (),
            _records(benchmarks.buyhold_account_daily, ("date", "signal_date")),
            _records(benchmarks.buyhold_orders, ("signal_date", "execution_date")),
            empty_trades,
            benchmarks.metrics["buyhold"]["metrics"],
            lot_size=lot_size,
        ),
        "ma5_ma20": BenchmarkEvidence(
            "MA5_MA20",
            float(initial_cash),
            fee_rate,
            sessions,
            prices,
            _records(benchmarks.ma_audit_signals, ("date",)),
            _records(benchmarks.ma_account_daily, ("date", "signal_date")),
            _records(benchmarks.ma_orders, ("signal_date", "execution_date")),
            _records(benchmarks.ma_trades, ("entry_date", "exit_date")),
            benchmarks.metrics["ma5_ma20"]["metrics"],
            lot_size=lot_size,
        ),
    }
