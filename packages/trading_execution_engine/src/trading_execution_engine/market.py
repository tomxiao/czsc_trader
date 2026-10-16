"""Dated exchange price boundaries for deterministic market execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from math import isfinite
import re
from types import MappingProxyType
from typing import ClassVar, Mapping


@dataclass(frozen=True)
class SessionPriceLimits:
    session: date
    down_limit: float
    up_limit: float

    def __post_init__(self) -> None:
        if type(self.session) is not date:
            raise TypeError("price-limit session must be a date")
        for name in ("down_limit", "up_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("price limits must be real numbers")
            if not isfinite(value) or value <= 0:
                raise ValueError("price limits must be positive and finite")
            object.__setattr__(self, name, float(value))
        if self.down_limit >= self.up_limit:
            raise ValueError("down_limit must be below up_limit")

    def contains(self, price: float) -> bool:
        # HFQ multiplication can add binary floating point noise. This tolerance
        # only absorbs rounding error; it does not widen a market price tick.
        tolerance = max(abs(self.down_limit), abs(self.up_limit)) * 1e-10
        return self.down_limit - tolerance <= price <= self.up_limit + tolerance

    def at_upper(self, price: float) -> bool:
        return abs(price - self.up_limit) <= abs(self.up_limit) * 1e-10

    def at_lower(self, price: float) -> bool:
        return abs(price - self.down_limit) <= abs(self.down_limit) * 1e-10

    def to_dict(self) -> dict[str, object]:
        return {"session": self.session.isoformat(), "down_limit": self.down_limit,
                "up_limit": self.up_limit}


@dataclass(frozen=True)
class MarketExecutionRules:
    symbol: str
    sessions: tuple[SessionPriceLimits, ...]
    contract_version: ClassVar[str] = "OPEN_LIMIT_BLOCK_V1"
    _by_session: Mapping[date, SessionPriceLimits] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", self.symbol) is None:
            raise ValueError("market rules require an exchange-qualified A-share or ETF symbol")
        if type(self.sessions) is not tuple or not self.sessions:
            raise ValueError("market rules require a non-empty tuple of sessions")
        if any(not isinstance(item, SessionPriceLimits) for item in self.sessions):
            raise TypeError("market rules sessions require SessionPriceLimits")
        dates = tuple(item.session for item in self.sessions)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("market rule sessions must be unique and increasing")
        object.__setattr__(self, "_by_session", MappingProxyType({item.session: item for item in self.sessions}))

    def for_session(self, session: date) -> SessionPriceLimits:
        if type(session) is not date:
            raise TypeError("market-rule lookup requires a date")
        try:
            return self._by_session[session]
        except KeyError as exc:
            raise ValueError(f"market rules do not cover session {session.isoformat()}") from exc

    def __reduce__(self) -> tuple[object, tuple[str, tuple[SessionPriceLimits, ...]]]:
        # Keep the private immutable index out of process transport. Rebuilding
        # through the public constructor revalidates the transported contract.
        return type(self), (self.symbol, self.sessions)

    def to_dict(self) -> dict[str, object]:
        return {"contract_version": self.contract_version, "symbol": self.symbol,
                "sessions": [item.to_dict() for item in self.sessions]}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MarketExecutionRules:
        if not isinstance(value, Mapping) or set(value) != {"contract_version", "symbol", "sessions"}:
            raise ValueError("invalid market execution contract fields")
        if type(value["contract_version"]) is not str or value["contract_version"] != cls.contract_version:
            raise ValueError("unsupported market execution contract version")
        raw_sessions = value["sessions"]
        if type(raw_sessions) is not list or not raw_sessions:
            raise ValueError("market execution contract sessions must be a non-empty list")
        sessions = []
        for item in raw_sessions:
            if not isinstance(item, Mapping) or set(item) != {"session", "down_limit", "up_limit"}:
                raise ValueError("invalid session price-limit fields")
            if type(item["session"]) is not str:
                raise TypeError("session price-limit date must be an ISO date string")
            day = date.fromisoformat(item["session"])
            if day.isoformat() != item["session"]:
                raise ValueError("session price-limit date must use YYYY-MM-DD")
            sessions.append(SessionPriceLimits(day, item["down_limit"], item["up_limit"]))
        result = cls(value["symbol"], tuple(sessions))
        if result.to_dict() != value:
            raise ValueError("market execution contract is not canonical")
        return result

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return sha256(payload.encode("utf-8")).hexdigest()
