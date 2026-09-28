from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.errors import DataContractError, IncompleteDataError
from dataflows.tushare_sell_side import fetch_sell_side_forecast


def _row(
    report_date: str,
    *,
    symbol: str = "600406.SH",
    quarter: str | None = "2026Q4",
    net_profit: object = "812300",
    create_time: str | None = None,
) -> dict[str, object]:
    return {
        "ts_code": symbol,
        "name": "国电南瑞",
        "report_date": report_date,
        "report_title": f"盈利预测-{report_date}",
        "report_type": "点评",
        "classify": "一般报告",
        "org_name": "测试证券",
        "author_name": "研究员甲",
        "quarter": quarter,
        "op_rt": "6200000",
        "op_pr": None,
        "tp": "1050000",
        "np": net_profit,
        "eps": "0.80",
        "pe": "25.0",
        "rd": None,
        "roe": "18.0",
        "ev_ebitda": None,
        "rating": "买入",
        "max_price": "32.0",
        "min_price": None,
        "create_time": create_time
        or f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:]} 21:15:00",
    }


class FakePro:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        calendar_gap: str | None = None,
    ) -> None:
        self.rows = rows
        self.calendar_gap = calendar_gap
        self.report_calls: list[dict[str, str]] = []

    def report_rc(self, **kwargs):
        self.report_calls.append(kwargs)
        frame = pd.DataFrame(
            row
            for row in self.rows
            if kwargs["start_date"] <= str(row["report_date"]) <= kwargs["end_date"]
        )
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", len(frame))
        return frame.iloc[offset : offset + limit].reset_index(drop=True)

    def trade_cal(self, **kwargs):
        days = pd.date_range(kwargs["start_date"], kwargs["end_date"], freq="D")
        if self.calendar_gap is not None:
            days = days[days != pd.Timestamp(self.calendar_gap)]
        return pd.DataFrame(
            {
                "cal_date": days.strftime("%Y%m%d"),
                "is_open": [int(day.weekday() < 5) for day in days],
            }
        )


def _request() -> DataRequest:
    return DataRequest(
        Dataset.SELL_SIDE_FORECAST,
        "600406.SH",
        "2024-12-31",
        "2025-01-03",
        None,
    )


def test_sell_side_forecast_is_canonical_causal_and_year_partitioned() -> None:
    pro = FakePro([_row("20241231"), _row("20250103", quarter=None, net_profit=None)])

    frame, metadata = fetch_sell_side_forecast(
        "600406.SH", "2024-12-31", "2025-01-03", pro=pro
    )

    assert [call["start_date"] for call in pro.report_calls] == ["20241231", "20250101"]
    assert all(call["limit"] == 3000 and call["offset"] == 0 for call in pro.report_calls)
    assert frame["Date"].tolist() == [pd.Timestamp("2024-12-31"), pd.Timestamp("2025-01-03")]
    assert frame["AvailableDate"].tolist() == [
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-06"),
    ]
    assert frame.loc[0, "NetProfitForecast"] == pytest.approx(812300.0)
    assert pd.isna(frame.loc[1, "NetProfitForecast"])
    assert metadata["vendor_interface"] == "report_rc"
    assert metadata["point_in_time_mode"] == "CURRENT_VENDOR_SNAPSHOT"
    assert metadata["historical_revision_identity"] == "unavailable_from_vendor"
    assert metadata["field_units"]["NetProfitForecast"] == "CNY_10000"


def test_sell_side_forecast_waits_past_late_vendor_creation() -> None:
    frame, _ = fetch_sell_side_forecast(
        "600406.SH",
        "2025-02-09",
        "2025-02-09",
        pro=FakePro([_row("20250209", create_time="2025-02-10 21:06:32")]),
    )

    assert frame.loc[0, "AvailableDate"] == pd.Timestamp("2025-02-11")


def test_default_facade_publishes_sell_side_forecast_with_identity(monkeypatch) -> None:
    pro = FakePro([_row("20250103")])
    monkeypatch.setattr(
        "dataflows.tushare_sell_side.get_tushare_pro", lambda ignored=None: pro
    )

    result = Dataflows().fetch(_request())

    assert Dataset.SELL_SIDE_FORECAST.value in Dataflows().datasets
    assert result.status is DataStatus.READY
    assert result.identity is not None
    assert result.identity.dataset == Dataset.SELL_SIDE_FORECAST.value
    assert result.identity.symbol == "600406.SH"
    assert result.identity.metadata["availability_time_field"] == "AvailableDate"
    assert result.dataframe["AvailableDate"].gt(result.dataframe["Date"]).all()


@pytest.mark.parametrize(
    ("rows", "gap", "error"),
    [
        ([_row("20250103", symbol="000001.SZ")], None, DataContractError),
        ([_row("20250103", net_profit="not-a-number")], None, DataContractError),
        ([_row("20250103")], "2025-01-04", IncompleteDataError),
    ],
)
def test_sell_side_forecast_fails_closed_on_identity_value_or_calendar(
    rows, gap, error
) -> None:
    with pytest.raises(error):
        fetch_sell_side_forecast(
            "600406.SH",
            "2025-01-03",
            "2025-01-03",
            pro=FakePro(rows, calendar_gap=gap),
        )


def test_facade_rejects_same_day_sell_side_availability() -> None:
    frame, metadata = fetch_sell_side_forecast(
        "600406.SH",
        "2025-01-03",
        "2025-01-03",
        pro=FakePro([_row("20250103")]),
    )
    frame.loc[0, "AvailableDate"] = frame.loc[0, "Date"]

    result = Dataflows(
        {Dataset.SELL_SIDE_FORECAST.value: lambda ignored: (frame, metadata)}
    ).fetch(_request())

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
