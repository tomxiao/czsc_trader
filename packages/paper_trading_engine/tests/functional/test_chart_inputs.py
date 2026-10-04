from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from dataflows import Dataflows, DataSpace, Dataset, PreparePolicy, ProviderBinding, ProviderConfig

from paper_trading_engine.chart_market_data import AccountChartMarketData
from paper_trading_engine.trading_window import SHANGHAI


def test_chart_market_data_refreshes_completed_sessions_and_preserves_bound_assets(tmp_path) -> None:
    clock = [datetime(2026, 9, 4, 14, 59, tzinfo=SHANGHAI)]
    source = {"published": pd.Timestamp("2026-09-03"), "price": 1.0}
    price_requests = []
    holiday = pd.Timestamp("2026-09-07")

    def calendar(request):
        dates = pd.date_range(request.start, request.end)
        return pd.DataFrame({
            "Date": dates, "IsOpen": ((dates.dayofweek < 5) & (dates != holiday)).astype(int),
        }), {"vendor": "synthetic"}

    def prices(request):
        price_requests.append(request)
        dates = pd.bdate_range(request.start, min(pd.Timestamp(request.end), source["published"]))
        dates = dates[dates != holiday]
        return pd.DataFrame({
            "Date": dates, "Open": source["price"], "High": source["price"] + 0.1,
            "Low": source["price"] - 0.1, "Close": source["price"],
            "Volume": 100.0, "Amount": source["price"] * 100.0,
        }), {"vendor": "synthetic"}

    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path("market")), providers=ProviderConfig(bindings={
        Dataset.TRADING_CALENDAR: ProviderBinding("synthetic", "v1", calendar),
        Dataset.ETF_OHLCV: ProviderBinding("synthetic", "v1", prices),
    }))
    source_port = AccountChartMarketData(dataflows=flows, now=lambda: clock[0])
    arguments = dict(symbol="588080.SH", asset="etf", selection_data_cutoff="2026-09-02", context_sessions=60)
    first_hash, first = source_port.history(**arguments)
    assert len(first_hash) == 64 and first.Date.max() == pd.Timestamp("2026-09-03")
    request = price_requests[-1]
    pinned = flows.prepare((request,), policy=PreparePolicy.REUSE).reference
    assert request.end == "2026-09-03"

    # Redrawing uses prepared assets; explicit refresh fetches the source even on the same day.
    source["price"] = 1.5
    assert source_port.history(**arguments)[0] == first_hash
    assert len(price_requests) == 1
    refreshed_hash, refreshed = source_port.history(**arguments, refresh_source=True)
    assert refreshed_hash != first_hash and refreshed.Close.iloc[-1] == 1.5
    assert len(price_requests) == 2
    assert flows.fetch(request, prepared=pinned).dataframe.equals(first)

    # The close advances the required cutoff. Delayed publication fails, then recovers
    # from the supplier on the same day instead of pinning a stale successful result.
    clock[0] = datetime(2026, 9, 4, 15, 0, tzinfo=SHANGHAI)
    with pytest.raises(ValueError, match="preparation failed"):
        source_port.history(**arguments)
    source["published"] = pd.Timestamp("2026-09-04")
    _, friday = source_port.history(**arguments)
    assert friday.Date.max() == pd.Timestamp("2026-09-04")
    calls = len(price_requests)
    for day in (5, 7):
        clock[0] = datetime(2026, 9, day, 16, 0, tzinfo=SHANGHAI)
        assert source_port.history(**arguments)[1].equals(friday)
    assert len(price_requests) == calls

    # Holiday-aware pre-close selection excludes the current unfinished daily bar.
    source["published"] = pd.Timestamp("2026-09-08")
    clock[0] = datetime(2026, 9, 8, 14, 0, tzinfo=SHANGHAI)
    assert source_port.history(**arguments)[1].Date.max() == pd.Timestamp("2026-09-04")
    clock[0] = datetime(2026, 9, 8, 15, 0, tzinfo=SHANGHAI)
    assert source_port.history(**arguments)[1].Date.max() == pd.Timestamp("2026-09-08")
    assert price_requests[-1].end == "2026-09-08"
    assert flows.fetch(request, prepared=pinned).dataframe.equals(first)
