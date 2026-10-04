"""Strategy-independent market data for PTE observation charts."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from dataflows import DataRequest, Dataflows, Dataset, PreparePolicy, canonical_frame_sha256


class AccountChartMarketData:
    """Read adjusted daily bars without creating or inspecting a strategy instance."""

    def __init__(
        self,
        *,
        dataflows: Dataflows,
        today: Callable[[], date] | None = None,
    ) -> None:
        self.dataflows = dataflows
        self.today = today or date.today

    def history(
        self,
        *,
        symbol: str,
        asset: str,
        selection_data_cutoff: str,
        context_sessions: int,
    ) -> tuple[str, object]:
        normalized_asset = asset.lower()
        if normalized_asset not in {"stock", "etf"}:
            raise ValueError("account chart asset must be stock or etf")
        cutoff = date.fromisoformat(selection_data_cutoff)
        end = max(cutoff, self.today())
        start = cutoff - timedelta(days=max(180, context_sessions * 3))
        dataset = Dataset.ETF_OHLCV if normalized_asset == "etf" else Dataset.STOCK_OHLCV
        request = DataRequest(
            dataset,
            symbol.upper(),
            start.isoformat(),
            end.isoformat(),
            cutoff.isoformat(),
            "daily",
        )
        prepared = self.dataflows.prepare((request,), policy=PreparePolicy.REUSE)
        if not prepared.ready:
            raise ValueError(f"account chart data preparation failed: {prepared.items}")
        result = self.dataflows.fetch(request, prepared=prepared.reference)
        if not result.ready:
            message = result.error.message if result.error is not None else result.status
            raise ValueError(f"account chart market data is unavailable: {message}")
        frame = result.dataframe.copy()
        if frame.empty:
            raise ValueError("account chart market data is empty")
        return canonical_frame_sha256(frame), frame
