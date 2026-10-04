from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRepairError
from dataflows.history_repair import (
    REPAIR_PATCHES,
    RepairPatch,
    SeriesKey,
    apply_repairs_once,
    inspect_registered_source_anomalies,
    rebuild_intraday_from_1m,
    validate_repair_patches,
)
from dataflows.history_validation import (
    ValidationFinding,
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


def test_known_source_anomaly_fails_before_exact_repair() -> None:
    frame = pd.DataFrame(
        [
            {
                "Date": "2020-03-09",
                "Open": 3.716,
                "High": 3.728,
                "Low": 3.317,
                "Close": 3.659,
                "Volume": 711691432.0,
                "Amount": 2624195457.0,
            }
        ]
    )
    series = SeriesKey(
        "tushare", "fund_daily", "518880.SH", "etf.ohlcv", "daily", "none"
    )

    findings = inspect_registered_source_anomalies(frame, series)
    repaired, records = apply_repairs_once(frame, series, findings)

    assert [item.code for item in findings] == ["KNOWN_SOURCE_ANOMALY"]
    assert repaired.loc[0, "Low"] == 3.548
    assert len(records) == 1
    assert records[0].patch_id == "TUSHARE_518880_V2"
    assert records[0].raw_content_sha256 != records[0].repaired_content_sha256
    assert records[0].to_dict()["affected_date_count"] == 1
    assert not inspect_registered_source_anomalies(repaired, series)


def test_unknown_source_signature_is_blocked() -> None:
    frame = pd.DataFrame(
        [
            {
                "Date": "2020-03-09",
                "Open": 3.716,
                "High": 3.728,
                "Low": 3.400,
                "Close": 3.659,
                "Volume": 711691432.0,
                "Amount": 2624195457.0,
            }
        ]
    )
    series = SeriesKey(
        "tushare", "fund_daily", "518880.SH", "etf.ohlcv", "daily", "none"
    )
    findings = inspect_registered_source_anomalies(frame, series)

    assert [item.code for item in findings] == ["SOURCE_SIGNATURE_UNKNOWN"]
    with pytest.raises(DataRepairError, match="no repair patch matched"):
        apply_repairs_once(frame, series, findings)


def test_repair_patch_does_not_cross_symbol_boundary() -> None:
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


def test_rebuilt_intraday_is_revalidated_against_daily() -> None:
    one_minute = _one_minute_day("2024-01-02")
    daily = _daily(["2024-01-02"])

    rebuilt = rebuild_intraday_from_1m(
        one_minute, daily, "30m", dates=["2024-01-02"]
    )
    report = inspect_intraday_against_daily(rebuilt, daily, "30m")

    assert report.passed
    assert len(rebuilt) == 8
    assert rebuilt[["Open", "High", "Low", "Close"]].eq(10.0).all().all()


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


def test_159326_rebuilds_registered_open_mismatch() -> None:
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


def test_159326_unknown_open_mismatch_is_blocked() -> None:
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


def test_518880_rebuild_is_limited_to_registered_dates() -> None:
    registered_date = "2015-07-16"
    ordinary_date = "2015-07-17"
    daily = _daily([registered_date, ordinary_date])
    one_minute = pd.concat(
        [_one_minute_day(registered_date), _one_minute_day(ordinary_date)],
        ignore_index=True,
    )
    frame = rebuild_intraday_from_1m(
        one_minute, daily, "30m", dates=[registered_date, ordinary_date]
    )
    frame.loc[
        pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d").eq(registered_date),
        "High",
    ] = 9.0
    ordinary_before = frame.loc[
        pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d").eq(ordinary_date)
    ].copy()
    series = SeriesKey(
        "tushare", "etf_mins", "518880.SH", "etf.ohlcv", "30m", "none"
    )
    findings = (
        ValidationFinding(
            "INVALID_OHLCV",
            "registered source anomaly",
            {"timestamps": [f"{registered_date} 10:00:00"]},
        ),
    )

    repaired, records = apply_repairs_once(
        frame,
        series,
        findings,
        references={"1m": one_minute, "daily": daily},
    )

    assert records[0].affected_dates == (registered_date,)
    pd.testing.assert_frame_equal(
        repaired.loc[
            pd.to_datetime(repaired["Date"])
            .dt.strftime("%Y-%m-%d")
            .eq(ordinary_date)
        ].reset_index(drop=True),
        ordinary_before.reset_index(drop=True),
        check_dtype=False,
    )
    assert inspect_intraday_against_daily(repaired, daily, "30m").passed


def test_518880_unknown_rebuild_date_is_blocked() -> None:
    trade_date = "2015-07-17"
    daily = _daily([trade_date])
    one_minute = _one_minute_day(trade_date)
    frame = rebuild_intraday_from_1m(one_minute, daily, "30m", dates=[trade_date])
    frame.loc[0, "High"] = 9.0
    series = SeriesKey(
        "tushare", "etf_mins", "518880.SH", "etf.ohlcv", "30m", "none"
    )
    findings = (
        ValidationFinding(
            "INVALID_OHLCV",
            "unknown source anomaly",
            {"timestamps": [f"{trade_date} 10:00:00"]},
        ),
    )

    with pytest.raises(DataRepairError, match="no repair patch matched"):
        apply_repairs_once(
            frame,
            series,
            findings,
            references={"1m": one_minute, "daily": daily},
        )


def test_518800_rebuild_aligns_registered_daily_activity() -> None:
    trade_date = "2014-02-18"
    daily = _daily([trade_date])
    daily.loc[0, "Volume"] = 480.0
    one_minute = _one_minute_day(trade_date)
    frame = rebuild_intraday_from_1m(one_minute, _daily([trade_date]), "30m", dates=[trade_date])
    series = SeriesKey(
        "tushare", "etf_mins", "518800.SH", "etf.ohlcv", "30m", "none"
    )
    findings = (
        ValidationFinding(
            "CROSS_FREQUENCY_MISMATCH",
            "registered source anomaly",
            {"fields_by_date": {trade_date: ["Volume"]}},
        ),
    )

    repaired, records = apply_repairs_once(
        frame,
        series,
        findings,
        references={"1m": one_minute, "daily": daily},
    )

    assert records[0].patch_id == "TUSHARE_518800_V1"
    assert records[0].affected_dates == (trade_date,)
    assert repaired["Volume"].sum() == pytest.approx(480.0)
    assert inspect_intraday_against_daily(repaired, daily, "30m").passed


def test_518800_unknown_rebuild_date_is_blocked() -> None:
    trade_date = "2014-02-19"
    daily = _daily([trade_date])
    one_minute = _one_minute_day(trade_date)
    frame = rebuild_intraday_from_1m(one_minute, daily, "30m", dates=[trade_date])
    series = SeriesKey(
        "tushare", "etf_mins", "518800.SH", "etf.ohlcv", "30m", "none"
    )
    findings = (
        ValidationFinding(
            "INVALID_OHLCV",
            "unknown source anomaly",
            {"timestamps": [f"{trade_date} 10:00:00"]},
        ),
    )

    with pytest.raises(DataRepairError, match="no repair patch matched"):
        apply_repairs_once(
            frame,
            series,
            findings,
            references={"1m": one_minute, "daily": daily},
        )


def test_one_vendor_symbol_patch_handles_multiple_series_repairs() -> None:
    volume_date = "2024-04-03"
    missing_date = "2024-10-30"
    daily = _daily([volume_date, missing_date])
    one_minute = pd.concat(
        [_one_minute_day(volume_date), _one_minute_day(missing_date)],
        ignore_index=True,
    )
    frame = rebuild_intraday_from_1m(
        one_minute, daily, "15m", dates=[volume_date, missing_date]
    )
    trade_dates = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
    frame = frame.loc[trade_dates.ne(missing_date)].reset_index(drop=True)
    volume_rows = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d").eq(
        volume_date
    )
    frame.loc[volume_rows, "Volume"] *= 100
    findings = inspect_intraday_against_daily(frame, daily, "15m").findings
    series = SeriesKey(
        "tushare", "etf_mins", "510500.SH", "etf.ohlcv", "15m", "none"
    )

    repaired, records = apply_repairs_once(
        frame,
        series,
        findings,
        references={"1m": one_minute, "daily": daily},
    )

    assert len(records) == 1
    assert records[0].patch_id == "TUSHARE_510500_V1"
    assert records[0].affected_dates == (volume_date, missing_date)
    assert inspect_intraday_against_daily(repaired, daily, "15m").passed


def test_repair_is_not_executed_without_a_validation_finding() -> None:
    frame = _daily(["2024-01-02"])
    series = SeriesKey(
        "tushare", "fund_daily", "518880.SH", "etf.ohlcv", "daily", "none"
    )

    unchanged, records = apply_repairs_once(frame, series, ())

    pd.testing.assert_frame_equal(unchanged, frame)
    assert records == ()


def test_requested_start_truncation_is_a_validation_failure() -> None:
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


def test_invalid_daily_and_empty_calendar_return_findings_instead_of_crashing() -> None:
    invalid_daily = _daily(["2024-01-02"])
    invalid_daily.loc[0, "High"] = float("inf")

    report = inspect_market_collection(
        {"daily": invalid_daily},
        trading_calendar=pd.DataFrame(columns=["Date", "IsOpen"]),
    )

    assert not report.passed
    assert [item.code for item in report.findings] == ["NON_NUMERIC_VALUE"]

    empty_calendar_report = inspect_market_collection(
        {"daily": _daily(["2024-01-02"])},
        trading_calendar=pd.DataFrame(columns=["Date", "IsOpen"]),
    )
    assert [item.code for item in empty_calendar_report.findings] == [
        "INVALID_CALENDAR"
    ]


def test_repair_registry_rejects_duplicate_vendor_symbol_patches() -> None:
    def executor(dataframe, patch, series, findings, references):
        del patch, series, findings, references
        return dataframe.copy(), ()

    left = RepairPatch(
        patch_id="LEFT",
        patch_version=1,
        vendor="tushare",
        symbol="510500.SH",
        execute=executor,
    )
    right = RepairPatch(
        patch_id="RIGHT",
        patch_version=1,
        vendor="tushare",
        symbol="510500.SH",
        execute=executor,
    )

    with pytest.raises(DataRepairError, match="duplicate vendor-symbol"):
        validate_repair_patches((left, right))


def test_repair_registry_is_managed_by_vendor_and_symbol() -> None:
    assert {
        (patch.vendor, patch.symbol): patch.patch_id for patch in REPAIR_PATCHES
    } == {
        ("tushare", "159326.SZ"): "TUSHARE_159326_V1",
        ("tushare", "510500.SH"): "TUSHARE_510500_V1",
        ("tushare", "512100.SH"): "TUSHARE_512100_V1",
        ("tushare", "515050.SH"): "TUSHARE_515050_V1",
        ("tushare", "518800.SH"): "TUSHARE_518800_V1",
        ("tushare", "518880.SH"): "TUSHARE_518880_V2",
        ("tushare", "518850.SH"): "TUSHARE_518850_V1",
        ("tushare", "588080.SH"): "TUSHARE_588080_V1",
    }


@pytest.mark.parametrize("symbol", ["518850.SH", "518880.SH"])
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


def test_gold_5m_price_defects_are_not_overwritten_by_volume_patch():
    day = "2024-04-03"
    daily = _daily([day]); minute = _one_minute_day(day)
    bad = rebuild_intraday_from_1m(minute, daily, "5m", dates=(day,))
    bad.loc[0, ["Open", "High"]] = 11.
    series = SeriesKey("tushare", "etf_mins", "518850.SH", "etf.ohlcv", "5m", "none")
    findings = inspect_intraday_against_daily(bad, daily, "5m").findings
    with pytest.raises(DataRepairError, match="no repair patch matched"):
        apply_repairs_once(bad, series, findings, references={"daily": daily, "1m": minute})
