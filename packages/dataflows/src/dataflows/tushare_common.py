"""Shared Tushare client construction."""

from __future__ import annotations

from pathlib import Path
from datetime import date, timedelta

import tushare as ts
import pandas as pd
import requests
from tushare.pro.client import DataApi

from .config import get_tushare_token
from .errors import DataContractError, SourceNotReadyError, SourceRequestError


class _TusharePro(DataApi):
    """Keep SDK method dispatch while checking transport before decoding rows."""

    def __init__(self, token: str, timeout: int = 30):
        super().__init__(token, timeout=timeout)
        self._source_token = token
        self._source_timeout = timeout

    def query(self, api_name, fields="", **kwargs):
        endpoint = self._DataApi__http_url
        kwargs.setdefault("ts_type_name", endpoint)
        context = {"vendor": "tushare", "api": api_name}
        try:
            response = requests.post(
                f"{endpoint}/{api_name}",
                json={"api_name": api_name, "token": self._source_token,
                      "params": kwargs, "fields": fields},
                timeout=self._source_timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise SourceNotReadyError("Tushare transport is unavailable", **context,
                                      exception_type=type(exc).__name__) from None
        except requests.RequestException as exc:
            raise SourceRequestError("Tushare request could not be sent", **context,
                                     exception_type=type(exc).__name__) from None
        status = response.status_code
        if not 200 <= status < 300:
            error = SourceNotReadyError if status == 429 or 500 <= status < 600 else SourceRequestError
            raise error(f"Tushare HTTP request failed: {status}", **context, http_status=status)
        try:
            payload = response.json()
        except ValueError:
            raise DataContractError("Tushare response is not JSON", **context, http_status=status) from None
        if not isinstance(payload, dict) or type(payload.get("code")) is not int:
            raise DataContractError("Tushare response has no valid business code", **context, http_status=status)
        if payload["code"] != 0:
            # Vendor messages and exception strings may echo request credentials.
            raise SourceRequestError("Tushare API rejected the request", **context,
                                     http_status=status, vendor_code=payload["code"])
        data = payload.get("data")
        if (not isinstance(data, dict) or not isinstance(data.get("fields"), list)
                or any(not isinstance(name, str) for name in data["fields"])
                or len(set(data["fields"])) != len(data["fields"])
                or not isinstance(data.get("items"), list)
                or any(not isinstance(row, list) or len(row) != len(data["fields"]) for row in data["items"])):
            raise DataContractError("Tushare response fields or rows are invalid", **context, http_status=status)
        return pd.DataFrame(data["items"], columns=data["fields"])


def get_tushare_module(env_file: str | Path | None = None):
    token = get_tushare_token(env_file)
    ts.set_token(token)
    return ts


def get_tushare_pro(env_file: str | Path | None = None):
    # ``ts.set_token`` persists ``tk.csv`` in the user profile. Pro clients
    # already accept the token explicitly, so avoid that unrelated filesystem
    # side effect and keep DFLS execution inside the repository boundary.
    return _TusharePro(get_tushare_token(env_file))


def fetch_instrument_name(
    symbol: str,
    asset_type: str,
    *,
    env_file: str | Path | None = None,
) -> str:
    """Return the unique Tushare Chinese short name for an A-share instrument."""
    pro = get_tushare_pro(env_file)
    if asset_type == "etf":
        frame = pro.fund_basic(
            market="E",
            ts_code=symbol,
            fields="ts_code,name",
        )
    elif asset_type == "stock":
        frame = pro.stock_basic(ts_code=symbol, fields="ts_code,name")
    else:
        raise ValueError("asset_type must be stock or etf")
    if frame is None or len(frame) != 1:
        count = 0 if frame is None else len(frame)
        raise ValueError(f"Tushare returned {count} instrument names for {symbol}")
    name = str(frame.iloc[0].get("name", "")).strip()
    if not name:
        raise ValueError(f"Tushare returned an empty instrument name for {symbol}")
    return name


def fetch_next_trading_session(
    after: date,
    *,
    env_file: str | Path | None = None,
    pro=None,
) -> tuple[date, dict[str, str]]:
    """Return the first open SSE session after a completed trading date."""
    client = pro or get_tushare_pro(env_file)
    start = after + timedelta(days=1)
    end = after + timedelta(days=40)
    frame = client.trade_cal(
        exchange="SSE",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        is_open="1",
        fields="exchange,cal_date,is_open",
    )
    if frame is None or frame.empty:
        raise ValueError(f"Tushare returned no open SSE session after {after}")
    sessions = sorted(date.fromisoformat(str(value)) for value in frame["cal_date"])
    return sessions[0], {"vendor": "tushare", "exchange": "SSE"}
