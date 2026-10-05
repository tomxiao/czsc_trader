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
        "trade_date": day, "ts_code": "159326.SZ", "con_code": code,
        "con_name": "成份股", "qty": 100, "sub_flag": "允许", "cpr": 10.0,
        "rdr": 0.0, "sub_cc": 0.0, "red_cc": 0.0, "exchange": "SH",
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
        return pd.DataFrame([
            row for row in self.rows
            if kwargs["start_date"] <= row["trade_date"] <= kwargs["end_date"]
        ])

    def trade_cal(self, **kwargs):
        return pd.DataFrame({"cal_date": list(self.open_dates),
                             "is_open": [1] * len(self.open_dates)})


def test_basket_is_registered_and_available_next_szse_session(flow_factory, publish_data, monkeypatch) -> None:
    pro = FakePro(
        [_row("20250303"), _row("20250303", "159900.SZ", qty=0,
                                      sub_flag="必须", exchange="SZ", sub_cc=120.0)],
        ("20250303", "20250304"),
    )
    monkeypatch.setattr(tushare_pcf, "get_tushare_pro", lambda _env: pro)
    facade = flow_factory()

    assert Dataset.ETF_CREATION_REDEMPTION_BASKET.value in facade.datasets
    result = publish_data(facade, DataRequest(
        Dataset.ETF_CREATION_REDEMPTION_BASKET, "159326.SZ",
        "2025-03-03", "2025-03-03", "2025-03-03", "daily",
    ))

    assert result.status is DataStatus.READY
    assert result.dataframe["AvailableDate"].unique().tolist() == ["2025-03-04 09:30:00"]
    assert result.dataframe.loc[
        result.dataframe["ConstituentSymbol"].eq("159900.SZ"), "Quantity"
    ].tolist() == [0]
    assert result.identity is not None
    assert result.identity.metadata["availability_time_field"] == "AvailableDate"
    assert result.identity.metadata["source_publication_timestamp_verified"] is False
    assert result.identity.metadata["historical_revision_history_verified"] is False
    assert result.identity.metadata["availability_basis"] == "CONSERVATIVE_NEXT_SESSION"
    assert result.identity.metadata["source_disclosure_schedule"].startswith("trade-date premarket")
    assert pro.basket_calls == [{
        "ts_code": "159326.SZ", "start_date": "20250303", "end_date": "20250303",
    }]


def test_basket_splits_months_and_rejects_missing_trading_sessions() -> None:
    pro = FakePro(
        [_row("20250331"), _row("20250401")],
        ("20250331", "20250401", "20250402"),
    )

    frame, metadata = tushare_pcf.fetch_etf_creation_redemption_basket(
        "159326.SZ", "2025-03-31", "2025-04-01", pro=pro,
    )

    assert frame["Date"].tolist() == ["2025-03-31", "2025-04-01"]
    assert frame["AvailableDate"].tolist() == [
        "2025-04-01 09:30:00", "2025-04-02 09:30:00",
    ]
    assert [call["start_date"] for call in pro.basket_calls] == ["20250331", "20250401"]
    assert metadata["primary_key"] == ["Date", "ConstituentSymbol"]

    missing = FakePro([_row("20250331")], ("20250331", "20250401", "20250402"))
    with pytest.raises(IncompleteDataError, match="missing SZSE trading sessions"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-31", "2025-04-01", pro=missing,
        )


@pytest.mark.parametrize("symbol", ["600089.SH", "159326.SH", "000400.SZ"])
def test_basket_rejects_non_szse_etf_symbols(symbol: str) -> None:
    with pytest.raises(DataContractError, match="six-digit"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            symbol, "2025-03-03", "2025-03-03", pro=object(),
        )


def test_basket_rejects_duplicate_member_and_invalid_quantity() -> None:
    duplicate = FakePro([_row("20250303"), _row("20250303")],
                        ("20250303", "20250304"))
    with pytest.raises(DataContractError, match="duplicate constituents"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-03", pro=duplicate,
        )

    invalid = FakePro([_row("20250303", qty=-1)], ("20250303", "20250304"))
    with pytest.raises(DataContractError, match="non-negative integers"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-03", pro=invalid,
        )


def test_basket_rejects_wrong_source_symbol_and_non_trading_date() -> None:
    wrong_symbol = FakePro([_row("20250303", ts_code="159327.SZ")],
                           ("20250303", "20250304"))
    with pytest.raises(DataContractError, match="another ETF symbol"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-03", pro=wrong_symbol,
        )

    non_trading = FakePro([_row("20250303"), _row("20250304")],
                          ("20250303", "20250305"))
    with pytest.raises(DataContractError, match="non-trading dates"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-04", pro=non_trading,
        )


def test_basket_rejects_missing_or_non_numeric_source_fields() -> None:
    missing_field = FakePro([_row("20250303")], ("20250303", "20250304"))
    missing_field.rows[0].pop("sub_cc")
    with pytest.raises(DataContractError, match="source fields are missing"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-03", pro=missing_field,
        )

    malformed = FakePro([_row("20250303", cpr="unknown")],
                        ("20250303", "20250304"))
    with pytest.raises(DataContractError, match="invalid numeric values"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-03", pro=malformed,
        )

    missing_identifier = FakePro([_row("20250303", sub_flag=None)],
                                 ("20250303", "20250304"))
    with pytest.raises(DataContractError, match="empty identifiers"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-03", pro=missing_identifier,
        )


def test_basket_row_limit_and_invalid_request_do_not_report_ready(monkeypatch) -> None:
    pro = FakePro([_row("20250303", f"{i:06d}.SZ") for i in range(3000)],
                  ("20250303", "20250304"))
    with pytest.raises(IncompleteDataError, match="vendor row limit"):
        tushare_pcf.fetch_etf_creation_redemption_basket(
            "159326.SZ", "2025-03-03", "2025-03-03", pro=pro,
        )

    monkeypatch.setattr(tushare_pcf, "get_tushare_pro", lambda _env: pro)
    with pytest.raises(ValueError):
        DataRequest(
            Dataset.ETF_CREATION_REDEMPTION_BASKET, "159326.SZ",
            "2025-03-03", "2025-03-03", None, "5m",
        )
    with pytest.raises(TypeError):
        DataRequest(
            Dataset.ETF_CREATION_REDEMPTION_BASKET, "159326.SZ",
            "2025-03-03", "2025-03-03", None, "daily", {"unknown": True},
        )


def test_facade_rejects_false_basket_availability_and_verification(flow_factory, publish_data) -> None:
    pro = FakePro([_row("20250303")], ("20250303", "20250304"))
    frame, metadata = tushare_pcf.fetch_etf_creation_redemption_basket(
        "159326.SZ", "2025-03-03", "2025-03-03", pro=pro,
    )
    supplied_frame, supplied_metadata = frame, metadata
    facade = flow_factory({
        Dataset.ETF_CREATION_REDEMPTION_BASKET.value: lambda request: (supplied_frame, supplied_metadata)
    })
    request = DataRequest(
        Dataset.ETF_CREATION_REDEMPTION_BASKET, "159326.SZ",
        "2025-03-03", "2025-03-03", None,
    )
    ready = publish_data(facade, request)
    assert ready.ready, ready.error
    for claim in ("same_day", "source_publication_timestamp_verified", "official_pcf_code_quantity_verified"):
        supplied_frame, supplied_metadata = frame.copy(deep=True), metadata.copy()
        if claim == "same_day":
            supplied_frame.loc[:, "AvailableDate"] = "2025-03-03 09:30:00"
        else:
            supplied_metadata[claim] = True
        result = publish_data(facade, request)
        assert result.status is DataStatus.FAILED, claim
        assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH", claim
    old = facade.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256


def _official_xml(quantity: int = 100, day: str = "20250303") -> bytes:
    return (
        "<PCFFile><SecurityID>159326</SecurityID><TradingDay>" + day +
        "</TradingDay><RecordNum>0</RecordNum><TotalRecordNum>1</TotalRecordNum>"
        "<Components><Component><UnderlyingSecurityID>600089"
        "</UnderlyingSecurityID><UnderlyingSecurityIDSource>101"
        "</UnderlyingSecurityIDSource><ComponentShare>" + str(quantity) +
        "</ComponentShare></Component></Components></PCFFile>"
    ).encode()


def test_optional_official_pcf_check_verifies_content_without_claiming_vintage(flow_factory, publish_data, monkeypatch) -> None:
    pro = FakePro([_row("20250303")], ("20250303", "20250304"))
    monkeypatch.setattr(tushare_pcf, "get_tushare_pro", lambda _env: pro)
    calls = []
    payload = _official_xml()

    def fake_post(path, data):
        calls.append((path, data))
        if path == "tradeList":
            return SimpleNamespace(json=lambda: {
                "status": 1, "data": {
                    "fileName": "pcf_159326_20250303.xml", "year": None,
                },
            })
        return SimpleNamespace(content=payload)

    monkeypatch.setattr(chinaamc_pcf, "_post", fake_post)
    flows = flow_factory()
    request = DataRequest(
        Dataset.ETF_CREATION_REDEMPTION_BASKET, "159326.SZ",
        "2025-03-03", "2025-03-03", None, "daily",
        PcfParameters(verify_official_pcf_components=True),
    )
    result = publish_data(flows, request)

    assert result.status is DataStatus.READY
    assert result.identity is not None
    metadata = result.identity.metadata
    assert metadata["official_pcf_code_quantity_verified"] is True
    assert metadata["official_pcf_component_count"] == 1
    assert metadata["official_pcf_publication_timestamp_verified"] is False
    assert metadata["official_pcf_historical_revisions_verified"] is False
    assert metadata["source_publication_timestamp_verified"] is False
    assert metadata["historical_revision_history_verified"] is False
    assert [path for path, _ in calls] == ["tradeList", "query/etfDownload"]
    assert calls[1][1]["fileName"] == "pcf_159326_20250303.xml"
    for defect, payload in (
        ("quantity mismatch", _official_xml(quantity=99)),
        ("date mismatch", _official_xml(day="20250304")),
        ("malformed XML", b"bad xml"),
    ):
        failed = publish_data(flows, request)
        assert failed.status is DataStatus.FAILED, defect
        assert failed.error is not None and failed.error.code == "DATA_CONTRACT_MISMATCH", defect
    old = flows.fetch(request, prepared=result.prepared)
    assert old.ready and old.identity.content_sha256 == result.identity.content_sha256


@pytest.mark.parametrize("option", [1, "true", None])
def test_official_pcf_check_requires_boolean_parameter(option) -> None:
    with pytest.raises(TypeError):
        PcfParameters(verify_official_pcf_components=option)


def test_official_pcf_check_rejects_multiday_request_before_source_call(flow_factory, publish_data, monkeypatch) -> None:
    monkeypatch.setattr(tushare_pcf, "get_tushare_pro", lambda _env: object())
    result = publish_data(flow_factory(), DataRequest(
        Dataset.ETF_CREATION_REDEMPTION_BASKET, "159326.SZ",
        "2025-03-03", "2025-03-04", None, "daily",
        PcfParameters(verify_official_pcf_components=True),
    ))
    assert result.status is DataStatus.FAILED
    assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH"


def test_official_pcf_check_rejects_wrong_file_identity(monkeypatch) -> None:
    basket = pd.DataFrame({
        "Date": ["2025-03-03"], "ConstituentSymbol": ["600089.SH"],
        "Quantity": [100],
    })
    monkeypatch.setattr(chinaamc_pcf, "_post", lambda _path, _data: SimpleNamespace(
        json=lambda: {"status": 1, "data": {"fileName": "pcf_159326_20250304.xml"}},
    ))
    with pytest.raises(DataContractError, match="file date differs"):
        chinaamc_pcf.verify_chinaamc_pcf_components("159326.SZ", "2025-03-03", basket)
