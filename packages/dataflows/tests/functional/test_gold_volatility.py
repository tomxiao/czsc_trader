"""GVZ publication and failure semantics through the public prepare/fetch contract."""

from pathlib import Path

import pandas as pd
import pytest
import requests

from dataflows import (
    Dataflows,
    DataRequest,
    DataSpace,
    DataStatus,
    Dataset,
    PreparePolicy,
    ProviderBinding,
    ProviderConfig,
)
from dataflows.contract import FRED_GVZ_AVAILABILITY_RULE


class Response:
    def __init__(self, code, observations, count=None):
        self.status_code = code
        self.payload = {
            "observations": observations,
            "count": len(observations) if count is None else count,
        }

    def json(self):
        return self.payload


def request():
    return DataRequest(
        Dataset.GOLD_VOLATILITY_DAILY, None, "2024-01-05", "2024-01-10", "2024-01-08"
    )


def observations():
    return [
        {"date": "2024-01-05", "realtime_start": "2024-01-04", "value": "15.5"},
        {"date": "2024-01-08", "realtime_start": "2024-01-08", "value": "."},
        {"date": "2024-01-08", "realtime_start": "2024-01-09", "value": "16.2"},
    ]


def test_gvz_first_release_preparation_and_offline_restoration(tmp_path, monkeypatch):
    monkeypatch.setenv("FRED_KEY", "test-key")
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["params"])
        return Response(200, observations())

    monkeypatch.setattr(requests, "get", get)
    args = {"base_dir": tmp_path, "space": DataSpace(Path("gvz")), "providers": ProviderConfig()}
    flow = Dataflows(**args)
    prepared = flow.prepare((request(),), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(request(), prepared=prepared.reference)
    assert result.ready
    assert result.dataframe.Close.tolist() == [15.5, 16.2]
    assert result.dataframe.InitialReleaseDate.tolist() == list(
        pd.to_datetime(["2024-01-04", "2024-01-09"])
    )
    assert result.dataframe.AvailableDate.tolist() == list(
        pd.to_datetime(["2024-01-06 16:00", "2024-01-10 16:00"])
    )
    assert result.identity.source == "FRED"
    assert result.identity.metadata["series_id"] == "GVZCLS"
    assert result.identity.metadata["original_source"] == "CBOE"
    assert result.identity.temporal_contract.available_at == FRED_GVZ_AVAILABILITY_RULE
    assert result.identity.metadata["historical_intraday_publication_verified"] is False
    assert result.identity.metadata["release_before_observation_dates"] == ["2024-01-05"]
    assert calls[0]["series_id"] == "GVZCLS" and calls[0]["output_type"] == 4

    def forbid(*args, **kwargs):
        raise AssertionError("pinned fetch/REUSE must be offline")

    monkeypatch.setattr(requests, "get", forbid)
    restored = Dataflows(**args)
    cached = restored.fetch(request(), prepared=prepared.reference)
    assert cached.identity.content_sha256 == result.identity.content_sha256
    assert restored.prepare((request(),), policy=PreparePolicy.REUSE).ready


@pytest.mark.parametrize(
    "code,count,expected",
    [
        (429, None, DataStatus.WAITING_SOURCE),
        (401, None, DataStatus.FAILED),
        (200, 20, DataStatus.INCOMPLETE),
        (200, 0, DataStatus.FAILED),
    ],
)
def test_gvz_provider_failure_never_publishes_data(
    flow_factory, monkeypatch, code, count, expected
):
    monkeypatch.setenv("FRED_KEY", "test-key")
    monkeypatch.setattr(requests, "get", lambda *a, **k: Response(code, observations(), count))
    prepared = flow_factory().prepare((request(),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is expected


@pytest.mark.parametrize("fault", ["nonfinite", "invalid_release_date", "duplicate"])
def test_gvz_rejects_invalid_first_release_records(flow_factory, monkeypatch, fault):
    monkeypatch.setenv("FRED_KEY", "test-key")
    rows = observations()
    if fault == "nonfinite":
        rows[0]["value"] = "Infinity"
    elif fault == "invalid_release_date":
        rows[0]["realtime_start"] = "invalid"
    else:
        rows.append(rows[0].copy())
    monkeypatch.setattr(requests, "get", lambda *a, **k: Response(200, rows))
    prepared = flow_factory().prepare((request(),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.items[0].status is DataStatus.FAILED


def test_gvz_custom_binding_cannot_publish_early_availability(tmp_path):
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-05", "2024-01-08"]),
            "InitialReleaseDate": pd.to_datetime(["2024-01-05", "2024-01-08"]),
            "AvailableDate": pd.to_datetime(["2024-01-05", "2024-01-08"]),
            "Close": [15.5, 16.2],
        }
    )
    metadata = {
        "vendor": "FRED",
        "original_source": "CBOE",
        "series_id": "GVZCLS",
        "vintage_mode": "INITIAL_RELEASE_ONLY",
        "fred_output_type": 4,
        "source_time_field": "Date",
        "availability_time_field": "AvailableDate",
        "source_calendar": "US_MARKET",
        "availability_timezone": "Asia/Shanghai",
        "available_at": FRED_GVZ_AVAILABILITY_RULE,
        "historical_intraday_publication_verified": False,
    }
    flow = Dataflows(
        base_dir=tmp_path,
        space=DataSpace(Path("early")),
        providers=ProviderConfig(
            bindings={
                Dataset.GOLD_VOLATILITY_DAILY: ProviderBinding(
                    "fixture", "v1", lambda _: (frame, metadata)
                )
            }
        ),
    )
    prepared = flow.prepare((request(),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.items[0].status is DataStatus.FAILED


def test_gvz_splits_vintage_window_without_changing_series(tmp_path, monkeypatch):
    monkeypatch.setenv("FRED_KEY", "test-key")
    calls = []

    def get(url, **kwargs):
        p = kwargs["params"]
        calls.append(p)
        day = "2020-01-02" if p["realtime_start"] == "2020-01-01" else "2026-09-30"
        return Response(200, [{"date": day, "realtime_start": day, "value": "20.0"}])

    monkeypatch.setattr(requests, "get", get)
    flow = Dataflows(base_dir=tmp_path, space=DataSpace(Path("long")), providers=ProviderConfig())
    req = DataRequest(Dataset.GOLD_VOLATILITY_DAILY, None, "2020-01-01", "2026-09-30", "2026-09-30")
    prepared = flow.prepare((req,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    assert [(p["realtime_start"], p["realtime_end"]) for p in calls] == [
        ("2020-01-01", "2025-12-31"),
        ("2026-01-01", "2026-09-30"),
    ]
    assert all(p["series_id"] == "GVZCLS" and p["output_type"] == 4 for p in calls)
