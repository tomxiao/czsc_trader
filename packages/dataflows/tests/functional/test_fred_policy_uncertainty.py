from __future__ import annotations

from typing import Any


from dataflows import DataRequest, DataStatus, Dataset
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


def test_DFLS_30_C01_fred_policy_uncertainty_splits_long_vintage_history(monkeypatch) -> None:
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








def test_DFLS_30_C02_fred_policy_uncertainty_rejects_truncated_response(flow_factory, publish_data, monkeypatch) -> None:
    monkeypatch.setenv("FRED_KEY", "test-key")
    payload = _payload()
    payload["count"] = 4
    flow = flow_factory({
        Dataset.US_POLICY_UNCERTAINTY_DAILY.value: lambda _: fetch_us_policy_uncertainty_daily(
            "2024-01-01",
            "2024-01-03",
            http_get=lambda *args, **kwargs: FakeResponse(200, payload),
        )
    })

    result = publish_data(flow, DataRequest(
        Dataset.US_POLICY_UNCERTAINTY_DAILY,
        None,
        "2024-01-01",
        "2024-01-03",
        None,
    ))

    assert result.status is DataStatus.INCOMPLETE
    assert result.error is not None
    assert result.error.code == "INCOMPLETE_DATA"
