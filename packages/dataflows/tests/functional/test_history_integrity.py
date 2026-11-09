from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRepairError
from dataflows.history_repair import (
    SeriesKey,
    apply_repairs_once,
    inspect_registered_source_anomalies,
    rebuild_intraday_from_1m,
)
from dataflows.history_validation import (
    inspect_intraday_against_daily,
    inspect_market_collection,
)


def _daily(trade_dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": trade_dates,
            "Open": 10.0,
            "High": 10.0,
            "Low": 10.0,
            "Close": 10.0,
            "Volume": 240.0,
            "Amount": 2400.0,
        }
    )


def _one_minute_day(trade_date: str) -> pd.DataFrame:
    day = pd.Timestamp(trade_date)
    regular = [
        *pd.date_range(day + pd.Timedelta(hours=9, minutes=31), periods=120, freq="1min"),
        *pd.date_range(day + pd.Timedelta(hours=13, minutes=1), periods=120, freq="1min"),
    ]
    timestamps = [day + pd.Timedelta(hours=9, minutes=30), *regular]
    frame = pd.DataFrame(
        {
            "Date": timestamps,
            "Open": 10.0,
            "High": 10.0,
            "Low": 10.0,
            "Close": 10.0,
            "Volume": [0.0, *([1.0] * 240)],
            "Amount": [0.0, *([10.0] * 240)],
        }
    )
    frame.loc[0, ["Open", "High", "Low", "Close"]] = 99.0
    return frame


def test_DFLS_23_C03_repair_patch_does_not_cross_symbol_boundary() -> None:
    frame = pd.DataFrame(
        [
            {
                "Date": "2020-03-09",
                "Open": 3.716,
                "High": 3.728,
                "Low": 3.317,
                "Close": 3.659,
                "Volume": 1.0,
                "Amount": 1.0,
            }
        ]
    )
    other = SeriesKey(
        "tushare", "fund_daily", "518850.SH", "etf.ohlcv", "daily", "none"
    )

    assert not inspect_registered_source_anomalies(frame, other)




def _159326_open_mismatch(
    trade_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = _daily([trade_date])
    daily.loc[0, "High"] = 10.02
    daily.loc[0, "Low"] = 9.98
    one_minute = _one_minute_day(trade_date)
    first_regular = pd.to_datetime(one_minute["Date"]).dt.strftime("%H:%M:%S").eq("09:31:00")
    one_minute.loc[first_regular, "High"] = 10.02
    one_minute.loc[first_regular, "Low"] = 9.98
    frame = rebuild_intraday_from_1m(one_minute, daily, "30m", dates=[trade_date])
    frame.loc[0, "Open"] = 10.01
    return frame, one_minute, daily


def test_DFLS_23_C01_159326_rebuilds_registered_open_mismatch() -> None:
    trade_date = "2024-10-16"
    frame, one_minute, daily = _159326_open_mismatch(trade_date)
    findings = inspect_intraday_against_daily(frame, daily, "30m").findings
    series = SeriesKey("tushare", "etf_mins", "159326.SZ", "etf.ohlcv", "30m", "none")

    repaired, records = apply_repairs_once(
        frame,
        series,
        findings,
        references={"1m": one_minute, "daily": daily},
    )

    assert [item.code for item in findings] == ["CROSS_FREQUENCY_MISMATCH"]
    assert records[0].patch_id == "TUSHARE_159326_V1"
    assert records[0].affected_dates == (trade_date,)
    assert inspect_intraday_against_daily(repaired, daily, "30m").passed


def test_DFLS_23_C02_159326_unknown_open_mismatch_is_blocked() -> None:
    trade_date = "2024-10-18"
    frame, one_minute, daily = _159326_open_mismatch(trade_date)
    findings = inspect_intraday_against_daily(frame, daily, "30m").findings
    series = SeriesKey("tushare", "etf_mins", "159326.SZ", "etf.ohlcv", "30m", "none")

    with pytest.raises(DataRepairError, match="no repair patch matched"):
        apply_repairs_once(
            frame,
            series,
            findings,
            references={"1m": one_minute, "daily": daily},
        )














def test_DFLS_23_C04_510500_unknown_minute_extrema_are_rejected():
    # These daily extremes are absent from the 1m source: keep the failure.
    unknown = _daily(["2020-03-17"])
    unknown_minute = _one_minute_day("2020-03-17").iloc[1:].reset_index(drop=True)
    unknown.loc[0, "High"] = 10.01
    unknown_findings = inspect_intraday_against_daily(unknown_minute, unknown, "1m").findings
    with pytest.raises(DataRepairError, match="no repair patch matched"):
        apply_repairs_once(unknown_minute, SeriesKey("tushare", "etf_mins", "510500.SH",
                           "etf.ohlcv", "1m", "none"), unknown_findings,
                           references={"daily": unknown})


def test_DFLS_23_C06_repair_is_not_executed_without_a_validation_finding() -> None:
    frame = _daily(["2024-01-02"])
    series = SeriesKey(
        "tushare", "fund_daily", "518880.SH", "etf.ohlcv", "daily", "none"
    )

    unchanged, records = apply_repairs_once(frame, series, ())

    pd.testing.assert_frame_equal(unchanged, frame)
    assert records == ()


def test_DFLS_16_C03_requested_start_truncation_is_a_validation_failure() -> None:
    daily = _daily(["2024-01-03"])
    calendar = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "IsOpen": [1, 1],
        }
    )

    report = inspect_market_collection(
        {"daily": daily},
        trading_calendar=calendar,
        expected_start="2024-01-02",
    )

    assert not report.passed
    finding = next(
        item for item in report.findings if item.code == "CALENDAR_COVERAGE_MISMATCH"
    )
    assert finding.context["missing"] == ["2024-01-02"]








@pytest.mark.parametrize("symbol", [
    '518850.SH',
], ids=['DFLS-23-C05'])
def test_gold_5m_volume_repair_requires_independent_bar_evidence(symbol):
    day = "2024-04-03"
    daily = _daily([day])
    minute = _one_minute_day(day)
    good = rebuild_intraday_from_1m(minute, daily, "5m", dates=(day,))
    bad = good.assign(Volume=good.Volume * 100)
    series = SeriesKey("tushare", "etf_mins", symbol, "etf.ohlcv", "5m", "none")
    findings = inspect_intraday_against_daily(bad, daily, "5m").findings
    fixed, records = apply_repairs_once(bad, series, findings,
                                        references={"daily": daily, "1m": minute})
    pd.testing.assert_frame_equal(fixed, good)
    assert records[0].affected_dates == (day,)
    assert records[0].raw_content_sha256 != records[0].repaired_content_sha256
    with pytest.raises(DataRepairError, match="1m volume evidence"):
        apply_repairs_once(bad, series, findings, references={"daily": daily})
    with pytest.raises(DataRepairError, match="unknown 100x volume signature"):
        apply_repairs_once(bad.assign(Volume=bad.Volume * 2), series, findings,
                           references={"daily": daily, "1m": minute})
