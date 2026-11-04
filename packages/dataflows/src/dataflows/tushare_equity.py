"""CN backward-adjusted observations for the market-qualified equity contract."""
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .contract import EquityDataRequest, ProviderBinding
from .equity_contracts import (AssetClass, BarFrequency, EquityProduct, MarketId,
                               PriceAdjustment, ProviderKey, SourceRef, TimeInterval, TradingSession)
from .equity_data import equity_metadata, validate_equity_frame
from .errors import DataContractError, IncompleteDataError
from .ohlcv_quality import source_session_calendar
from .tushare_common import get_tushare_pro
from .tushare_etf import fetch_etf_ohlcv
from .tushare_stock import fetch_stock_ohlcv


def _sessions(coverage: dict) -> tuple[TradingSession, ...]:
    zone = ZoneInfo("Asia/Shanghai")
    days = [date.fromisoformat(row["Date"]) for row in coverage["calendar"]
            if row["is_open"] == 1 and row["Date"] >= coverage["listing_date"]]
    if not days:
        raise IncompleteDataError("requested CN interval has no listed trading sessions")
    return tuple(TradingSession(day, str(zone), tuple(
        TimeInterval(datetime.combine(day, start, zone), datetime.combine(day, end, zone))
        for start, end in ((time(9, 30), time(11, 30)), (time(13), time(15)))
    )) for day in days)


def tushare_equity_observation_bindings(*, source: SourceRef,
                                        env_file: str | Path | None = None) -> dict[ProviderKey, ProviderBinding]:
    """Bind CN stock/ETF HFQ bars and independent sessions, without execution facts.

    Existing Tushare adapters retain their factor, units, quality and publication
    contracts. RAW execution requires a separate economic-event source binding.
    """
    if type(source) is not SourceRef:
        raise TypeError("source requires SourceRef")

    def fetch(request: EquityDataRequest):
        p = request.parameters
        if p.instrument.market is not MarketId.CN or p.source != source:
            raise DataContractError("MARKET_CONTRACT_MISMATCH")
        if p.query.product not in (EquityProduct.BARS, EquityProduct.SESSIONS):
            raise DataContractError("Tushare observations provide only bars and sessions")
        if p.query.product is EquityProduct.BARS and p.query.adjustment is not PriceAdjustment.BACKWARD:
            raise DataContractError("Tushare equity observations require backward-adjusted prices")
        start, end = p.query.start.isoformat(), p.query.end.isoformat()
        if p.query.product is EquityProduct.SESSIONS:
            coverage = source_session_calendar(
                get_tushare_pro(env_file), p.instrument.symbol, start=start, end=end,
                asset_type="stock" if p.instrument.asset_class is AssetClass.STOCK else "etf")
            sessions = _sessions(coverage)
            metadata = equity_metadata(request, sessions, availability_basis="SESSION_OPEN_RESEARCH_ASSUMPTION")
            metadata.update(calendar_source="tushare.trade_cal", daily_session_coverage=coverage,
                            publication_time_verified=False)
            return pd.DataFrame({"Date": [s.segments[0].start for s in sessions],
                                 "AvailableDate": [s.segments[0].start for s in sessions],
                                 "SessionDate": [s.session_date.isoformat() for s in sessions]}), metadata

        fetch_bars = fetch_stock_ohlcv if p.instrument.asset_class is AssetClass.STOCK else fetch_etf_ohlcv
        frame, source_metadata = fetch_bars(p.instrument.symbol, start, end,
                                           period=p.query.frequency.value, env_file=env_file)
        if source_metadata.get("adjustment") != PriceAdjustment.BACKWARD.value:
            raise DataContractError("Tushare observation source returned a different adjustment")
        sessions = _sessions(source_metadata["daily_session_coverage"])
        metadata = {**source_metadata, **equity_metadata(
            request, sessions, availability_basis=source_metadata["available_at"])}
        metadata["calendar_source"] = "tushare.trade_cal"
        times = pd.to_datetime(frame.Date, errors="raise")
        if p.query.frequency is BarFrequency.DAILY:
            grid = {s.session_date: s.bars(BarFrequency.DAILY)[0] for s in sessions}
            keys = times.dt.date
        else:
            grid = {pd.Timestamp(b.end): b for s in sessions for b in s.bars(p.query.frequency)}
            keys = times.dt.tz_localize(p.instrument.timezone).dt.tz_convert("UTC")
        try:
            selected = [grid[key] for key in keys]
        except KeyError as exc:
            raise DataContractError("Tushare observation lies outside independent session grid") from exc
        result = frame.loc[:, ["Open", "High", "Low", "Close", "Volume", "Amount"]].copy()
        result["Date"] = [b.end for b in selected]
        result["BarStart"] = [b.start for b in selected]
        result["AvailableDate"] = pd.to_datetime(frame.AvailableDate).dt.tz_localize(
            p.instrument.timezone).dt.tz_convert("UTC")
        result = result.sort_values("Date").reset_index(drop=True)
        validate_equity_frame(result, request, metadata)
        return result, metadata

    return {ProviderKey(product, MarketId.CN, source): ProviderBinding(source.provider, source.revision, fetch)
            for product in (EquityProduct.BARS, EquityProduct.SESSIONS)}
