"""Quote-only US equity adapter. The host owns the OpenQuoteContext lifecycle."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .contract import ProviderBinding
from .equity_contracts import (BarFrequency, EquityProduct, MarketId, PriceAdjustment,
                               ProviderKey, SourceRef, TimeInterval, TradingSession)
from .equity_data import equity_metadata
from .errors import DataContractError, IncompleteDataError, SourceRequestError


def futu_equity_bindings(*, source: SourceRef, quote_context, maximum_pages: int = 100):
    """Bind exact quote products without creating a broker/trade connection.

    Cash dividends require an independently enriched action product containing
    payment dates; get_rehab alone must never invent that information.
    """
    if type(source) is not SourceRef or type(maximum_pages) is not int or maximum_pages < 1:
        raise TypeError("explicit source and positive maximum_pages required")

    def fetch(request):
        p = request.parameters
        if p.instrument.market is not MarketId.US or p.source != source:
            raise DataContractError("MARKET_CONTRACT_MISMATCH")
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
        if p.query.product is EquityProduct.SESSIONS:
            return pd.DataFrame({"Date": [s.segments[0].start for s in sessions],
                                 "AvailableDate": [s.segments[0].start for s in sessions],
                                 "SessionDate": [s.session_date.isoformat() for s in sessions]}), metadata
        code = "US." + p.instrument.symbol
        if p.query.product is EquityProduct.ACTIONS:
            ret, actions = quote_context.get_rehab(code)
            if ret != 0:
                raise SourceRequestError("Futu corporate actions failed", result=ret)
            rows = []
            for action in actions.to_dict("records"):
                day = date.fromisoformat(str(action["ex_div_date"])[:10])
                if not p.query.start <= day <= p.query.end:
                    continue
                unsupported = ("per_cash_div", "special_dividend", "per_share_div_ratio",
                               "per_share_trans_ratio", "allotment_ratio", "stk_spo_ratio", "spin_off_ratio")
                if any(pd.notna(action.get(k)) and action.get(k, 0) != 0 for k in unsupported):
                    raise DataContractError("CORPORATE_ACTION_UNSUPPORTED: enriched event/payment evidence required")
                ratio = float(action["split_ratio"])
                if ratio <= 0:
                    raise DataContractError("invalid source split ratio")
                stamp = pd.Timestamp(datetime.combine(day, time(9, 30), zone)).tz_convert("UTC")
                rows.append({"Date": stamp, "AvailableDate": stamp,
                             "EventId": f"{code}:{day}:split", "Kind": "SPLIT",
                             "Ratio": ratio, "CashPerShare": 0., "PayAt": None})
            if not rows:
                stamp = sessions[0].segments[0].start
                rows = [{"Date": stamp, "AvailableDate": stamp, "EventId": "no-actions",
                         "Kind": "NONE", "Ratio": 1., "CashPerShare": 0., "PayAt": None}]
                metadata["no_actions_verified"] = True
            return pd.DataFrame(rows).sort_values(["Date", "EventId"]).reset_index(drop=True), metadata
        if p.query.product is not EquityProduct.BARS:
            raise DataContractError("unsupported Futu equity product")
        pages, key, keys, receipts = [], None, set(), []
        autype = {PriceAdjustment.NONE: "None", PriceAdjustment.FORWARD: "QFQ", PriceAdjustment.BACKWARD: "HFQ"}[p.query.adjustment]
        for index in range(maximum_pages):
            ret, frame, next_key = quote_context.request_history_kline(
                code, start=start, end=end, ktype="K_30M" if p.query.frequency is BarFrequency.M30 else "K_DAY",
                autype=autype, max_count=1000, page_req_key=key, session="RTH")
            if ret != 0:
                raise SourceRequestError("Futu history failed", result=ret, page=index)
            pages.append(frame)
            receipts.append({"page": index, "rows": len(frame), "result": ret})
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
        bars = tuple(b for s in sessions for b in s.bars(p.query.frequency))
        if p.query.frequency is BarFrequency.DAILY:
            by_day = {s.session_date: s.bars(BarFrequency.DAILY)[0] for s in sessions}
            selected = [by_day[t.date()] for t in times]
        else:
            by_end = {pd.Timestamp(b.end): b for b in bars}
            selected = [by_end[t] for t in times.dt.tz_localize(zone, ambiguous="raise", nonexistent="raise").dt.tz_convert("UTC")]
        result = pd.DataFrame({"Date": [b.end for b in selected], "BarStart": [b.start for b in selected],
                               "AvailableDate": [b.end for b in selected]})
        for out, original in (("Open", "open"), ("High", "high"), ("Low", "low"),
                              ("Close", "close"), ("Volume", "volume"), ("Amount", "turnover")):
            result[out] = frame[original].to_numpy()
        metadata["download_receipts"] = receipts
        metadata["daily_volume_scope"] = "VENDOR_DAILY" if p.query.frequency is BarFrequency.DAILY else "REGULAR_SESSION"
        return result.sort_values("Date").reset_index(drop=True), metadata

    return {ProviderKey(product, MarketId.US, source): ProviderBinding(source.provider, source.revision, fetch)
            for product in (EquityProduct.BARS, EquityProduct.SESSIONS, EquityProduct.ACTIONS)}
