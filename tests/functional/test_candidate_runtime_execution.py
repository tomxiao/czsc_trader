# Risk ownership: TDR-04
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding, PreparePolicy

from strategy_runtime import (
    StrategyCandidate,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
)
from execution_channels.historical import HistoricalExecutor
from execution_channels.serialization import from_record, to_record
from execution_channels.policy import ExecutionPolicy as ChannelPolicy
from czsc_trader.application.session_replay import replay_sessions
from czsc_trader.backtesting.observation import ObservationExecutor


def _install_candidate_dataflows(monkeypatch, flow, daily, *, base_dir=None, space=None, hfq_factors=None, price_limits=None, asset_type="etf", suspended_dates=()):
    from dataflows.ohlcv_quality import (
        bind_quality_frame, build_quality_evidence, verify_daily_sessions,
    )

    market = daily.rename(
        columns={
            "dt": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
            "amount": "Amount",
        }
    ).copy()
    for column, value in (
        ("High", market[["Open", "Close"]].max(axis=1)),
        ("Low", market[["Open", "Close"]].min(axis=1)),
        ("Volume", 1000.0),
    ):
        if column not in market:
            market[column] = value
    if "Amount" not in market:
        market["Amount"] = market["Volume"] * (market["High"] + market["Low"]) / 2

    suspended_dates = set(pd.to_datetime(list(suspended_dates)).strftime("%Y-%m-%d"))
    market = market.loc[~pd.to_datetime(market.Date).dt.strftime("%Y-%m-%d").isin(suspended_dates)].reset_index(drop=True)

    class SyntheticCalendar:
        """Declared weekday calendar and lifecycle for this synthetic provider."""

        def fund_basic(self, *, ts_code, fields):
            listed = pd.to_datetime(market["Date"]).min().strftime("%Y%m%d")
            return pd.DataFrame({"ts_code": [ts_code], "list_date": [listed]})

        stock_basic = fund_basic

        def trade_cal(self, *, exchange, start_date, end_date):
            dates = pd.date_range(start_date, end_date)
            return pd.DataFrame({"cal_date": dates.strftime("%Y%m%d"),
                                 "is_open": (dates.weekday < 5).astype(int)})

    def coverage(request, frame):
        baseline = frame if not suspended_dates else pd.DataFrame({"Date": pd.bdate_range(request.start, request.end)})
        baseline = baseline.loc[pd.to_datetime(baseline.Date).ge(pd.to_datetime(market.Date).min())]
        value = verify_daily_sessions(SyntheticCalendar(), request.symbol, baseline, start=pd.Timestamp(request.start).date().isoformat(),
                                     end=pd.Timestamp(request.end).date().isoformat(), asset_type=asset_type)
        halted = sorted(suspended_dates.intersection(value["expected_dates"]))
        value["expected_dates"] = [day for day in value["expected_dates"] if day not in halted]
        value.update(verified_sessions=len(value["expected_dates"]), suspended_dates=halted,
                     suspension_evidence=[{"date": day, "status": "SUSPENDED", "source": "synthetic-exchange"} for day in halted])
        return value

    def fetch(request):
        dataset = str(request.dataset)
        if dataset == Dataset.TRADING_CALENDAR.value:
            dates = pd.date_range(request.start, request.end)
            return pd.DataFrame({"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}), {
                "vendor": "test"
            }
        if dataset == Dataset.SECURITY_TRADING_STATUS.value:
            evidence = coverage(request, pd.DataFrame({"Date": pd.bdate_range(request.start, request.end)}))
            dates = sorted(set(evidence["expected_dates"]) | set(evidence["suspended_dates"]))
            return pd.DataFrame({"Date": dates, "Status": ["SUSPENDED" if day in suspended_dates else "TRADING" for day in dates]}), {"vendor": "test", "daily_session_coverage": evidence}
        if dataset == Dataset.SECURITY_PRICE_LIMITS.value:
            frame = price_limits.copy() if price_limits is not None else pd.DataFrame({
                "Date": market["Date"], "UpLimit": market["High"] * 2, "DownLimit": market["Low"] / 2,
            })
        elif dataset == Dataset.ETF_SHARE_SIZE.value and request.symbol == "588080.SH":
            frame = flow.copy()
            frame["TotalShare"] = frame["Flow"]
        elif dataset == Dataset.ETF_SHARE_SIZE.value:
            frame = pd.DataFrame({"Date": market["Date"], "TotalShare": range(1, len(market) + 1)})
        else:
            frame = market.copy()
            if dataset in {Dataset.ETF_OHLCV.value, Dataset.STOCK_OHLCV.value} and hfq_factors is not None:
                for column in ("Open", "High", "Low", "Close"):
                    frame[column] = frame[column] * hfq_factors
                frame["Volume"] = frame["Volume"] / hfq_factors
            if request.frequency == "30m":
                pieces = []
                for hour, minute in ((10, 0), (10, 30), (11, 0), (11, 30),
                                     (13, 30), (14, 0), (14, 30), (15, 0)):
                    piece = frame.copy()
                    piece["Date"] = pd.to_datetime(piece["Date"]).dt.normalize() + pd.Timedelta(hours=hour, minutes=minute)
                    piece["Volume"] = piece["Volume"] / 8
                    piece["Amount"] = piece["Amount"] / 8
                    pieces.append(piece)
                frame = pd.concat(pieces).sort_values("Date").reset_index(drop=True)
        values = pd.to_datetime(frame["Date"])
        end = pd.Timestamp(request.end)
        if len(request.end) == 10:
            end += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        frame = frame.loc[
            values.between(pd.Timestamp(request.start), end)
        ].reset_index(drop=True)
        metadata = {"vendor": "test"}
        if dataset == Dataset.SECURITY_TRADING_STATUS.value:
            evidence = coverage(request, pd.DataFrame({"Date": pd.bdate_range(request.start, request.end)}))
            dates = sorted(set(evidence["expected_dates"]) | set(evidence["suspended_dates"]))
            return pd.DataFrame({"Date": dates, "Status": ["SUSPENDED" if day in suspended_dates else "TRADING" for day in dates]}), {"vendor": "test", "daily_session_coverage": evidence}
        if dataset == Dataset.SECURITY_PRICE_LIMITS.value:
            metadata.update(
                vendor_symbol=request.symbol, vendor_interface="etf_limit" if asset_type == "etf" else "stk_limit", asset_type=asset_type,
                adjustment="none", frequency="daily", source_calendar="SSE",
                available_at="same-session pre-open source schedule; historical publication unverified",
                source_publication_timestamp_verified=False, historical_revision_history_verified=False,
                daily_session_coverage=coverage(request, frame),
            )
        if dataset in {Dataset.ETF_OHLCV.value, Dataset.STOCK_OHLCV.value} and hfq_factors is not None:
            metadata["adjustment"] = "hfq"
        if dataset == Dataset.ETF_SHARE_SIZE.value:
            metadata["vendor_symbol"] = request.symbol
        if dataset in {Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value,
                       Dataset.STOCK_UNADJUSTED_DAILY.value, Dataset.STOCK_UNADJUSTED_INTRADAY.value}:
            metadata["adjustment"] = "none"
        if dataset in {Dataset.ETF_UNADJUSTED_INTRADAY.value, Dataset.STOCK_UNADJUSTED_INTRADAY.value}:
            from dataflows.contract import ETF_INTRADAY_OBSERVATION_RULE

            frame["AvailableDate"] = frame["Date"]
            metadata.update(
                availability_time_field="AvailableDate", available_at=ETF_INTRADAY_OBSERVATION_RULE,
                availability_basis="MARKET_BAR_CLOSE_ASSUMPTION",
                source_publication_timestamp_verified=False,
                historical_revision_history_verified=False, live_feed_latency_verified=False,
            )
        if dataset in {Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                       Dataset.ETF_UNADJUSTED_INTRADAY.value, Dataset.STOCK_OHLCV.value,
                       Dataset.STOCK_UNADJUSTED_DAILY.value, Dataset.STOCK_UNADJUSTED_INTRADAY.value}:
            start_day = pd.Timestamp(request.start).normalize()
            end_day = pd.Timestamp(request.end).normalize()
            anchor_dates = pd.to_datetime(market["Date"]).dt.normalize()
            anchor = market.loc[anchor_dates.between(start_day, end_day)].reset_index(drop=True)
            if dataset in {Dataset.ETF_OHLCV.value, Dataset.STOCK_OHLCV.value} and hfq_factors is not None:
                anchor = frame.copy()
            calendar = coverage(request, anchor)
            evidence = build_quality_evidence(
                anchor, intraday=frame if request.frequency == "30m" else None,
                frequency=request.frequency, expected_dates=calendar["expected_dates"],
            )
            metadata.update(
                daily_session_coverage=calendar,
                ohlcv_quality_evidence=bind_quality_frame(evidence, frame,
                    adjustment=metadata.get("adjustment", "none")),
            )
            frame.attrs.update({key: deepcopy(metadata[key]) for key in (
                "daily_session_coverage", "ohlcv_quality_evidence",
            )})
        return frame, metadata

    from czsc_trader.temp_workspace import create_temporary_directory
    root = base_dir if base_dir is not None else create_temporary_directory(Path.cwd(), "test-dataflows")
    flows = Dataflows(
        base_dir=root, space=space if space is not None else DataSpace(Path("research/S900/assets/data")),
        providers=ProviderConfig(bindings={dataset: ProviderBinding("synthetic", "v1", fetch)
            for dataset in (Dataset.ETF_SHARE_SIZE, Dataset.ETF_OHLCV,
                            Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                            Dataset.STOCK_OHLCV, Dataset.STOCK_UNADJUSTED_DAILY, Dataset.STOCK_UNADJUSTED_INTRADAY,
                            Dataset.TRADING_CALENDAR, Dataset.SECURITY_TRADING_STATUS, Dataset.SECURITY_PRICE_LIMITS)}),
    )
    return flows


def _execution_data(flows, root, sessions):
    from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
    return _prepare_backtest_execution_data(
        repository_root=root, symbol="588080.SH", asset_type="etf",
        start=sessions[1].date(), end=sessions[-1].date(), dataflows=flows,
        intraday_frequencies=("30m",),
    )


def _execute(
    source: StrategyCandidate | StrategyRelease,
    data_dir,
    monkeypatch,
    *,
    source_root=None,
    runtime_binding=None,
):
    sessions = pd.bdate_range("2026-09-14", periods=5)
    inputs = {"flow": pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.2, 0.9, 0.0]})}
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    flows = _install_candidate_dataflows(monkeypatch, inputs["flow"], daily,
        space=DataSpace(Path("research") / source.strategy_family_id / "data"))
    runtime = StrategyRuntime(dataflows=flows)
    strategy = runtime.create(
        StrategyInit(
            source,
            TradableWindow(sessions[1].date(), sessions[-1].date()),
            data_dir,
            source_root=source_root,
            runtime_binding=runtime_binding,
        )
    )
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    channel = HistoricalExecutor(
        strategy_reference=strategy.definition.release_id,
        symbol=strategy.identity.symbol,
        execution_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "open", "high", "low", "close"]),
        evaluation_start=sessions[1],
        evaluation_end=sessions[-1],
        initial_cash=100_000,
        execution_policy=from_record(ChannelPolicy, to_record(strategy.definition.execution)),
        order_types=strategy.definition.capabilities.order_types,
    )
    history = strategy.inspect_signals()
    return history, replay_sessions(strategy, ObservationExecutor(strategy.definition, channel))


@pytest.fixture
def managed_evaluation(request, tmp_path, frozen_seed_root, monkeypatch):
    from managed_evaluation_support import managed_evaluation as prepare_managed
    return prepare_managed.__wrapped__(request, tmp_path, frozen_seed_root, monkeypatch)


def test_TDR_04_C02_retired_candidate_backtest_rejected_before_execution(managed_evaluation, monkeypatch):
    from czsc_trader.application import run_backtest, BacktestRequest
    from czsc_trader.application import backtest_service
    context, request = managed_evaluation
    def forbidden(*args, **kwargs):
        raise AssertionError('retired candidate backtest must not compute')
    monkeypatch.setattr(backtest_service, '_run_backtest', forbidden)
    window = request.windows[0]
    with pytest.raises(TypeError, match='frozen StrategyVersion'):
        run_backtest(context, request.strategy, BacktestRequest(request.symbol, request.asset_type,
            window.start, window.end, request.initial_cash, 100))
