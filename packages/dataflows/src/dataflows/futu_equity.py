"""Quote-only US equity adapter. The host owns the OpenQuoteContext lifecycle."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .contract import ProviderBinding
from .equity_contracts import (BarFrequency, EquityProduct, MarketId, PriceAdjustment,
                               ProviderKey, SourceRef, TimeInterval, TradingSession, UsEquityBarPolicy)
from .equity_data import equity_metadata
from .errors import DataContractError, IncompleteDataError, SourceRequestError


def futu_equity_bindings(*, source: SourceRef, quote_context, maximum_pages: int = 100,
                         research_policy: UsEquityBarPolicy | None = None):
    """Bind exact price bars and sessions without a broker connection."""
    if type(source) is not SourceRef or type(maximum_pages) is not int or maximum_pages < 1:
        raise TypeError("explicit source and positive maximum_pages required")
    if research_policy is not None and type(research_policy) is not UsEquityBarPolicy:
        raise TypeError("research_policy requires UsEquityBarPolicy")

    def fetch(request):
        p = request.parameters
        if p.instrument.market is not MarketId.US or p.source != source:
            raise DataContractError("MARKET_CONTRACT_MISMATCH")
        if p.query.product not in (EquityProduct.BARS, EquityProduct.SESSIONS):
            raise DataContractError("Futu quote adapter provides only bars and sessions")
        start, end = p.query.start.isoformat(), p.query.end.isoformat()
        ret, days = quote_context.request_trading_days(market="US", start=start, end=end)
        if ret != 0:
            raise SourceRequestError("Futu trading calendar failed", result=ret, detail=str(days))
        zone = ZoneInfo(p.instrument.timezone)
        sessions = []
        for item in days:
            day = date.fromisoformat(item["time"])
            kind = item["trade_date_type"]
            if kind not in {"WHOLE", "MORNING"}:
                raise DataContractError("unsupported US trading-day type", kind=kind)
            sessions.append(TradingSession(day, str(zone), (TimeInterval(
                datetime.combine(day, time(9, 30), zone),
                datetime.combine(day, time(16 if kind == "WHOLE" else 13), zone)),)))
        sessions = tuple(sessions)
        if not sessions:
            raise IncompleteDataError("requested US interval has no source trading sessions")
        metadata = equity_metadata(request, sessions, availability_basis="BAR_CLOSE_RESEARCH_ASSUMPTION")
        metadata["calendar_source"] = "futu.request_trading_days"
        metadata["publication_time_verified"] = False
        if research_policy is not None:
            metadata["research_bar_policy"] = {
                "kind": "OBSERVATION_GAPS_V2",
                "unavailable_intervals": [{"start": i.start.isoformat(), "end": i.end.isoformat()}
                                          for i in research_policy.unavailable_intervals],
            }
        if p.query.product is EquityProduct.SESSIONS:
            return pd.DataFrame({"Date": [s.segments[0].start for s in sessions],
                                 "AvailableDate": [s.segments[0].start for s in sessions],
                                 "SessionDate": [s.session_date.isoformat() for s in sessions]}), metadata
        code = "US." + p.instrument.symbol
        pages, key, keys, receipts = [], None, set(), []
        autype = {PriceAdjustment.NONE: "None", PriceAdjustment.FORWARD: "qfq", PriceAdjustment.BACKWARD: "hfq"}[p.query.adjustment]
        metadata["acquisition_method"] = ("PROVIDER_RAW" if p.query.adjustment is PriceAdjustment.NONE
                                           else "PROVIDER_ADJUSTED")
        metadata["price_source_api"] = "futu.request_history_kline"
        for index in range(maximum_pages):
            ret, frame, next_key = quote_context.request_history_kline(
                code, start=start, end=end, ktype="K_30M" if p.query.frequency is BarFrequency.M30 else "K_DAY",
                autype=autype, max_count=1000, page_req_key=key, session="RTH")
            if ret != 0:
                raise SourceRequestError("Futu history failed", result=ret, page=index)
            pages.append(frame)
            receipts.append({"page": index, "rows": len(frame), "result": ret, "more_pages": next_key is not None})
            if next_key is None:
                break
            token = repr(next_key)
            if token in keys:
                raise IncompleteDataError("Futu repeated a pagination key")
            keys.add(token)
            key = next_key
        else:
            raise IncompleteDataError("Futu pagination limit reached")
        frame = pd.concat(pages, ignore_index=True)
        if frame.empty:
            raise IncompleteDataError("Futu returned no history")
        if "code" not in frame or not frame.code.eq(code).all():
            raise DataContractError("Futu returned another instrument")
        times = pd.to_datetime(frame.time_key)
        if times.isna().any() or times.duplicated().any():
            raise DataContractError("Futu history has invalid or duplicate timestamps")
        bars = tuple(b for s in sessions for b in s.bars(p.query.frequency))
        try:
            if p.query.frequency is BarFrequency.DAILY:
                by_day = {s.session_date: s.bars(BarFrequency.DAILY)[0] for s in sessions}
                selected = [by_day[t.date()] for t in times]
            else:
                by_end = {pd.Timestamp(b.end): b for b in bars}
                selected = [by_end[t] for t in times.dt.tz_localize(zone, ambiguous="raise", nonexistent="raise").dt.tz_convert("UTC")]
        except KeyError as exc:
            raise DataContractError("Futu history timestamp outside independent session grid") from exc
        result = pd.DataFrame({"Date": [b.end for b in selected], "BarStart": [b.start for b in selected],
                               "AvailableDate": [b.end for b in selected]})
        for out, original in (("Open", "open"), ("High", "high"), ("Low", "low"),
                              ("Close", "close"), ("Volume", "volume"), ("Amount", "turnover")):
            result[out] = frame[original].to_numpy()
        if p.query.completed_through is not None:
            if research_policy is not None:
                raise DataContractError('partial-session quotes require the ordinary observation source')
            result = result.loc[result.Date <= p.query.completed_through]
        metadata["download_receipts"] = receipts
        metadata["daily_volume_scope"] = "VENDOR_DAILY" if p.query.frequency is BarFrequency.DAILY else "REGULAR_SESSION"
        if research_policy is not None:
            metadata["download_complete"] = True
            result["BarStatus"] = "OBSERVED"
            result.loc[result.Volume.eq(0), "BarStatus"] = "ZERO_VOLUME"
            result = result.set_index("Date").reindex(pd.DatetimeIndex([b.end for b in bars], name="Date"))
            result["BarStart"] = [b.start for b in bars]
            result["AvailableDate"] = [b.end for b in bars]
            result["BarStatus"] = result.BarStatus.fillna("MISSING")
            result["ExecutionBlocked"] = [any(b.start < i.end and i.start < b.end
                                              for i in research_policy.unavailable_intervals) for b in bars]
            result = result.reset_index()
        return result.sort_values("Date").reset_index(drop=True), metadata

    products = (EquityProduct.BARS, EquityProduct.SESSIONS)
    return {ProviderKey(product, MarketId.US, source): ProviderBinding(source.provider, source.revision, fetch)
            for product in products}
