# Risk ownership: TDR-26
"""Backtest acceptance against an isolated current-contract frozen fixture."""
from datetime import date
from copy import deepcopy
import pandas as pd
import pytest
from czsc_trader.application import BacktestRequest, run_backtest
from dataflows import Dataflows, DataSpace, ProviderConfig, ProviderBinding, Dataset, IncompleteDataError
from pathlib import Path
from public_backtest_support import research_context
from frozen_contract_support import (
    current_frozen as current_frozen, inspection as inspection,
    completed as completed, managed_evaluation as managed_evaluation,
)


def execution_flows(root, *, adjusted_price=1., procurement=None, space=None, data_failure=None):
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
        if request.dataset is Dataset.SECURITY_TRADING_STATUS:
            proof = verify_daily_sessions(SyntheticCalendar(), request.symbol, pd.DataFrame({"Date": pd.bdate_range(request.start, request.end)}), start=request.start, end=request.end)
            return pd.DataFrame({"Date": proof["expected_dates"], "Status": "TRADING"}), {"vendor": "test", "daily_session_coverage": proof}
        if request.dataset is Dataset.ETF_OHLCV and data_failure is not None:
            raise IncompleteDataError("injected incomplete daily observations", **data_failure)
        dates = pd.bdate_range(request.start, min(pd.Timestamp(request.end), pd.Timestamp("2026-09-21")))
        if request.dataset is Dataset.SECURITY_PRICE_LIMITS:
            frame = pd.DataFrame({"Date": dates, "UpLimit": 1.2, "DownLimit": 0.8})
            calendar = verify_daily_sessions(
                SyntheticCalendar(), request.symbol, frame,
                start=request.start, end=request.end,
            )
            return frame, {
                "vendor": "test", "vendor_symbol": request.symbol,
                "vendor_interface": "etf_limit", "asset_type": "etf",
                "adjustment": "none", "frequency": "daily", "source_calendar": "SSE",
                "available_at": "same-session pre-open source schedule; historical publication unverified",
                "source_publication_timestamp_verified": False,
                "historical_revision_history_verified": False,
                "daily_session_coverage": calendar,
            }
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
    return Dataflows(base_dir=root, space=space or DataSpace(Path("research/S900/assets/data")),
                    providers=ProviderConfig(bindings={name: ProviderBinding("backtest-fixture", "v1", fetch)
                        for name in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                                     Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                                     Dataset.ETF_SHARE_SIZE, Dataset.SECURITY_TRADING_STATUS, Dataset.SECURITY_PRICE_LIMITS)}))


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
    # Restore the chart implementation and exercise explicit publication using
    # the same computed account rather than preparing/replaying a second one.
    monkeypatch.undo()
    import re
    from public_backtest_support import publish_reports

    references = publish_reports(context, result)
    report = references["report.md"].resolve(repository.root)
    links = re.findall(r"\]\(([^)]+)\)", report.read_text(encoding="utf-8"))
    assert links == [references["chart.html"].evidence_id, references["ma_chart.html"].evidence_id]
    assert all((report.parent / link).is_file() for link in links)
    again = publish_reports(context, result)
    assert {name: ref.sha256 for name, ref in again.items()} == {
        name: ref.sha256 for name, ref in references.items()
    }
    assert report.is_relative_to(repository.root / "research/S900/assets/evidence")
