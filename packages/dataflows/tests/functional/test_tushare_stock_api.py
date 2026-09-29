"""A-share bars reuse the explicit Tushare client without profile writes."""

from __future__ import annotations

import pandas as pd

from dataflows import tushare_stock


def test_stock_daily_pro_bar_receives_explicit_api(monkeypatch) -> None:
    client = object()
    calls: list[dict] = []
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _env: client)

    def fake_pro_bar(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([{
            "ts_code": "600406.SH", "trade_date": "20260928",
            "open": 24.0, "high": 24.5, "low": 23.8, "close": 24.2,
            "vol": 100.0, "amount": 240.0,
        }])

    monkeypatch.setattr(tushare_stock.ts, "pro_bar", fake_pro_bar)

    bars, market, symbol = tushare_stock._fetch_tushare_ohlcv(
        "600406.SH", "2026-09-28", "2026-09-28", env_file=".env"
    )

    assert len(calls) == 1
    assert calls[0]["api"] is client
    assert calls[0]["ts_code"] == "600406.SH"
    assert calls[0]["freq"] == "D"
    assert calls[0]["asset"] == "E"
    assert (market, symbol) == (tushare_stock.MARKET_A_SHARE, "600406.SH")
    assert bars.loc[0, "Close"] == 24.2


def test_stock_minute_prefers_trade_time_over_pro_bar_derived_trade_date() -> None:
    raw = pd.DataFrame([{
        "ts_code": "600089.SH", "trade_time": "2025-03-03 09:35:00",
        "trade_date": "20250303", "open": 10.0, "high": 10.2,
        "low": 9.9, "close": 10.1, "vol": 100.0, "amount": 1000.0,
    }])

    bars = tushare_stock._standardize_a_share_tushare_ohlcv(raw, intraday=True)

    assert bars["Date"].tolist() == ["2025-03-03 09:35:00"]
    assert bars.loc[0, "Close"] == 10.1
    assert "trade_date" in raw.columns
