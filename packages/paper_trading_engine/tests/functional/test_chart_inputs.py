from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from dataflows import Dataset, PreparePolicy

from paper_trading_engine.chart_market_data import AccountChartMarketData


def test_chart_market_data_reads_adjusted_bars_without_strategy_instance() -> None:
    requests = []
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "Open": [1.0, 1.1],
            "High": [1.2, 1.3],
            "Low": [0.9, 1.0],
            "Close": [1.1, 1.2],
        }
    )

    reference = object()

    def prepare(values, *, policy):
        assert policy is PreparePolicy.REUSE
        assert len(values) == 1
        return SimpleNamespace(ready=True, reference=reference)

    def fetch(request, *, prepared):
        assert prepared is reference
        requests.append(request)
        return SimpleNamespace(ready=True, dataframe=frame, error=None, status="READY")

    source = AccountChartMarketData(
        dataflows=SimpleNamespace(prepare=prepare, fetch=fetch),
        today=lambda: pd.Timestamp("2026-09-20").date(),
    )

    identity, actual = source.history(
        symbol="588080.SH",
        asset="etf",
        selection_data_cutoff="2026-09-02",
        context_sessions=60,
    )

    assert len(identity) == 64
    assert actual.equals(frame)
    assert len(requests) == 1
    request = requests[0]
    assert request.dataset == Dataset.ETF_OHLCV
    assert request.symbol == "588080.SH"
    assert request.end == "2026-09-20"
    assert request.required_cutoff == "2026-09-02"
