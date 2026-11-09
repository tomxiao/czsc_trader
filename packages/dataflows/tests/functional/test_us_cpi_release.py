from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset, PreparePolicy
from dataflows.tushare_strategy_data import fetch_us_cpi_release


class FakeCpiPro:
    def __init__(self, rows: list[dict[str, str]], *, calendar_gap: bool = False) -> None:
        self.rows = rows
        self.calendar_gap = calendar_gap
        self.eco_calls: list[dict[str, str]] = []

    def eco_cal(self, **kwargs):
        self.eco_calls.append(kwargs)
        return pd.DataFrame(
            row for row in self.rows if kwargs["start_date"] <= row["date"] <= kwargs["end_date"]
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


def test_DFLS_29_C03_us_cpi_release_facade_rejects_missing_actual_value(flow_factory) -> None:
    # The source adapter converts an empty actual to NaN. Numeric admission is
    # owned by the public facade, so this boundary must include preparation.
    pro = FakeCpiPro([_row("20240112", "21:30", "")])
    flow = flow_factory(
        {
            Dataset.US_CPI_RELEASE.value: lambda _: fetch_us_cpi_release(
                "2024-01-12", "2024-01-12", pro=pro
            )
        }
    )
    prepared = flow.prepare(
        (DataRequest(Dataset.US_CPI_RELEASE, None, "2024-01-12", "2024-01-12", None),),
        policy=PreparePolicy.REFRESH,
    )
    assert not prepared.ready and prepared.reference is None
    (item,) = prepared.items
    assert item.status is DataStatus.FAILED and item.identity is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"
    assert item.error.context["field"] == "YoYPercent"


@pytest.mark.parametrize(
    "day,clock,through,expected",
    [
        ("20240112", "21:30", "2024-01-31", "2024-01-15"),
        ("20240711", "20:30", "2024-07-31", "2024-07-12"),
    ],
    ids=["DFLS-29-C01", "DFLS-29-C02"],
)
def test_cpi_release_clock_and_actual_value(day, clock, through, expected):
    pro = FakeCpiPro([{**_row(day, clock), "forecast": "99.9%"}])
    frame, meta = fetch_us_cpi_release(through[:8] + "01", through, pro=pro)
    assert frame.YoYPercent.tolist() == [3.4]
    assert frame.AvailableDate.tolist() == [pd.Timestamp(expected)]
    assert frame.ReleaseAt.dt.tz_convert("America/New_York").dt.strftime("%H:%M").tolist() == [
        "08:30"
    ]
    assert meta["official_release_timezone"] == "America/New_York"
