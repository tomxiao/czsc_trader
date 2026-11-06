"""CN RAW/HFQ prices and independent sessions for the equity contract."""
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
from .tushare_etf import (fetch_etf_ohlcv, fetch_etf_unadjusted_daily,
                          fetch_etf_unadjusted_intraday)
from .tushare_stock import (fetch_stock_ohlcv, fetch_stock_unadjusted_daily,
                            fetch_stock_unadjusted_intraday)


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
    return _bindings(source=source, env_file=env_file, raw=False)


def tushare_equity_bindings(*, source: SourceRef,
                            env_file: str | Path | None = None) -> dict[ProviderKey, ProviderBinding]:
    """CN RAW/HFQ D1/M30 and calendar products; no inferred events or rules.

    Publication-time limitations of the upstream adapters remain explicit. The
    host must separately bind dated constraints and complete economic events.
    """
    return _bindings(source=source, env_file=env_file, raw=True)


def _bindings(*, source, env_file, raw):
    if type(source) is not SourceRef:
        raise TypeError("source requires SourceRef")

    def fetch(request: EquityDataRequest):
        p = request.parameters
        if p.instrument.market is not MarketId.CN or p.source != source:
            raise DataContractError("MARKET_CONTRACT_MISMATCH")
        if p.query.product not in (EquityProduct.BARS, EquityProduct.SESSIONS):
            raise DataContractError("Tushare observations provide only bars and sessions")
        if p.query.product is EquityProduct.BARS:
            allowed = (PriceAdjustment.NONE, PriceAdjustment.BACKWARD) if raw else (PriceAdjustment.BACKWARD,)
            if p.query.adjustment not in allowed:
                raise DataContractError("Tushare equity observations require backward-adjusted prices or explicitly enabled RAW")
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

        stock = p.instrument.asset_class is AssetClass.STOCK
        if p.query.adjustment is PriceAdjustment.NONE:
            if p.query.frequency is BarFrequency.DAILY:
                fetch_bars = fetch_stock_unadjusted_daily if stock else fetch_etf_unadjusted_daily
                frame, source_metadata = fetch_bars(p.instrument.symbol, start, end, env_file=env_file)
            else:
                fetch_bars = fetch_stock_unadjusted_intraday if stock else fetch_etf_unadjusted_intraday
                frame, source_metadata = fetch_bars(p.instrument.symbol, start, end,
                    period=p.query.frequency.value, env_file=env_file)
        else:
            fetch_bars = fetch_stock_ohlcv if stock else fetch_etf_ohlcv
            frame, source_metadata = fetch_bars(p.instrument.symbol, start, end,
                period=p.query.frequency.value, env_file=env_file)
        if source_metadata.get("adjustment") != p.query.adjustment.value:
            raise DataContractError("Tushare observation source returned a different adjustment")
        sessions = _sessions(source_metadata["daily_session_coverage"])
        raw_daily = p.query.adjustment is PriceAdjustment.NONE and p.query.frequency is BarFrequency.DAILY
        availability = ("BAR_CLOSE_SOURCE_TIME; historical vendor publication time unverified"
                        if raw_daily else source_metadata["available_at"])
        metadata = {**source_metadata, **equity_metadata(
            request, sessions, availability_basis=availability)}
        metadata["calendar_source"] = "tushare.trade_cal"
        metadata.setdefault("publication_time_verified", False)
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
        result["AvailableDate"] = ([b.end for b in selected] if raw_daily else
            pd.to_datetime(frame.AvailableDate).dt.tz_localize(p.instrument.timezone).dt.tz_convert("UTC"))
        result = result.sort_values("Date").reset_index(drop=True)
        validate_equity_frame(result, request, metadata)
        return result, metadata

    return {ProviderKey(product, MarketId.CN, source): ProviderBinding(source.provider, source.revision, fetch)
            for product in (EquityProduct.BARS, EquityProduct.SESSIONS)}
