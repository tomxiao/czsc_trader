"""SZSE ETF creation/redemption baskets have explicit completeness and time semantics."""

from __future__ import annotations

import pandas as pd
import pytest
from types import SimpleNamespace

from dataflows import DataRequest, DataStatus, Dataset, PcfParameters
from dataflows import chinaamc_pcf, tushare_pcf
from dataflows.errors import DataContractError, IncompleteDataError


def _row(day: str, code: str = "600089.SH", **changes) -> dict:
    row = {
        "trade_date": day,
        "ts_code": "159326.SZ",
        "con_code": code,
        "con_name": "成份股",
        "qty": 100,
        "sub_flag": "允许",
        "cpr": 10.0,
        "rdr": 0.0,
        "sub_cc": 0.0,
        "red_cc": 0.0,
        "exchange": "SH",
    }
    row.update(changes)
    return row


class FakePro:
    def __init__(self, rows: list[dict], open_dates: tuple[str, ...]) -> None:
        self.rows = rows
        self.open_dates = open_dates
        self.basket_calls: list[dict] = []

    def etf_sz_cons(self, **kwargs):
        self.basket_calls.append(kwargs)
        return pd.DataFrame(
            [
                row
                for row in self.rows
                if kwargs["start_date"] <= row["trade_date"] <= kwargs["end_date"]
            ]
        )

    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            {"cal_date": list(self.open_dates), "is_open": [1] * len(self.open_dates)}
        )


@pytest.fixture(scope="module")
def basket_source():
    pro = FakePro([_row("20250303")], ("20250303", "20250304"))
    return tushare_pcf.fetch_etf_creation_redemption_basket(
        "159326.SZ",
        "2025-03-03",
        "2025-03-03",
        pro=pro,
    )


def _official_xml(quantity: int = 100, day: str = "20250303") -> bytes:
    return (
        "<PCFFile><SecurityID>159326</SecurityID><TradingDay>"
        + day
        + "</TradingDay><RecordNum>0</RecordNum><TotalRecordNum>1</TotalRecordNum>"
        "<Components><Component><UnderlyingSecurityID>600089"
        "</UnderlyingSecurityID><UnderlyingSecurityIDSource>101"
        "</UnderlyingSecurityIDSource><ComponentShare>"
        + str(quantity)
        + "</ComponentShare></Component></Components></PCFFile>"
    ).encode()


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "date",
    ],
    ids=["DFLS-33-C05", "DFLS-33-C06"],
)
def test_optional_official_pcf_check_verifies_content_without_claiming_vintage(
    clone_published_flow, publish_data, monkeypatch, defect
) -> None:
    pro = FakePro([_row("20250303")], ("20250303", "20250304"))
    monkeypatch.setattr(tushare_pcf, "get_tushare_pro", lambda _env: pro)
    calls = []
    payload = _official_xml()

    def fake_post(path, data):
        calls.append((path, data))
        if path == "tradeList":
            return SimpleNamespace(
                json=lambda: {
                    "status": 1,
                    "data": {
                        "fileName": "pcf_159326_20250303.xml",
                        "year": None,
                    },
                }
            )
        return SimpleNamespace(content=payload)

    monkeypatch.setattr(chinaamc_pcf, "_post", fake_post)
    request = DataRequest(
        Dataset.ETF_CREATION_REDEMPTION_BASKET,
        "159326.SZ",
        "2025-03-03",
        "2025-03-03",
        None,
        "daily",
        PcfParameters(verify_official_pcf_components=True),
    )
    flows, result = clone_published_flow("official-basket", None, request)
    calls.clear()

    assert result.status is DataStatus.READY
    assert result.identity is not None
    metadata = result.identity.metadata
    assert metadata["official_pcf_code_quantity_verified"] is True
    assert metadata["official_pcf_component_count"] == 1
    assert metadata["official_pcf_publication_timestamp_verified"] is False
    assert metadata["official_pcf_historical_revisions_verified"] is False
    assert metadata["source_publication_timestamp_verified"] is False
    assert metadata["historical_revision_history_verified"] is False
    if defect is None:
        current = publish_data(flows, request)
        assert current.ready, current.error
        assert current.identity.metadata == metadata
    else:
        payload = {
            "quantity": _official_xml(quantity=99),
            "date": _official_xml(day="20250304"),
            "xml": b"bad xml",
        }[defect]
        failed = publish_data(flows, request)
        assert failed.status is DataStatus.FAILED
        assert failed.error.code == "DATA_CONTRACT_MISMATCH"
    assert [path for path, _ in calls] == ["tradeList", "query/etfDownload"]
    assert calls[1][1]["fileName"] == "pcf_159326_20250303.xml"
    old = flows.fetch(request, prepared=result.prepared)
    assert old.ready and old.identity.content_sha256 == result.identity.content_sha256


def test_DFLS_33_C01_cross_month_basket_availability() -> None:
    pro = FakePro(
        [_row("20250331"), _row("20250401")],
        ("20250331", "20250401", "20250402"),
    )

    frame, metadata = tushare_pcf.fetch_etf_creation_redemption_basket(
        "159326.SZ",
        "2025-03-31",
        "2025-04-01",
        pro=pro,
    )

    assert frame["Date"].tolist() == ["2025-03-31", "2025-04-01"]
    assert frame["AvailableDate"].tolist() == [
        "2025-04-01 09:30:00",
        "2025-04-02 09:30:00",
    ]
    assert [call["start_date"] for call in pro.basket_calls] == ["20250331", "20250401"]
    assert metadata["primary_key"] == ["Date", "ConstituentSymbol"]


def test_DFLS_33_C04_missing_session_rejected():
    missing = FakePro([_row("20250331")], ("20250331", "20250401", "20250402"))
    with pytest.raises(IncompleteDataError, match="missing SZSE trading sessions"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ",
            "2025-03-31",
            "2025-04-01",
            pro=missing,
        )


def test_DFLS_33_C02_duplicate_constituent_rejected() -> None:
    duplicate = FakePro([_row("20250303"), _row("20250303")], ("20250303", "20250304"))
    with pytest.raises(DataContractError, match="duplicate constituents"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ",
            "2025-03-03",
            "2025-03-03",
            pro=duplicate,
        )


def test_DFLS_33_C03_negative_quantity_rejected():
    invalid = FakePro([_row("20250303", qty=-1)], ("20250303", "20250304"))
    with pytest.raises(DataContractError, match="non-negative integers"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ",
            "2025-03-03",
            "2025-03-03",
            pro=invalid,
        )
