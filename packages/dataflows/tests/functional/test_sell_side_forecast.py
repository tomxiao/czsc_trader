from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, Dataset
from dataflows.tushare_sell_side import fetch_sell_side_forecast


@pytest.fixture(autouse=True)
def _disable_vendor_wait(monkeypatch) -> None:
    monkeypatch.setattr(
        "dataflows.tushare_sell_side._MIN_REQUEST_INTERVAL_SECONDS", 0.0
    )
    monkeypatch.setattr("dataflows.tushare_sell_side.time.sleep", lambda ignored: None)


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
        transient_report_failures: int = 0,
    ) -> None:
        self.rows = rows
        self.calendar_gap = calendar_gap
        self.transient_report_failures = transient_report_failures
        self.report_calls: list[dict[str, str]] = []

    def report_rc(self, **kwargs):
        self.report_calls.append(kwargs)
        if self.transient_report_failures:
            self.transient_report_failures -= 1
            raise RuntimeError("temporary vendor throttle")
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




def test_DFLS_30_C03_sell_side_forecast_waits_past_late_vendor_creation() -> None:
    frame, _ = fetch_sell_side_forecast(
        "600406.SH",
        "2025-02-09",
        "2025-02-09",
        pro=FakePro([_row("20250209", create_time="2025-02-10 21:06:32")]),
    )

    assert frame.loc[0, "AvailableDate"] == pd.Timestamp("2025-02-11")


def test_DFLS_30_C04_sell_side_forecast_retries_transient_vendor_failure() -> None:
    pro = FakePro([_row("20250103")], transient_report_failures=1)

    frame, _ = fetch_sell_side_forecast(
        "600406.SH", "2025-01-03", "2025-01-03", pro=pro
    )

    assert len(frame) == 1
    assert len(pro.report_calls) == 2
