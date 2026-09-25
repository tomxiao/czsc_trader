"""Fixed FRED publication for the U.S. daily policy-uncertainty index."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .config import get_fred_key
from .errors import (
    DataContractError,
    EmptyDataError,
    IncompleteDataError,
    SourceNotReadyError,
)


_FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_SERIES_ID = "USEPUINDXD"
_INITIAL_RELEASE_OUTPUT_TYPE = 4


def _realtime_windows(start: str, end: str) -> tuple[tuple[str, str], ...]:
    """Bound ALFRED vintage ranges so a request never exceeds its history limit."""

    cursor = pd.Timestamp(start).normalize()
    final = pd.Timestamp(end).normalize()
    windows: list[tuple[str, str]] = []
    while cursor <= final:
        boundary = pd.Timestamp(year=cursor.year + 5, month=12, day=31)
        stop = min(boundary, final)
        windows.append((cursor.date().isoformat(), stop.date().isoformat()))
        cursor = stop + pd.Timedelta(days=1)
    return tuple(windows)


def fetch_us_policy_uncertainty_daily(
    start: str,
    end: str,
    *,
    env_file: str | Path | None = None,
    http_get: Callable[..., Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch only ALFRED initial releases for the fixed USEPUINDXD series."""

    try:
        api_key = get_fred_key(env_file)
    except ValueError as exc:
        raise DataContractError("FRED_KEY is not configured") from exc
    getter = requests.get if http_get is None else http_get
    observations: list[dict[str, Any]] = []
    for realtime_start, realtime_end in _realtime_windows(start, end):
        try:
            response = getter(
                _FRED_OBSERVATIONS_URL,
                params={
                    "api_key": api_key,
                    "file_type": "json",
                    "series_id": _SERIES_ID,
                    "observation_start": start,
                    "observation_end": end,
                    "realtime_start": realtime_start,
                    "realtime_end": realtime_end,
                    "output_type": _INITIAL_RELEASE_OUTPUT_TYPE,
                    "limit": 100_000,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise SourceNotReadyError(
                "FRED policy-uncertainty source is unavailable",
                exception_type=type(exc).__name__,
            ) from exc

        status_code = int(getattr(response, "status_code", 0))
        if status_code == 429 or status_code >= 500:
            raise SourceNotReadyError(
                "FRED policy-uncertainty source is temporarily unavailable",
                status_code=status_code,
            )
        if status_code != 200:
            raise DataContractError(
                "FRED rejected the fixed policy-uncertainty request",
                status_code=status_code,
                realtime_start=realtime_start,
                realtime_end=realtime_end,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise DataContractError("FRED returned an invalid JSON response") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
            raise DataContractError("FRED response is missing observations")
        chunk = payload["observations"]
        try:
            count = int(payload.get("count", len(chunk)))
        except (TypeError, ValueError) as exc:
            raise DataContractError("FRED response count is invalid") from exc
        if count > len(chunk):
            raise IncompleteDataError(
                "FRED response was truncated",
                expected_rows=count,
                returned_rows=len(chunk),
                realtime_start=realtime_start,
                realtime_end=realtime_end,
            )
        observations.extend(chunk)

    rows = [item for item in observations if item.get("value") not in (None, ".")]
    if not rows:
        raise EmptyDataError("FRED returned no usable policy-uncertainty observations")
    frame = pd.DataFrame(rows)
    missing = sorted({"date", "realtime_start", "value"}.difference(frame.columns))
    if missing:
        raise DataContractError("FRED observation fields are incomplete", missing_fields=missing)
    observed = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    vintage = pd.to_datetime(frame["realtime_start"], errors="coerce").dt.normalize()
    values = pd.to_numeric(frame["value"], errors="coerce")
    invalid = observed.isna() | vintage.isna() | values.isna() | values.le(0)
    if invalid.any():
        raise DataContractError(
            "FRED policy-uncertainty observations are invalid",
            invalid_rows=int(invalid.sum()),
        )
    available = pd.concat([observed, vintage], axis=1).max(axis=1)
    result = pd.DataFrame(
        {
            "Date": observed,
            "AvailableDate": available,
            "PolicyUncertaintyIndex": values.astype(float),
        }
    )
    start_date = pd.Timestamp(start).normalize()
    end_date = pd.Timestamp(end).normalize()
    result = result.loc[
        result["Date"].between(start_date, end_date)
        & result["AvailableDate"].le(end_date)
    ].sort_values("Date", kind="stable").reset_index(drop=True)
    if result.empty:
        raise EmptyDataError("FRED returned no causally available observations in range")
    if result["Date"].duplicated().any():
        raise DataContractError("FRED initial-release history contains duplicate observation dates")

    metadata = {
        "vendor": "FRED",
        "vendor_interface": "fred/series/observations",
        "series_id": _SERIES_ID,
        "vintage_mode": "INITIAL_RELEASE_ONLY",
        "fred_output_type": _INITIAL_RELEASE_OUTPUT_TYPE,
        "primary_key": ["Date"],
        "source_time_field": "Date",
        "availability_time_field": "AvailableDate",
        "source_calendar": "FRED_CALENDAR_DAY",
        "available_at": "initial release date reported by ALFRED",
        "request_range_policy": "EXACT",
        "maximum_start_lag_days": 7,
    }
    return result, metadata
