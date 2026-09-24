from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.tushare_strategy_data import fetch_us_cpi_release


class FakeCpiPro:
    def __init__(self, rows: list[dict[str, str]], *, calendar_gap: bool = False) -> None:
        self.rows = rows
        self.calendar_gap = calendar_gap
        self.eco_calls: list[dict[str, str]] = []

    def eco_cal(self, **kwargs):
        self.eco_calls.append(kwargs)
        return pd.DataFrame(
            row for row in self.rows
            if kwargs["start_date"] <= row["date"] <= kwargs["end_date"]
        )

    def trade_cal(self, **kwargs):
        days = pd.date_range(kwargs["start_date"], kwargs["end_date"], freq="D")
        if self.calendar_gap:
            days = days[days != pd.Timestamp("2024-01-13")]
        return pd.DataFrame(
            {
                "cal_date": days.strftime("%Y%m%d"),
                "is_open": [int(day.weekday() < 5) for day in days],
            }
        )


def _row(day: str, clock: str, value: str = "3.4%") -> dict[str, str]:
    return {
        "date": day,
        "time": clock,
        "event": "美国未季调CPI年率(%)",
        "value": value,
    }


def test_us_cpi_release_converts_both_dst_clocks_and_delays_until_next_sse_session() -> None:
    pro = FakeCpiPro([
        _row("20240112", "21:30"),
        _row("20240711", "20:30", "3.0%"),
    ])
    winter, metadata = fetch_us_cpi_release("2024-01-01", "2024-01-31", pro=pro)
    summer, _ = fetch_us_cpi_release("2024-07-01", "2024-07-31", pro=pro)
    frame = pd.concat([winter, summer], ignore_index=True)

    assert frame["Date"].tolist() == [pd.Timestamp("2024-01-12"), pd.Timestamp("2024-07-11")]
    assert frame["AvailableDate"].tolist() == [
        pd.Timestamp("2024-01-15"),
        pd.Timestamp("2024-07-12"),
    ]
    assert frame["ReleaseAt"].dt.strftime("%Y-%m-%dT%H:%M:%S%z").tolist() == [
        "2024-01-12T21:30:00+0800",
        "2024-07-11T20:30:00+0800",
    ]
    assert frame["YoYPercent"].tolist() == [3.4, 3.0]
    assert metadata["source_time_field"] == "ReleaseAt"
    assert metadata["official_release_timezone"] == "America/New_York"
    assert len(pro.eco_calls) == 2


def test_us_cpi_release_splits_vendor_queries_by_year() -> None:
    pro = FakeCpiPro([
        _row("20131217", "21:30"),
        _row("20140116", "21:30"),
    ])

    frame, _ = fetch_us_cpi_release("2013-12-01", "2014-01-31", pro=pro)

    assert len(frame) == 2
    assert [call["start_date"] for call in pro.eco_calls] == ["20131201", "20140101"]


@pytest.mark.parametrize(
    ("rows", "calendar_gap", "expected_status"),
    [
        ([_row("20240112", "20:30")], False, DataStatus.FAILED),
        ([_row("20240112", "21:30", "")], False, DataStatus.FAILED),
        ([_row("20240112", "21:30"), _row("20240112", "21:30")], False, DataStatus.FAILED),
        ([_row("20240112", "21:30")], True, DataStatus.INCOMPLETE),
    ],
)
def test_us_cpi_release_fails_closed_on_source_or_calendar_errors(
    rows: list[dict[str, str]], calendar_gap: bool, expected_status: DataStatus
) -> None:
    pro = FakeCpiPro(rows, calendar_gap=calendar_gap)
    flow = Dataflows({
        Dataset.US_CPI_RELEASE.value: lambda _: fetch_us_cpi_release(
            "2024-01-12", "2024-01-12", pro=pro
        )
    })

    result = flow.fetch(DataRequest(Dataset.US_CPI_RELEASE, None, "2024-01-12", "2024-01-12", None))

    assert result.status is expected_status
    assert result.dataframe.empty
    assert result.identity is None
    assert result.error is not None


def test_us_cpi_release_rejects_missing_monthly_history() -> None:
    pro = FakeCpiPro([
        _row("20240112", "21:30"),
        _row("20240312", "20:30"),
    ])

    flow = Dataflows({
        Dataset.US_CPI_RELEASE.value: lambda _: fetch_us_cpi_release(
            "2024-01-12", "2024-03-12", pro=pro
        )
    })
    result = flow.fetch(
        DataRequest(Dataset.US_CPI_RELEASE, None, "2024-01-12", "2024-03-12", None)
    )

    assert result.status is DataStatus.INCOMPLETE
    assert result.identity is None


def test_us_cpi_release_facade_publishes_identity_and_excludes_forecast() -> None:
    pro = FakeCpiPro([_row("20240112", "21:30")])
    flow = Dataflows({
        Dataset.US_CPI_RELEASE.value: lambda _: fetch_us_cpi_release(
            "2024-01-12", "2024-01-12", pro=pro
        )
    })

    result = flow.fetch(
        DataRequest(Dataset.US_CPI_RELEASE, None, "2024-01-12", "2024-01-12", "2024-01-12")
    )

    assert result.status is DataStatus.READY
    assert result.identity is not None
    assert result.identity.source == "tushare"
    assert result.identity.metadata["available_at"].startswith("first SSE open day")
    assert "Forecast" not in result.dataframe.columns


def test_us_cpi_release_facade_rejects_same_day_availability_from_any_provider() -> None:
    pro = FakeCpiPro([_row("20240112", "21:30")])
    frame, metadata = fetch_us_cpi_release("2024-01-12", "2024-01-12", pro=pro)
    frame.loc[0, "AvailableDate"] = frame.loc[0, "Date"]
    flow = Dataflows({Dataset.US_CPI_RELEASE.value: lambda _: (frame, metadata)})

    result = flow.fetch(
        DataRequest(Dataset.US_CPI_RELEASE, None, "2024-01-12", "2024-01-12", None)
    )

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
