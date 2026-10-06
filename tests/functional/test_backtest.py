"""Backtest acceptance against an isolated current-contract frozen fixture."""
from datetime import date
from dataclasses import replace
from copy import deepcopy
import re
import pandas as pd
import pytest
from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from dataflows import Dataflows, DataSpace, ProviderConfig, ProviderBinding, Dataset
from pathlib import Path
from public_backtest_support import assert_public_charts, research_context, render_output
from test_current_contracts import (
    current_frozen as current_frozen, inspection as inspection,
    completed as completed, managed_evaluation as managed_evaluation,
)


def execution_flows(root, *, adjusted_price=1., procurement=None):
    from dataflows.ohlcv_quality import (
        bind_quality_frame, build_quality_evidence, verify_daily_sessions,
    )

    class SyntheticCalendar:
        def fund_basic(self, *, ts_code, fields):
            return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20200101"]})

        def trade_cal(self, *, exchange, start_date, end_date):
            dates = pd.date_range(start_date, end_date)
            return pd.DataFrame({"cal_date": dates.strftime("%Y%m%d"),
                                 "is_open": (dates.weekday < 5).astype(int)})

    def fetch(request):
        if procurement is not None:
            if not procurement["allowed"]:
                pytest.fail("warm backtest must reuse its pinned inputs without supplier access")
            procurement["requests"].append(request)
        if str(request.dataset) == "calendar.trading_sessions":
            dates = pd.date_range(request.start, request.end)
            return pd.DataFrame({"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}), {"vendor": "test"}
        dates = pd.bdate_range(request.start, min(pd.Timestamp(request.end), pd.Timestamp("2026-09-21")))
        daily_dates = dates
        volume = 8000
        if request.frequency == "30m":
            dates = pd.DatetimeIndex([day + pd.Timedelta(hours=h, minutes=m) for day in dates for h, m in ((10, 0), (10, 30), (11, 0), (11, 30), (13, 30), (14, 0), (14, 30), (15, 0))])
            volume = 1000
        price = 1. if "unadjusted" in str(request.dataset) else adjusted_price
        frame = pd.DataFrame({"Date": dates, "Open": price, "Close": price, "High": price, "Low": price, "Volume": volume, "Amount": volume * price, "Flow": 0.8, "TotalShare": 1.0})
        metadata = {"vendor": "test", "adjustment": "none" if "unadjusted" in str(request.dataset) else "hfq"}
        if request.dataset is Dataset.ETF_UNADJUSTED_INTRADAY:
            from dataflows.contract import ETF_INTRADAY_OBSERVATION_RULE

            frame["AvailableDate"] = frame["Date"]
            metadata.update(
                availability_time_field="AvailableDate", available_at=ETF_INTRADAY_OBSERVATION_RULE,
                availability_basis="MARKET_BAR_CLOSE_ASSUMPTION",
                source_publication_timestamp_verified=False,
                historical_revision_history_verified=False, live_feed_latency_verified=False,
            )
        if request.dataset in {
            Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
        }:
            anchor = pd.DataFrame({"Date": daily_dates, "Open": price, "Close": price,
                                   "High": price, "Low": price, "Volume": 8000,
                                   "Amount": 8000 * price})
            calendar = verify_daily_sessions(
                SyntheticCalendar(), request.symbol, anchor,
                start=request.start, end=request.end,
            )
            evidence = build_quality_evidence(
                anchor, intraday=frame if request.frequency == "30m" else None,
                frequency=request.frequency, expected_dates=calendar["expected_dates"],
            )
            metadata.update(daily_session_coverage=calendar,
                            ohlcv_quality_evidence=bind_quality_frame(
                                evidence, frame, adjustment=metadata["adjustment"],
                            ))
            frame.attrs.update({key: deepcopy(metadata[key]) for key in (
                "daily_session_coverage", "ohlcv_quality_evidence",
            )})
        return frame, metadata
    return Dataflows(base_dir=root, space=DataSpace(Path("research/S900/data")),
                    providers=ProviderConfig(bindings={name: ProviderBinding("backtest-fixture", "v1", fetch)
                        for name in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                                     Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                                     Dataset.ETF_SHARE_SIZE)}))


def test_current_frozen_backtest_returns_audited_accounts_and_reuses_batch_data(current_frozen):
    repository, version = current_frozen
    procurement = {"allowed": True, "requests": []}
    context = research_context(repository, execution_flows(repository.root, adjusted_price=2., procurement=procurement))
    request = BacktestRequest("588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100)
    result = run_backtest(context, version, request)
    assert result.manifest["audit"]["status"] == "PASS"
    assert not (repository.root / "outputs").exists()
    assert not (repository.root / "data/backtest").exists()
    assert not list((repository.root / "research").glob("*/experiments/*/evidence/*"))
    assert result.result.account_daily.iloc[0]["cash_before"] == 100000
    assert result.result.orders["quantity"].mod(100).eq(0).all()
    assert len(result.result.observations) == len(result.result.decisions)
    assert all(item.strategy.release_hash == version.release_hash for item in result.result.observations)
    output = render_output(result, repository.root)
    payload = assert_public_charts(output)
    assert payload["market_data"]["bars"][0]["close"] == 2.
    assert payload["execution"]["fills"][0]["price"] == 1.
    report = (output / "report.md").read_text(encoding="utf-8")
    html = (output / "chart.html").read_text(encoding="utf-8")
    cards = re.findall(r'<div class="backtest-metric"><span>(.*?)</span><strong>(.*?)</strong></div>', html)
    row = next(line for line in report.splitlines() if line.startswith(f'| {version.release_id} |'))
    assert [value for _, value in cards] == [x.strip() for x in row.split('|')[2:-1]]
    original_requests = tuple(procurement["requests"])
    procurement["allowed"] = False
    repeated = run_backtest(context, version, request)
    assert repeated.metrics == result.metrics
    assert repeated.manifest["execution_data"] == result.manifest["execution_data"]
    assert tuple(procurement["requests"]) == original_requests
    procurement["allowed"] = True
    weekend = run_backtest(context, version, replace(request, end=date(2026, 9, 20)))
    assert weekend.manifest["request"]["end"] == "2026-09-20"
    assert weekend.manifest["execution_data"]["cutoff"] == "2026-09-18"


def test_chart_generation_is_explicit_and_cannot_block_account_computation(current_frozen, monkeypatch):
    from czsc_trader.backtesting.service import _backtest_report_files
    repository, version = current_frozen
    context = research_context(repository, execution_flows(repository.root))
    def invalid_chart(*args, **kwargs):
        raise ValueError("chart facts are inconsistent")
    monkeypatch.setattr("czsc_trader.backtesting.service.build_backtest_chart_context", invalid_chart)
    result = run_backtest(context, version, BacktestRequest(
        "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100))
    assert result.manifest["audit"]["status"] == "PASS"
    with pytest.raises(ValueError, match="chart facts are inconsistent"):
        _backtest_report_files(result)
    assert not (repository.root / "outputs").exists()


def test_backtest_rejects_unpublished_session_without_outputs(current_frozen):
    repository, version = current_frozen
    context = research_context(repository, execution_flows(repository.root))
    with pytest.raises(ExecutionError):
        run_backtest(context, version, BacktestRequest(
            "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 30), 100000, 100))
    assert not (repository.root / "outputs").exists()
