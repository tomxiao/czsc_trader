"""Backtest acceptance against an isolated current-contract frozen fixture."""
from datetime import date
import json
import re
import pandas as pd
import pytest
from czsc_trader.application import BacktestRequest, run_backtest
from czsc_trader.application.errors import ExecutionError
from dataflows import Dataflows, DataSpace, ProviderConfig, ProviderBinding, Dataset
from pathlib import Path
from public_backtest_support import assert_public_charts
from test_current_contracts import (
    current_frozen as current_frozen, inspection as inspection,
    completed as completed, managed_evaluation as managed_evaluation,
)


def execution_flows(root, *, adjusted_price=1., procurement=None):
    def fetch(request):
        if procurement is not None:
            if not procurement["allowed"]:
                pytest.fail("warm backtest must reuse its pinned inputs without supplier access")
            procurement["requests"].append(request)
        if str(request.dataset) == "calendar.trading_sessions":
            dates = pd.date_range(request.start, request.end)
            return pd.DataFrame({"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}), {"vendor": "test"}
        dates = pd.bdate_range(request.start, min(pd.Timestamp(request.end), pd.Timestamp("2026-09-21")))
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
        return frame, metadata
    return Dataflows(base_dir=root, space=DataSpace(Path("data/backtest")),
                    providers=ProviderConfig(bindings={name: ProviderBinding("backtest-fixture", "v1", fetch)
                        for name in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                                     Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                                     Dataset.ETF_SHARE_SIZE)}))


def test_current_frozen_backtest_publishes_account_and_evidence(current_frozen, monkeypatch):
    context, version = current_frozen
    procurement = {"allowed": True, "requests": []}
    monkeypatch.setattr("czsc_trader.backtesting._dataflows.create_backtest_dataflows", lambda repository_root, **kwargs: execution_flows(repository_root, adjusted_price=2., procurement=procurement))
    result = run_backtest(context, version, BacktestRequest(
        "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100,
    ))
    assert result.status == "PASS"
    assert (context.root / "data/backtest").is_dir()
    assert not (context.root / "data/backtest/market").exists()
    outputs = list(context.outputs_root.glob("*/manifest.json"))
    assert len(outputs) == 1
    output = Path(result.artifacts["output_dir"])
    assert output == outputs[0].parent
    assert {"orders.csv", "fills.csv", "account_daily.csv", "trades.csv", "metrics.json", "chart.html", "report.md"} <= {p.name for p in output.iterdir()}
    from strategy_runtime import StrategyObservation
    observations = [StrategyObservation.from_dict(item) for item in json.loads((output / 'observations.json').read_text(encoding='utf-8'))]
    decisions = pd.read_csv(output / 'decisions.csv')
    assert len(observations) == len(decisions)
    assert {'DEC-' + item.plan_identity[:20].upper() for item in observations} == set(decisions['decision_id'])
    assert all(item.strategy.release_hash == version.release_hash for item in observations)
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
    assert '| 策略 | 收益率 | 最大回撤 | 闭合交易数 | 卡玛比率 | 盈亏比 | 交易胜率 |' in report
    assert '夏普率' not in report
    cards = re.findall(r'<div class="backtest-metric"><span>(.*?)</span><strong>(.*?)</strong></div>', html)
    row = next(line for line in report.splitlines() if line.startswith(f'| {version.release_id} |'))
    assert [value for _, value in cards] == [x.strip() for x in row.split('|')[2:-1]]
    ma_html = (output / "ma_chart.html").read_text(encoding="utf-8")
    assert 'forward-svg' in ma_html and 'Plotly.newPlot' not in ma_html
    ma_cards = re.findall(r'<div class="backtest-metric"><span>(.*?)</span><strong>(.*?)</strong></div>', ma_html)
    ma_row = next(line for line in report.splitlines() if line.startswith('| MA5/MA20 |'))
    assert [value for _, value in ma_cards] == [x.strip() for x in ma_row.split('|')[2:-1]]
    payload = assert_public_charts(output)
    assert payload["market_data"]["bars"][0]["close"] == 2.
    assert payload["execution"]["fills"][0]["price"] == 1.

    original_inputs = manifest["execution_data"]
    original_requests = tuple(procurement["requests"])
    assert original_requests
    procurement["allowed"] = False
    repeated = run_backtest(context, version, BacktestRequest(
        "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100,
    ))
    assert repeated.status == "PASS"
    assert repeated.artifacts["output_dir"] != result.artifacts["output_dir"]
    repeated_manifest = json.loads((Path(repeated.artifacts["output_dir"]) / "manifest.json").read_text())
    assert repeated_manifest["execution_data"] == original_inputs
    assert repeated_manifest["strategy"] == manifest["strategy"]
    assert repeated.result["metrics"] == result.result["metrics"]
    assert tuple(procurement["requests"]) == original_requests
    procurement["allowed"] = True
    weekend = run_backtest(context, version, BacktestRequest(
        "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 20), 100000, 100,
    ))
    assert weekend.status == "PASS"
    weekend_manifest = json.loads((Path(weekend.artifacts["output_dir"]) / "manifest.json").read_text())
    assert weekend_manifest["request"]["end"] == "2026-09-20"
    assert weekend_manifest["execution_data"]["cutoff"] == "2026-09-18"


def test_chart_failure_prevents_backtest_publication(current_frozen, monkeypatch):
    context, version = current_frozen
    monkeypatch.setattr("czsc_trader.backtesting._dataflows.create_backtest_dataflows", lambda repository_root, **kwargs: execution_flows(repository_root))

    def invalid_chart(*args, **kwargs):
        raise ValueError("chart facts are inconsistent")

    monkeypatch.setattr("czsc_trader.backtesting.service.build_backtest_chart_context", invalid_chart)
    with pytest.raises(ExecutionError, match="chart facts are inconsistent"):
        run_backtest(context, version, BacktestRequest(
            "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 21), 100000, 100,
        ))
    assert not list(context.outputs_root.glob("*/manifest.json"))


def test_backtest_rejects_unpublished_session_without_outputs(current_frozen, monkeypatch):
    context, version = current_frozen
    monkeypatch.setattr("czsc_trader.backtesting._dataflows.create_backtest_dataflows", lambda repository_root, **kwargs: execution_flows(repository_root))
    with pytest.raises(ExecutionError):
        run_backtest(context, version, BacktestRequest(
            "588080.SH", "etf", date(2026, 9, 15), date(2026, 9, 30), 100000, 100,
        ))
    assert not list(context.outputs_root.glob("*/manifest.json"))
