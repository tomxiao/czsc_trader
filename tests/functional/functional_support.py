from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

import pandas as pd

from czsc_trader.backtesting.execution_data import BacktestExecutionData


@dataclass(frozen=True)
class ReplayFixture:
    root: Path
    adjusted: object
    execution_daily: pd.DataFrame
    execution_intraday: pd.DataFrame
    fingerprint: str
    cutoff: date
    execution_five_minute: pd.DataFrame | None = None


def replay_fingerprint(*frames: pd.DataFrame) -> str:
    digest = sha256()
    for frame in frames:
        digest.update(frame.to_csv(index=False).encode())
    return digest.hexdigest()


def execution_data_from_replay(replay, *, start, end) -> BacktestExecutionData:
    daily = replay.execution_daily.copy()
    sessions = pd.DatetimeIndex(pd.to_datetime(daily["dt"]).dt.normalize(), name="dt")
    sessions = sessions[
        (sessions >= pd.Timestamp(start).normalize())
        & (sessions <= pd.Timestamp(end).normalize())
    ]
    return BacktestExecutionData(
        replay.root,
        replay.adjusted.symbol,
        replay.adjusted.asset_type,
        replay.adjusted.daily.copy(),
        daily,
        replay.execution_intraday.copy(),
        replay.fingerprint,
        replay.cutoff,
        sessions,
        replay.execution_five_minute,
    )

def vendor_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Date": timestamp,
                "Open": close,
                "High": close,
                "Low": close,
                "Close": close,
                "Volume": 1000.0,
                "Amount": close * 1000.0,
            }
            for timestamp, close in rows
        ]
    )


def synthetic_ohlcv_evidence(request, frame, daily, *, adjustment="none"):
    """Synthetic providers obey the same calendar and quality contract as real providers."""
    from dataflows.history_repair import frame_content_sha256
    from dataflows.ohlcv_quality import build_quality_evidence, bind_quality_frame

    days = pd.date_range(pd.Timestamp(request.start).normalize(), pd.Timestamp(request.end).normalize())
    calendar = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"),
                             "is_open": (days.weekday < 5).astype(int)})
    listing = pd.to_datetime(daily.Date).min().date().isoformat()
    expected = calendar.loc[calendar.is_open.eq(1) & calendar.Date.ge(listing), "Date"].tolist()
    dates = pd.to_datetime(daily.Date).dt.strftime("%Y-%m-%d")
    selected = daily.loc[dates.isin(expected)].reset_index(drop=True)
    quality = build_quality_evidence(
        selected, expected_dates=expected, frequency=request.frequency,
        intraday=frame if request.frequency != "daily" else None,
    )
    quality = bind_quality_frame(quality, frame, adjustment=adjustment, daily=selected)
    return {
        "ohlcv_quality_evidence": quality,
        "daily_session_coverage": {
            "exchange": "SSE" if request.symbol.endswith(".SH") else "SZSE",
            "start_date": calendar.Date.iloc[0], "end_date": calendar.Date.iloc[-1],
            "listing_date": listing, "source": "synthetic-weekday-calendar",
            "listing_source": "synthetic-fixture-start",
            "calendar": calendar.to_dict("records"),
            "calendar_sha256": frame_content_sha256(calendar),
            "expected_dates": expected, "verified_sessions": len(expected),
        },
    }


def invoke_main(arguments: list[str], capsys) -> dict:
    from czsc_trader.cli.main import main

    exit_code = main(arguments)
    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    assert exit_code == 0, payload
    assert payload["status"] == "PASS", payload
    return payload


def invoke_main_failure(arguments: list[str], capsys) -> dict:
    from czsc_trader.cli.main import main

    exit_code = main(arguments)
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert exit_code != 0
    assert payload["status"] == "FAIL"
    return payload
