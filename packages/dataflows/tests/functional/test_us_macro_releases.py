from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.tushare_strategy_data import (
    fetch_us_federal_budget_release,
    fetch_us_ism_pmi_release,
    fetch_us_nominal_yield_daily,
)


class FakePro:
    def __init__(self, rows: list[dict[str, str]] | None = None, *, gap: bool = False) -> None:
        self.rows = rows or []
        self.gap = gap

    def us_tycr(self, **kwargs):
        return pd.DataFrame({"date": [kwargs["start_date"]], "y10": [4.25]})

    def eco_cal(self, **kwargs):
        return pd.DataFrame([
            row for row in self.rows
            if kwargs["start_date"] <= row["date"] <= kwargs["end_date"]
        ])

    def trade_cal(self, **kwargs):
        days = pd.date_range(kwargs["start_date"], kwargs["end_date"], freq="D")
        if self.gap:
            days = days[days != pd.Timestamp("2024-01-13")]
        return pd.DataFrame({
            "cal_date": days.strftime("%Y%m%d"),
            "is_open": [int(day.weekday() < 5) for day in days],
        })


def _event(day: str, clock: str, name: str, value: str) -> dict[str, str]:
    return {"date": day, "time": clock, "event": name, "value": value}


def test_nominal_yield_publication_uses_percent_and_identity() -> None:
    pro = FakePro()
    flow = Dataflows({
        Dataset.US_NOMINAL_YIELD_DAILY.value: lambda _: fetch_us_nominal_yield_daily(
            "2024-01-12", "2024-01-12", pro=pro
        )
    })
    result = flow.fetch(DataRequest(
        Dataset.US_NOMINAL_YIELD_DAILY, None, "2024-01-12", "2024-01-12", None
    ))
    assert result.status is DataStatus.READY
    assert result.dataframe["NominalYield10YPercent"].tolist() == [4.25]
    assert result.identity.metadata["vendor_interface"] == "us_tycr"


def test_ism_pmi_uses_first_later_sse_session_and_filters_other_events() -> None:
    pro = FakePro([
        _event("20240112", "23:00", "美国ISM制造业PMI(十二月)", "47.2"),
        _event("20240112", "22:00", "美国ISM非制造业PMI", "52.0"),
    ])
    frame, metadata = fetch_us_ism_pmi_release("2024-01-12", "2024-01-12", pro=pro)
    assert frame["Date"].tolist() == [pd.Timestamp("2024-01-12")]
    assert frame["AvailableDate"].tolist() == [pd.Timestamp("2024-01-15")]
    assert frame["PmiIndex"].tolist() == [47.2]
    assert metadata["source_time_precision"] == "date_only"


def test_budget_conservatively_handles_unknown_clock_and_excludes_budget_bill() -> None:
    pro = FakePro([
        _event("20240112", "待公布", "美国政府预算(美元)(十二月)", "-367.0B"),
        _event("20240113", "02:00", "美国联邦政府预算案", "-1,837.0B"),
    ])
    frame, metadata = fetch_us_federal_budget_release("2024-01-12", "2024-01-13", pro=pro)
    assert frame["BudgetBalanceBillionUSD"].tolist() == [-367.0]
    assert frame["AvailableDate"].tolist() == [pd.Timestamp("2024-01-15")]
    assert metadata["unverified_source_clock_rows"] == 1


@pytest.mark.parametrize(
    ("rows", "gap", "expected"),
    [
        ([_event("20240112", "14:00", "美国ISM制造业PMI", "47.2")], False, DataStatus.FAILED),
        ([_event("20240112", "23:00", "美国ISM制造业PMI", "oops")], False, DataStatus.FAILED),
        ([_event("20240112", "23:00", "美国ISM制造业PMI", "47.2")] * 2, False, DataStatus.FAILED),
        ([_event("20240112", "23:00", "美国ISM制造业PMI", "47.2")], True, DataStatus.INCOMPLETE),
    ],
)
def test_pmi_fails_closed_on_invalid_source_or_calendar(rows, gap, expected) -> None:
    pro = FakePro(rows, gap=gap)
    flow = Dataflows({
        Dataset.US_ISM_PMI_RELEASE.value: lambda _: fetch_us_ism_pmi_release(
            "2024-01-12", "2024-01-12", pro=pro
        )
    })
    result = flow.fetch(DataRequest(
        Dataset.US_ISM_PMI_RELEASE, None, "2024-01-12", "2024-01-12", None
    ))
    assert result.status is expected
    assert result.identity is None


def test_monthly_release_rejects_same_day_availability() -> None:
    pro = FakePro([_event("20240112", "23:00", "美国ISM制造业PMI", "47.2")])
    frame, metadata = fetch_us_ism_pmi_release("2024-01-12", "2024-01-12", pro=pro)
    frame.loc[0, "AvailableDate"] = frame.loc[0, "Date"]
    flow = Dataflows({Dataset.US_ISM_PMI_RELEASE.value: lambda _: (frame, metadata)})
    result = flow.fetch(DataRequest(
        Dataset.US_ISM_PMI_RELEASE, None, "2024-01-12", "2024-01-12", None
    ))
    assert result.status is DataStatus.FAILED
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
