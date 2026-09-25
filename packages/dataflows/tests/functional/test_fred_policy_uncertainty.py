from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.fred_policy_uncertainty import fetch_us_policy_uncertainty_daily


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _payload() -> dict[str, Any]:
    observations = [
        {"date": "2024-01-01", "realtime_start": "2024-01-02", "value": "110.5"},
        {"date": "2024-01-02", "realtime_start": "2024-01-02", "value": "."},
        {"date": "2024-01-03", "realtime_start": "2024-01-03", "value": "121.0"},
    ]
    return {"count": len(observations), "observations": observations}


def test_fred_policy_uncertainty_is_fixed_to_initial_release_history(monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        captured.update(url=url, **kwargs)
        return FakeResponse(200, _payload())

    frame, metadata = fetch_us_policy_uncertainty_daily(
        "2024-01-01", "2024-01-03", http_get=fake_get
    )

    assert captured["params"]["series_id"] == "USEPUINDXD"
    assert captured["params"]["output_type"] == 4
    assert captured["params"]["realtime_start"] == "2024-01-01"
    assert captured["params"]["realtime_end"] == "2024-01-03"
    assert "test-key" not in captured["url"]
    assert frame.to_dict("list") == {
        "Date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")],
        "AvailableDate": [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")],
        "PolicyUncertaintyIndex": [110.5, 121.0],
    }
    assert metadata["vintage_mode"] == "INITIAL_RELEASE_ONLY"


def test_fred_policy_uncertainty_splits_long_vintage_history(monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")
    observed_windows: list[tuple[str, str]] = []

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        params = kwargs["params"]
        observed_windows.append((params["realtime_start"], params["realtime_end"]))
        day = params["realtime_start"]
        return FakeResponse(
            200,
            {
                "count": 1,
                "observations": [{"date": day, "realtime_start": day, "value": "100.0"}],
            },
        )

    frame, _ = fetch_us_policy_uncertainty_daily(
        "2014-03-28", "2024-12-31", http_get=fake_get
    )

    assert observed_windows == [
        ("2014-03-28", "2019-12-31"),
        ("2020-01-01", "2024-12-31"),
    ]
    assert len(frame) == 2


def test_fred_policy_uncertainty_facade_publishes_typed_identity(monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")
    flow = Dataflows({
        Dataset.US_POLICY_UNCERTAINTY_DAILY.value: lambda _: fetch_us_policy_uncertainty_daily(
            "2024-01-01",
            "2024-01-03",
            http_get=lambda *args, **kwargs: FakeResponse(200, _payload()),
        )
    })

    result = flow.fetch(DataRequest(
        Dataset.US_POLICY_UNCERTAINTY_DAILY,
        None,
        "2024-01-01",
        "2024-01-03",
        "2024-01-03",
    ))

    assert result.status is DataStatus.READY
    assert result.identity is not None
    assert result.identity.source == "FRED"
    assert result.identity.metadata["series_id"] == "USEPUINDXD"
    assert result.identity.temporal_contract.availability_time_field == "AvailableDate"


def test_fred_policy_uncertainty_rejects_symbol_and_wrong_lineage(monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")
    symbol_result = Dataflows().fetch(DataRequest(
        Dataset.US_POLICY_UNCERTAINTY_DAILY,
        "OTHER",
        "2024-01-01",
        "2024-01-03",
        None,
    ))
    assert symbol_result.status is DataStatus.FAILED
    assert symbol_result.error is not None
    assert symbol_result.error.code == "DATA_CONTRACT_MISMATCH"

    frame = pd.DataFrame({
        "Date": [pd.Timestamp("2024-01-01")],
        "AvailableDate": [pd.Timestamp("2024-01-02")],
        "PolicyUncertaintyIndex": [100.0],
    })
    wrong_lineage = Dataflows({
        Dataset.US_POLICY_UNCERTAINTY_DAILY.value: lambda _: (
            frame,
            {
                "vendor": "FRED",
                "series_id": "OTHER",
                "vintage_mode": "INITIAL_RELEASE_ONLY",
                "fred_output_type": 4,
                "source_time_field": "Date",
                "availability_time_field": "AvailableDate",
                "source_calendar": "FRED_CALENDAR_DAY",
                "available_at": "initial release date reported by ALFRED",
            },
        )
    }).fetch(DataRequest(
        Dataset.US_POLICY_UNCERTAINTY_DAILY,
        None,
        "2024-01-01",
        "2024-01-03",
        None,
    ))
    assert wrong_lineage.status is DataStatus.FAILED
    assert wrong_lineage.error is not None
    assert wrong_lineage.error.code == "DATA_CONTRACT_MISMATCH"


def test_fred_policy_uncertainty_maps_source_failure_without_fake_success(monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")

    def unavailable(*args: Any, **kwargs: Any) -> FakeResponse:
        raise requests.ConnectionError("offline")

    flow = Dataflows({
        Dataset.US_POLICY_UNCERTAINTY_DAILY.value: lambda _: fetch_us_policy_uncertainty_daily(
            "2024-01-01", "2024-01-03", http_get=unavailable
        )
    })
    result = flow.fetch(DataRequest(
        Dataset.US_POLICY_UNCERTAINTY_DAILY,
        None,
        "2024-01-01",
        "2024-01-03",
        None,
    ))

    assert result.status is DataStatus.WAITING_SOURCE
    assert result.dataframe.empty
    assert result.identity is None
    assert result.error is not None and result.error.retryable


def test_fred_policy_uncertainty_rejects_truncated_response(monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")
    payload = _payload()
    payload["count"] = 4
    flow = Dataflows({
        Dataset.US_POLICY_UNCERTAINTY_DAILY.value: lambda _: fetch_us_policy_uncertainty_daily(
            "2024-01-01",
            "2024-01-03",
            http_get=lambda *args, **kwargs: FakeResponse(200, payload),
        )
    })

    result = flow.fetch(DataRequest(
        Dataset.US_POLICY_UNCERTAINTY_DAILY,
        None,
        "2024-01-01",
        "2024-01-03",
        None,
    ))

    assert result.status is DataStatus.INCOMPLETE
    assert result.error is not None
    assert result.error.code == "INCOMPLETE_DATA"


def test_fred_policy_uncertainty_blocks_missing_history_start(monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")
    payload = {
        "count": 1,
        "observations": [
            {"date": "2024-01-10", "realtime_start": "2024-01-10", "value": "100.0"}
        ],
    }
    flow = Dataflows({
        Dataset.US_POLICY_UNCERTAINTY_DAILY.value: lambda _: fetch_us_policy_uncertainty_daily(
            "2024-01-01",
            "2024-01-10",
            http_get=lambda *args, **kwargs: FakeResponse(200, payload),
        )
    })

    result = flow.fetch(DataRequest(
        Dataset.US_POLICY_UNCERTAINTY_DAILY,
        None,
        "2024-01-01",
        "2024-01-10",
        None,
    ))

    assert result.status is DataStatus.INCOMPLETE
    assert result.error is not None
    assert result.error.code == "INCOMPLETE_DATA"


def test_default_registry_exposes_fred_policy_uncertainty() -> None:
    assert Dataset.US_POLICY_UNCERTAINTY_DAILY.value in Dataflows().datasets
