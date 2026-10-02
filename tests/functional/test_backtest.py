"""Backtest acceptance against a freshly frozen current-contract fixture."""
from datetime import date
import json
import re
import pandas as pd
import pytest
from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from czsc_trader.backtesting import resolve_registered_strategy
from czsc_trader.backtesting.srt_bridge import srt_data_directory
from strategy_runtime import RuntimeContractError
from dataflows import Dataflows
from test_current_contracts import (
    current_frozen as current_frozen, inspection as inspection,
    completed as completed, managed_evaluation as managed_evaluation,
)


def execution_flows():
    def fetch(request):
        if str(request.dataset) == "calendar.trading_sessions":
            dates = pd.date_range(request.start, request.end)
            return pd.DataFrame({"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}), {"vendor": "test"}
        dates = pd.bdate_range(request.start, min(pd.Timestamp(request.end), pd.Timestamp("2026-09-21")))
        volume = 8000
        if request.frequency == "30m":
            dates = pd.DatetimeIndex([day + pd.Timedelta(hours=h, minutes=m) for day in dates for h, m in ((10, 0), (10, 30), (11, 0), (11, 30), (13, 30), (14, 0), (14, 30), (15, 0))])
            volume = 1000
        frame = pd.DataFrame({"Date": dates, "Open": 1., "Close": 1., "High": 1., "Low": 1., "Volume": volume, "Amount": volume, "Flow": 0.8})
        return frame, {"vendor": "test", "adjustment": "none" if "unadjusted" in str(request.dataset) else "hfq"}
    return Dataflows({name: fetch for name in ("calendar.trading_sessions", "etf.ohlcv", "etf.unadjusted_daily", "etf.share")})


def test_tdr_allocates_one_human_readable_reusable_srt_space(current_frozen):
    context, version = current_frozen
    snapshot = resolve_registered_strategy(context, version.strategy_id, version.version)
    created = srt_data_directory(context.tdr_srt_root, snapshot, "588080.SH", created_on=date(2026, 9, 22))
    assert created == context.tdr_srt_root / "S900v1_588080_260922"
    assert srt_data_directory(context.tdr_srt_root, snapshot, "588080.SH", created_on=date(2026, 9, 23)) == created
    (context.tdr_srt_root / "S900v1_588080_260921").mkdir()
    with pytest.raises(RuntimeContractError, match="multiple reusable"):
        srt_data_directory(context.tdr_srt_root, snapshot, "588080.SH")


def test_current_frozen_backtest_publishes_account_and_evidence(current_frozen, monkeypatch):
    context, version = current_frozen
    def forbidden_renderer(*args, **kwargs):
        raise AssertionError("TDR must not load strategy-owned chart code")

    monkeypatch.setattr("strategy_runtime.ChartRuntime._implementation", forbidden_renderer)
    result = run_backtest(context, version, BacktestRequest(
        "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100,
    ), dataflows=execution_flows())
    assert result.status == "PASS"
    outputs = list(context.outputs_root.glob("*/manifest.json"))
    assert len(outputs) == 1
    output = outputs[0].parent
    assert {"orders.csv", "fills.csv", "account_daily.csv", "trades.csv", "metrics.json", "chart.html", "report.md"} <= {p.name for p in output.iterdir()}
    account = pd.read_csv(output / "account_daily.csv")
    assert account.iloc[0]["cash_before"] == 100000
    orders = pd.read_csv(output / "orders.csv")
    assert orders["quantity"].mod(100).eq(0).all()
    manifest = json.loads(outputs[0].read_text())
    assert manifest["audit"]["status"] == "PASS"
    assert manifest["application"]["runtime_engine"] == "srt"
    html = (output / "chart.html").read_text(encoding="utf-8")
    assert 'tdr-backtest-chart' in html
    assert 'data-range="all" aria-pressed="true"' in html
    assert 'forward-svg' in html and 'Plotly.newPlot' not in html
    report = (output / "report.md").read_text(encoding="utf-8")
    assert '| 策略 | 收益率 | 最大回撤 | 闭合交易数 | 卡玛比率 | 盈亏比 |' in report
    assert '夏普率' not in report
    cards = re.findall(r'<div class="backtest-metric"><span>(.*?)</span><strong>(.*?)</strong></div>', html)
    row = next(line for line in report.splitlines() if line.startswith(f'| {version.release_id} |'))
    assert [value for _, value in cards] == [x.strip() for x in row.split('|')[2:-1]]
    ma_html = (output / "ma_chart.html").read_text(encoding="utf-8")
    assert 'forward-svg' in ma_html and 'Plotly.newPlot' not in ma_html
    ma_cards = re.findall(r'<div class="backtest-metric"><span>(.*?)</span><strong>(.*?)</strong></div>', ma_html)
    ma_row = next(line for line in report.splitlines() if line.startswith('| MA5/MA20 |'))
    assert [value for _, value in ma_cards] == [x.strip() for x in ma_row.split('|')[2:-1]]


def test_chart_failure_prevents_backtest_publication(current_frozen, monkeypatch):
    context, version = current_frozen

    def invalid_chart(*args, **kwargs):
        raise ValueError("chart facts are inconsistent")

    monkeypatch.setattr("czsc_trader.backtesting.service.build_backtest_chart_context", invalid_chart)
    with pytest.raises(ExecutionError, match="chart facts are inconsistent"):
        run_backtest(context, version, BacktestRequest(
            "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100,
        ), dataflows=execution_flows())
    assert not list(context.outputs_root.glob("*/manifest.json"))


def test_backtest_rejects_unpublished_session_without_outputs(current_frozen):
    context, version = current_frozen
    with pytest.raises(ExecutionError):
        run_backtest(context, version, BacktestRequest(
            "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 30), 100000, 100,
        ), dataflows=execution_flows())
    assert not list(context.outputs_root.glob("*/manifest.json"))
