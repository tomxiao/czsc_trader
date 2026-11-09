from __future__ import annotations

import pandas as pd
import pytest

from dataflows.errors import DataContractError
from dataflows.tushare_strategy_data import (
    fetch_etf_share_size,
    fetch_vix_daily,
    fetch_index_daily_basic,
    fetch_shibor_daily,
    fetch_stock_moneyflow,
    fetch_trading_calendar,
)


class FakePro:
    def shibor(self, **kwargs):
        return pd.DataFrame({"date": ["20260915"], "on": [1.25]})

    def index_dailybasic(self, **kwargs):
        return pd.DataFrame({"trade_date": ["20260915"], "turnover_rate_f": [2.5]})

    def etf_share_size(self, **kwargs):
        return pd.DataFrame({"trade_date": ["20260915"], "total_share": [123.0]})

    def index_global(self, **kwargs):
        return pd.DataFrame({"trade_date": ["20260915"], "pct_chg": [1.5]})

    def index_weight(self, **kwargs):
        return pd.DataFrame(
            {
                "trade_date": ["20260915", "20260915"],
                "con_code": ["000001.SZ", "600000.SH"],
                "weight": [40.0, 60.0],
            }
        )

    def moneyflow(self, **kwargs):
        trade_date = kwargs.get("trade_date", "20260915")
        return pd.DataFrame(
            {
                "trade_date": [trade_date, trade_date],
                "ts_code": ["000001.SZ", "600000.SH"],
                "net_mf_amount": [10.0, -5.0],
            }
        )

    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            {
                "cal_date": ["20260915", "20260916"],
                "is_open": [1, 1],
                "pretrade_date": ["20260914", "20260915"],
            }
        )


class ChunkedShiborPro:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def shibor(self, **kwargs):
        self.calls.append(kwargs)
        return pd.DataFrame({"date": [kwargs["start_date"]], "on": [1.25]})


class ChunkedGlobalPro:
    def __init__(self) -> None:
        self.index_calls: list[dict[str, str]] = []
        self.vix_calls: list[dict[str, str]] = []

    def index_global(self, **kwargs):
        self.index_calls.append(kwargs)
        dates = pd.bdate_range(kwargs["start_date"], kwargs["end_date"])
        return pd.DataFrame({"trade_date": dates.strftime("%Y%m%d"), "pct_chg": 1.5})

    def vix_index(self, **kwargs):
        self.vix_calls.append(kwargs)
        return pd.DataFrame(
            {
                "trade_date": [kwargs["start_date"]],
                "open": [20.0],
                "high": [22.0],
                "low": [19.0],
                "close": [21.0],
                "pct_change": [5.0],
            }
        )


def test_DFLS_34_C01_shibor_long_history_is_split_by_calendar_year() -> None:
    pro = ChunkedShiborPro()

    frame, metadata = fetch_shibor_daily("2024-12-31", "2026-01-01", pro=pro)

    assert frame["Date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2024-12-31",
        "2025-01-01",
        "2026-01-01",
    ]
    assert [call["start_date"] for call in pro.calls] == [
        "20241231",
        "20250101",
        "20260101",
    ]
    assert metadata["maximum_start_lag_days"] == 10


def test_DFLS_34_C11_vix_dataset_rejects_other_symbols() -> None:
    with pytest.raises(DataContractError, match="only supports symbol VIX"):
        fetch_vix_daily("VXN", "2026-09-15", "2026-09-15", pro=ChunkedGlobalPro())


def test_DFLS_34_C04_all_market_moneyflow_rejects_unsafe_multi_day_request() -> None:
    with pytest.raises(DataContractError, match="exactly one day"):
        fetch_stock_moneyflow("2026-09-14", "2026-09-15", pro=FakePro())


def test_DFLS_34_C12_trading_calendar_is_canonical() -> None:
    calendar, metadata = fetch_trading_calendar("SSE", "2026-09-15", "2026-09-16", pro=FakePro())

    assert list(calendar.columns) == ["Date", "IsOpen", "PreviousTradingDate"]
    assert calendar["IsOpen"].tolist() == [1, 1]
    assert metadata["exchange"] == "SSE"


def test_DFLS_34_C03_moneyflow_panel_preserves_two_symbols():
    frame, meta = fetch_stock_moneyflow("2026-09-15", "2026-09-15", pro=FakePro())
    assert frame.Symbol.tolist() == ["000001.SZ", "600000.SH"]
    assert meta["primary_key"] == ["Date", "Symbol"]
    assert frame.NetMoneyflowAmount.tolist() == [10.0, -5.0]


def test_DFLS_34_C05_share_size_is_not_ohlcv():
    frame, meta = fetch_etf_share_size("588080.SH", "2026-09-15", "2026-09-15", pro=FakePro())
    assert frame.TotalShare.tolist() == [123.0]
    assert "Open" not in frame and "Close" not in frame
    assert meta["availability_rule"] == "T+1 08:30 Asia/Shanghai"


def test_DFLS_34_C06_index_indicator_is_not_ohlcv():
    frame, _ = fetch_index_daily_basic("399006.SZ", "2026-09-15", "2026-09-15", pro=FakePro())
    assert frame.TurnoverRateFreeFloat.tolist() == [2.5]
    assert "Open" not in frame and "Close" not in frame


def test_DFLS_34_C10_vix_yearly_units_and_availability():
    pro = ChunkedGlobalPro()
    frame, meta = fetch_vix_daily("VIX", "2024-12-31", "2026-01-01", pro=pro)
    assert [c["start_date"] for c in pro.vix_calls] == ["20241231", "20250101", "20260101"]
    assert frame.Close.tolist() == [21.0] * 3
    assert frame.PercentChange.tolist() == [0.05] * 3
    assert meta["availability_rule"].startswith("US close date")
