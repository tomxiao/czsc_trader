"""Dynamic facts from an explicitly configured, independently verified feed."""

from dataclasses import asdict, replace
from datetime import date, timedelta
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

import pandas as pd

from .contract import EquityDataRequest, ProviderBinding
from .equity_contracts import EquityProduct, MarketId, ProviderKey, SourceRef
from .equity_data import equity_metadata, session_record, sessions_from_metadata, validate_equity_frame
from .errors import DataContractError, IncompleteDataError, SourceRequestError


def validate_facts_endpoint(endpoint: str) -> None:
    if type(endpoint) is not str:
        raise TypeError("dynamic equity endpoint must be a URL")
    url = urlsplit(endpoint)
    if (not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment
            or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"}))):
        raise ValueError("dynamic equity facts require an HTTPS endpoint or loopback HTTP")


def _read_json(url):
    try:
        with urlopen(url, timeout=10) as response:
            return json.load(response)
    except (OSError, ValueError) as exc:
        raise SourceRequestError("dynamic equity facts request failed") from exc


def _aware(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise DataContractError("dynamic equity facts require explicit timestamp offsets")
    return stamp.tz_convert("UTC")


def dynamic_equity_bindings(*, source: SourceRef, market: MarketId, endpoint: str,
                            calendar_source: SourceRef, calendar_binding: ProviderBinding,
                            read_json=_read_json):
    """Expose dynamic facts only. A successful empty response is not proof of completeness."""
    validate_facts_endpoint(endpoint)
    if (type(source) is not SourceRef or type(market) is not MarketId
            or type(calendar_source) is not SourceRef or type(calendar_binding) is not ProviderBinding):
        raise TypeError("dynamic equity facts require typed source and independent calendar")

    def fetch(request):
        p = request.parameters
        query = p.query
        if p.source != source or p.instrument.market is not market:
            raise DataContractError("dynamic equity facts source differs from request")
        selection = dict(market=market.value, symbol=p.instrument.symbol,
                         asset_class=p.instrument.asset_class.value, product=query.product.value,
                         start=query.start.isoformat(), end=query.end.isoformat(),
                         frequency=query.frequency.value, session=query.session.value)
        raw = read_json(endpoint + "?" + urlencode(selection))
        if (type(raw) is not dict or set(raw) != {"source", "selection", "coverage", "rows"}
                or raw["source"] != asdict(source) or raw["selection"] != selection):
            raise DataContractError("dynamic equity facts identity differs from request")
        coverage, rows = raw["coverage"], raw["rows"]
        if (type(coverage) is not dict or set(coverage) != {"start", "end", "complete", "receipt"}
                or type(rows) is not list or any(type(row) is not dict for row in rows)):
            raise DataContractError("invalid dynamic equity facts response")
        try:
            coverage_start = date.fromisoformat(coverage["start"])
            coverage_end = date.fromisoformat(coverage["end"])
        except (TypeError, ValueError) as exc:
            raise DataContractError("invalid dynamic equity facts coverage dates") from exc
        if (coverage["complete"] is not True or type(coverage["receipt"]) is not str or not coverage["receipt"].strip()
                or coverage_start > query.start or coverage_end < query.end):
            raise IncompleteDataError("dynamic equity facts lack verified coverage")
        cal_end = query.end + timedelta(days=14) if query.product is EquityProduct.TRADING_FACTS else query.end
        cal_request = EquityDataRequest(p.instrument, calendar_source,
            replace(query, product=EquityProduct.SESSIONS, end=cal_end))
        cal_frame, cal_meta = calendar_binding.fetch(cal_request)
        validate_equity_frame(cal_frame, cal_request, cal_meta)
        calendar = sessions_from_metadata(cal_meta)
        sessions = tuple(s for s in calendar if s.session_date <= query.end)
        if not sessions:
            raise IncompleteDataError("dynamic equity facts have no trading sessions")
        meta = equity_metadata(request, sessions, availability_basis="EXPLICIT_SOURCE_TIMESTAMPS")
        meta["coverage_receipt"] = coverage["receipt"]
        if query.product is EquityProduct.TRADING_FACTS:
            following = next((s for s in calendar if s.session_date > query.end), None)
            if following is not None:
                meta["following_session"] = session_record(following)
        else:
            meta["action_history_complete"] = True
            if not rows:
                stamp = sessions[0].segments[0].start.isoformat()
                rows = [{"Date": stamp, "AvailableDate": stamp, "EventId": "verified-no-actions",
                         "Kind": "NONE", "Ratio": 1., "CashPerShare": 0., "PayAt": None}]
                meta["no_actions_verified"] = True
            elif any(set(row) != {"Date", "AvailableDate", "EventId", "Kind", "Ratio", "CashPerShare", "PayAt"}
                    or row["Kind"] != "SPLIT" or type(row["EventId"]) is not str or not row["EventId"].strip()
                    or type(row["Ratio"]) not in (int, float) or type(row["CashPerShare"]) not in (int, float)
                    or row["CashPerShare"] != 0 or row["PayAt"] is not None for row in rows):
                raise DataContractError("dynamic action feed requires exact mechanical share adjustments")
        frame = pd.DataFrame(rows)
        for name in ("Date", "AvailableDate"):
            if name not in frame:
                raise IncompleteDataError("dynamic equity facts contain no dated rows")
            frame[name] = pd.to_datetime([_aware(value) for value in frame[name]], utc=True)
        frame = frame.sort_values(["Date", "EventId"] if query.product is EquityProduct.ACTIONS else ["Date"]).reset_index(drop=True)
        if not frame.Date.dt.tz_convert(p.instrument.timezone).dt.date.between(query.start, query.end).all():
            raise DataContractError("dynamic equity facts contain rows outside the request")
        if (frame.AvailableDate > frame.Date).any():
            raise DataContractError("dynamic equity facts unavailable at their effective time")
        validate_equity_frame(frame, request, meta)
        return frame, meta

    return {ProviderKey(product, market, source): ProviderBinding(source.provider, source.revision, fetch)
            for product in (EquityProduct.ACTIONS, EquityProduct.TRADING_FACTS)}
