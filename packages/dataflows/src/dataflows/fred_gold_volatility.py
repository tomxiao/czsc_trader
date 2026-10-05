"""CBOE gold ETF implied-volatility closes distributed by FRED, first releases only."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from .config import get_fred_key
from .contract import FRED_GVZ_AVAILABILITY_RULE
from .errors import DataContractError, EmptyDataError, IncompleteDataError, SourceNotReadyError


def fetch_gold_volatility_daily(
    start: str,
    end: str,
    *,
    env_file: str | Path | None = None,
    http_get: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch fixed GVZCLS first releases; retain release dates and a safe day boundary."""
    try:
        api_key = get_fred_key(env_file)
    except ValueError:
        raise DataContractError("FRED_KEY is not configured") from None
    getter = requests.get if http_get is None else http_get
    cursor = pd.Timestamp(start).normalize()
    final = pd.Timestamp(end).normalize()
    observations: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    while cursor <= final:
        stop = min(pd.Timestamp(year=cursor.year + 5, month=12, day=31), final)
        realtime_start, realtime_end = cursor.date().isoformat(), stop.date().isoformat()
        try:
            response = getter(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "api_key": api_key,
                    "file_type": "json",
                    "series_id": "GVZCLS",
                    "observation_start": start,
                    "observation_end": end,
                    "realtime_start": realtime_start,
                    "realtime_end": realtime_end,
                    "output_type": 4,
                    "limit": 100_000,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            # Requests exception URLs may contain API credentials. Retain type only.
            raise SourceNotReadyError(
                "FRED gold-volatility source is unavailable", exception_type=type(exc).__name__
            ) from None
        code = int(getattr(response, "status_code", 0))
        if code == 429 or code >= 500:
            raise SourceNotReadyError(
                "FRED gold-volatility source is temporarily unavailable", status_code=code
            )
        if code != 200:
            raise DataContractError("FRED rejected the GVZCLS request", status_code=code)
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise DataContractError("FRED returned invalid JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
            raise DataContractError("FRED response is missing observations")
        chunk = payload["observations"]
        try:
            count = int(payload.get("count", len(chunk)))
        except (TypeError, ValueError):
            raise DataContractError("FRED response count is invalid") from None
        if count < 0 or count < len(chunk):
            raise DataContractError("FRED response count disagrees with observations")
        if count > len(chunk):
            raise IncompleteDataError(
                "FRED GVZCLS response was truncated", expected_rows=count, returned_rows=len(chunk)
            )
        if not all(isinstance(item, dict) for item in chunk):
            raise DataContractError("FRED observations must be records")
        responses.append(
            {
                "realtime_start": realtime_start,
                "realtime_end": realtime_end,
                "count": count,
                "payload_sha256": sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        )
        observations.extend(chunk)
        cursor = stop + pd.Timedelta(days=1)
    usable = [item for item in observations if item.get("value") not in (None, ".")]
    if not usable:
        raise EmptyDataError("FRED returned no usable GVZCLS observations")
    frame = pd.DataFrame(usable)
    missing = sorted({"date", "realtime_start", "value"}.difference(frame.columns))
    if missing:
        raise DataContractError("FRED GVZCLS fields are incomplete", missing_fields=missing)
    dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce").dt.normalize()
    released = pd.to_datetime(
        frame["realtime_start"], format="%Y-%m-%d", errors="coerce"
    ).dt.normalize()
    close = pd.to_numeric(frame["value"], errors="coerce")
    invalid = dates.isna() | released.isna() | ~np.isfinite(close) | close.le(0)
    if invalid.any():
        raise DataContractError(
            "FRED GVZCLS observations are invalid", invalid_rows=int(invalid.sum())
        )
    # ALFRED occasionally dates a vintage before its observation (2021-12-24).
    # Retain that source fact, but never make the observation available early.
    available = pd.concat([dates, released], axis=1).max(axis=1) + pd.Timedelta(days=1, hours=16)
    result = pd.DataFrame(
        {
            "Date": dates,
            "InitialReleaseDate": released,
            "AvailableDate": available,
            "Close": close.astype(float),
        }
    )
    result = (
        result.loc[result.Date.between(pd.Timestamp(start).normalize(), final)]
        .sort_values("Date", kind="stable")
        .reset_index(drop=True)
    )
    if result.empty:
        raise EmptyDataError("FRED returned no GVZCLS observations in range")
    if result.Date.duplicated().any():
        raise DataContractError("FRED GVZCLS first-release history contains duplicate dates")
    return result, {
        "vendor": "FRED",
        "original_source": "CBOE",
        "vendor_interface": "fred/series/observations",
        "series_id": "GVZCLS",
        "vintage_mode": "INITIAL_RELEASE_ONLY",
        "fred_output_type": 4,
        "primary_key": ["Date"],
        "frequency": "daily",
        "unit": "implied_volatility_index_percent",
        "source_time_field": "Date",
        "availability_time_field": "AvailableDate",
        "availability_timezone": "Asia/Shanghai",
        "source_calendar": "US_MARKET",
        "available_at": FRED_GVZ_AVAILABILITY_RULE,
        "request_range_policy": "EXACT",
        "historical_intraday_publication_verified": False,
        "release_before_observation_dates": sorted(
            dates.loc[released.lt(dates)].dt.strftime("%Y-%m-%d").tolist()
        ),
        "maximum_start_lag_days": 7,
        "source_responses": responses,
        "missing_value_dates": sorted(
            {x.get("date") for x in observations if x.get("value") in (None, ".") and x.get("date")}
        ),
    }
