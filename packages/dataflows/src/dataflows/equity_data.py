"""Validation of explicit equity products before managed publication."""
from dataclasses import asdict
from datetime import date, datetime
import math

import pandas as pd

from .equity_contracts import EquityProduct, TradingSession, TimeInterval
from .errors import DataContractError, IncompleteDataError


def sessions_from_metadata(metadata):
    try:
        sessions = tuple(TradingSession(
            date.fromisoformat(row["session_date"]), row["timezone"],
            tuple(TimeInterval(datetime.fromisoformat(seg["start"]),
                               datetime.fromisoformat(seg["end"])) for seg in row["segments"]),
        ) for row in metadata["sessions"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DataContractError("invalid independent equity session evidence") from exc
    days = tuple(item.session_date for item in sessions)
    if not sessions or days != tuple(sorted(set(days))):
        raise DataContractError("equity sessions must be unique and ordered")
    return sessions


def session_record(session: TradingSession):
    return {"session_date": session.session_date.isoformat(), "timezone": session.timezone,
            "segments": [{"start": seg.start.isoformat(), "end": seg.end.isoformat()}
                         for seg in session.segments]}


def equity_metadata(request, sessions, *, availability_basis: str):
    """Build explicit source declarations; validation still checks their contents."""
    p = request.parameters
    return {
        "vendor": p.source.provider, "source_revision": p.source.revision,
        "instrument": asdict(p.instrument), "adjustment": p.query.adjustment.value,
        "source_time_field": "Date", "availability_time_field": "AvailableDate",
        "source_calendar": p.instrument.market.value,
        "available_at": availability_basis, "request_range_policy": "EXACT",
        "coverage_start": p.query.start.isoformat(), "coverage_end": p.query.end.isoformat(),
        "sessions": [session_record(s) for s in sessions],
        "primary_key": ["Date", "EventId"] if p.query.product is EquityProduct.ACTIONS else ["Date"],
    }


def _timestamps(frame, column):
    if column not in frame:
        raise DataContractError(f"equity product requires {column}")
    values = pd.to_datetime(frame[column], errors="raise")
    if values.isna().any() or values.dt.tz is None:
        raise DataContractError(f"{column} requires aware, finite timestamps")
    return values.dt.tz_convert("UTC")


def validate_equity_frame(frame, request, metadata):
    p = request.parameters
    if metadata.get("instrument") != asdict(p.instrument):
        raise DataContractError("MARKET_CONTRACT_MISMATCH: source instrument differs")
    if (metadata.get("vendor"), metadata.get("source_revision")) != (p.source.provider, p.source.revision):
        raise DataContractError("source identity differs from explicit binding")
    if (metadata.get("coverage_start"), metadata.get("coverage_end")) != (
            p.query.start.isoformat(), p.query.end.isoformat()):
        raise IncompleteDataError("independent calendar does not cover the request")
    sessions = sessions_from_metadata(metadata)
    if any(s.timezone != p.instrument.timezone or not p.query.start <= s.session_date <= p.query.end for s in sessions):
        raise DataContractError("session market or bounds differ from request")
    dates = _timestamps(frame, "Date")
    available = _timestamps(frame, "AvailableDate")
    if not dates.is_monotonic_increasing:
        raise DataContractError("equity rows must be ordered")
    if p.query.product is EquityProduct.BARS:
        starts = _timestamps(frame, "BarStart")
        expected = tuple(bar for s in sessions for bar in s.bars(p.query.frequency))
        if tuple(dates) != tuple(pd.Timestamp(b.end) for b in expected) or tuple(starts) != tuple(pd.Timestamp(b.start) for b in expected):
            raise IncompleteDataError("equity bars differ from the independent session grid")
        if (available < dates).any():
            raise DataContractError("bar availability precedes bar completion")
        if metadata.get("adjustment") != p.query.adjustment.value:
            raise DataContractError("bar adjustment differs from request")
        columns = ("Open", "High", "Low", "Close", "Volume", "Amount")
        if not set(columns).issubset(frame):
            raise DataContractError("equity OHLCV fields are incomplete")
        values = frame.loc[:, list(columns)].astype(float)
        if not values.map(math.isfinite).all().all() or (values.iloc[:, :4] <= 0).any().any() or (values.iloc[:, 4:] < 0).any().any():
            raise DataContractError("invalid equity OHLCV values")
        if ((values.High < values[["Open", "Close", "Low"]].max(axis=1))
                | (values.Low > values[["Open", "Close", "High"]].min(axis=1))).any():
            raise DataContractError("invalid equity OHLC bounds")
    elif p.query.product is EquityProduct.SESSIONS:
        if "SessionDate" not in frame or tuple(frame.SessionDate) != tuple(s.session_date.isoformat() for s in sessions):
            raise DataContractError("session product differs from its declared calendar")
    elif p.query.product is EquityProduct.ACTIONS:
        required = {"EventId", "Kind", "Ratio", "CashPerShare", "PayAt"}
        if not required.issubset(frame) or frame.EventId.duplicated().any():
            raise DataContractError("corporate actions need unique identities and complete fields")
        for row in frame.itertuples():
            if row.Kind not in {"NONE", "SPLIT", "CASH_DIVIDEND"}:
                raise DataContractError("CORPORATE_ACTION_UNSUPPORTED")
            if row.Kind == "SPLIT" and (not math.isfinite(float(row.Ratio)) or row.Ratio <= 0):
                raise DataContractError("split ratio must be positive and finite")
            if row.Kind == "CASH_DIVIDEND":
                pay = pd.Timestamp(row.PayAt)
                if (not math.isfinite(float(row.CashPerShare)) or row.CashPerShare < 0
                        or pd.isna(pay) or pay.tzinfo is None or pay < row.Date):
                    raise DataContractError("cash dividend requires a valid payment time and amount")
        if "NONE" in set(frame.Kind) and (len(frame) != 1 or not metadata.get("no_actions_verified")):
            raise DataContractError("empty action history requires explicit source verification")
    elif p.query.product is EquityProduct.CONSTRAINTS:
        if not {"QuantityStep", "PriceTick", "Tradable"}.issubset(frame):
            raise DataContractError("trading constraint fields missing")
        for row in frame.itertuples():
            if type(row.QuantityStep) is not int or row.QuantityStep <= 0 or not math.isfinite(float(row.PriceTick)) or row.PriceTick <= 0 or type(row.Tradable) is not bool:
                raise DataContractError("invalid dated trading constraints")
        expected = tuple(bar.start for session in sessions for bar in session.bars(p.query.frequency))
        if tuple(dates) != tuple(pd.Timestamp(stamp) for stamp in expected):
            raise IncompleteDataError("trading constraints must cover every execution interval")
        if (available > dates).any():
            raise DataContractError("trading constraints unavailable at their effective interval")
