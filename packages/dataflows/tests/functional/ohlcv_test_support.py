"""Synthetic OHLCV evidence shared by DFLS tests, independent of conftest names."""
import pandas as pd
from dataflows.history_repair import frame_content_sha256
from dataflows.ohlcv_quality import build_quality_evidence


def ohlcv_fixture_metadata(
    daily, *, start, end, intraday=None, frequency="daily", listing_date="2013-01-01",
    market="a_share",
):
    """Explicit synthetic calendar and lifecycle, independent of returned rows.

    Callers supply the complete daily anchor and, for minutes, the independently
    declared full-session source even when testing a partial returned slice.
    """
    dates = pd.date_range(start, end).normalize()
    expected = dates[(dates.dayofweek < 5) & (dates >= pd.Timestamp(listing_date))]
    sessions = expected.strftime("%Y-%m-%d").tolist()
    calendar = pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"),
                             "is_open": (dates.dayofweek < 5).astype(int)})
    return {
        "daily_session_coverage": {
            "source": "declared-synthetic-weekday-calendar",
            "exchange": "HKEX" if market == "hk" else "SSE",
            "start_date": dates[0].date().isoformat(), "end_date": dates[-1].date().isoformat(),
            "listing_date": listing_date, "listing_source": "declared-synthetic-lifecycle",
            "expected_dates": sessions, "verified_sessions": len(sessions),
            "calendar": calendar.to_dict("records"),
            "calendar_sha256": frame_content_sha256(calendar),
        },
        "ohlcv_quality_evidence": build_quality_evidence(
            daily, intraday=intraday, frequency=frequency, expected_dates=sessions, market=market,
        ),
    }
