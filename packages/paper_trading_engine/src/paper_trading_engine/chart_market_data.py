"""Strategy-independent market data for PTE observation charts."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Callable

from dataflows import DataRequest, Dataflows, Dataset, PreparePolicy, canonical_frame_sha256
import pandas as pd

from .trading_window import SHANGHAI, shanghai_now


class AccountChartMarketData:
    """Read adjusted daily bars without creating or inspecting a strategy instance."""

    def __init__(
        self,
        *,
        dataflows: Dataflows,
        now: Callable[[], datetime] = shanghai_now,
    ) -> None:
        self.dataflows = dataflows
        self.now = now

    def history(
        self,
        *,
        symbol: str,
        asset: str,
        selection_data_cutoff: str,
        context_sessions: int,
        refresh_source: bool = False,
    ) -> tuple[str, object]:
        normalized_asset = asset.lower()
        if normalized_asset not in {"stock", "etf"}:
            raise ValueError("account chart asset must be stock or etf")
        cutoff = date.fromisoformat(selection_data_cutoff)
        moment = self.now()
        if moment.tzinfo is None:
            raise ValueError("account chart clock must be timezone-aware")
        moment = moment.astimezone(SHANGHAI)
        start = cutoff - timedelta(days=max(180, context_sessions * 3))
        policy = PreparePolicy.REFRESH if refresh_source else PreparePolicy.REUSE
        symbol = symbol.upper()
        exchange = {"SH": "SSE", "SZ": "SZSE"}.get(symbol.rsplit(".", 1)[-1])
        if exchange is None:
            raise ValueError("account chart symbol must identify an SH or SZ exchange")
        calendar = self._read(DataRequest(
            Dataset.TRADING_CALENDAR, exchange, start.isoformat(),
            moment.date().isoformat(), moment.date().isoformat(), "daily",
        ), policy)
        sessions = pd.to_datetime(calendar.loc[calendar["IsOpen"].eq(1), "Date"]).dt.date
        sessions = sessions[sessions <= moment.date()] if moment.time() >= time(15) else sessions[sessions < moment.date()]
        if sessions.empty:
            raise ValueError("account chart calendar has no completed trading session")
        end = sessions.iloc[-1]
        if cutoff > end:
            raise ValueError("account selection cutoff exceeds the latest completed trading session")
        dataset = Dataset.ETF_OHLCV if normalized_asset == "etf" else Dataset.STOCK_OHLCV
        request = DataRequest(
            dataset,
            symbol,
            start.isoformat(),
            end.isoformat(),
            end.isoformat(),
            "daily",
        )
        frame = self._read(request, policy)
        return canonical_frame_sha256(frame), frame

    def _read(self, request: DataRequest, policy: PreparePolicy) -> pd.DataFrame:
        prepared = self.dataflows.prepare((request,), policy=policy)
        if not prepared.ready:
            raise ValueError(f"account chart data preparation failed: {prepared.items}")
        result = self.dataflows.fetch(request, prepared=prepared.reference)
        if not result.ready:
            message = result.error.message if result.error is not None else result.status
            raise ValueError(f"account chart market data is unavailable: {message}")
        frame = result.dataframe.copy()
        if frame.empty:
            raise ValueError("account chart market data is empty")
        return frame
