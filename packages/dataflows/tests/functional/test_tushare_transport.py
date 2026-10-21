"""HTTP failures remain distinguishable from legitimate empty source results."""
import json

import pandas as pd
import pytest
import requests

from dataflows import DataContractError, DataRequest, DataStatus, Dataset, PreparePolicy, SourceNotReadyError, SourceRequestError
from dataflows import tushare_common


def response(status=200, payload=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload if payload is not None else {
        "code": 0, "data": {"fields": ["ts_code", "trade_date"], "items": [["600722.SH", "20261015"]]},
    }).encode()
    return result


_HTTP_FAILURES = [
    (502, DataStatus.WAITING_SOURCE, "SOURCE_NOT_READY", True),
    (503, DataStatus.WAITING_SOURCE, "SOURCE_NOT_READY", True),
    (504, DataStatus.WAITING_SOURCE, "SOURCE_NOT_READY", True),
    (429, DataStatus.WAITING_SOURCE, "SOURCE_NOT_READY", True),
    (401, DataStatus.FAILED, "SOURCE_REQUEST_FAILED", False),
    (403, DataStatus.FAILED, "SOURCE_REQUEST_FAILED", False),
]


# One native route carries the complete HTTP-code matrix. Every other native
# route still exercises server failure, throttling and authorization failure;
# 502/504 and 403 reuse the same transport branch as 503 and 401 respectively.
# This preserves route-specific exception propagation without a Cartesian copy
# of the common transport classifier. Every retained input remains a pytest node.
@pytest.mark.parametrize("dataset,http_status,expected_status,code,retryable", [
    (dataset, *failure)
    for dataset in (Dataset.STOCK_UNADJUSTED_DAILY, Dataset.STOCK_OHLCV,
                    Dataset.SECURITY_PRICE_LIMITS, Dataset.SECURITY_TRADING_STATUS)
    for failure in _HTTP_FAILURES
    if dataset is Dataset.STOCK_UNADJUSTED_DAILY or failure[0] in (503, 429, 401)
])
def test_http_failures_cross_native_preparation_without_empty_rows_or_retries(
    flow_factory, monkeypatch, http_status, expected_status, code, retryable, dataset,
):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response(http_status)

    monkeypatch.setattr(tushare_common.requests, "post", post)
    request = DataRequest(dataset, "600722.SH", "2026-10-15", "2026-10-15", "2026-10-15")
    prepared = flow_factory().prepare((request,), policy=PreparePolicy.REUSE)
    assert not prepared.ready and prepared.reference is None
    item = prepared.items[0]
    assert item.status is expected_status
    assert (item.error.code, item.error.retryable) == (code, retryable)
    assert item.error.context["http_status"] == http_status
    assert item.error.context["api"] == ("stk_limit" if dataset is Dataset.SECURITY_PRICE_LIMITS else "daily")
    assert item.error.context["vendor"] == "tushare"
    assert "private-test-token" not in str(item.error)
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [requests.Timeout, requests.ConnectionError])
def test_transport_failure_is_typed_and_does_not_echo_exception_credentials(monkeypatch, failure):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")

    def fail(*args, **kwargs):
        raise failure("private-test-token in vendor exception")

    monkeypatch.setattr(tushare_common.requests, "post", fail)
    with pytest.raises(SourceNotReadyError) as raised:
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")
    assert raised.value.context == {"vendor": "tushare", "api": "daily", "exception_type": failure.__name__}
    assert "private-test-token" not in str(raised.value)


def test_successful_empty_suspension_response_preserves_columns(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")
    fields = ["ts_code", "trade_date", "suspend_type", "suspend_timing"]
    monkeypatch.setattr(tushare_common.requests, "post", lambda *args, **kwargs: response(
        payload={"code": 0, "data": {"fields": fields, "items": []}}))
    frame = tushare_common.get_tushare_pro().suspend_d(ts_code="600722.SH")
    assert frame.empty and frame.columns.tolist() == fields


def test_successful_query_keeps_sdk_dispatch_and_request_contract(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")
    seen = []

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return response()

    monkeypatch.setattr(tushare_common.requests, "post", post)
    frame = tushare_common.get_tushare_pro().daily(ts_code="600722.SH", fields="ts_code,trade_date")
    pd.testing.assert_frame_equal(frame, pd.DataFrame({"ts_code": ["600722.SH"], "trade_date": ["20261015"]}))
    url, request = seen[0]
    assert url.endswith("/daily")
    assert request["timeout"] == 30
    assert request["json"] == {"api_name": "daily", "token": "private-test-token",
                               "params": {"ts_code": "600722.SH", "ts_type_name": url.rsplit("/", 1)[0]},
                               "fields": "ts_code,trade_date"}


def test_api_rejection_keeps_business_code_without_echoing_vendor_message(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")
    monkeypatch.setattr(tushare_common.requests, "post", lambda *args, **kwargs: response(
        payload={"code": 2002, "msg": "private-test-token not authorized", "data": None}))
    with pytest.raises(SourceRequestError) as raised:
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")
    assert raised.value.context["vendor_code"] == 2002
    assert raised.value.context["http_status"] == 200
    assert "private-test-token" not in str(raised.value)


@pytest.mark.parametrize("payload", [
    {}, {"code": False, "data": {}}, {"code": 0, "data": None},
    {"code": 0, "data": {"fields": ["x", "x"], "items": []}},
    {"code": 0, "data": {"fields": ["x"], "items": [[1, 2]]}},
])
def test_invalid_response_schema_is_not_published_as_empty(monkeypatch, payload):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")
    monkeypatch.setattr(tushare_common.requests, "post", lambda *args, **kwargs: response(payload=payload))
    with pytest.raises(DataContractError):
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")


def test_non_json_response_is_a_contract_failure(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")
    invalid = response()
    invalid._content = b"<html>private-test-token</html>"
    monkeypatch.setattr(tushare_common.requests, "post", lambda *args, **kwargs: invalid)
    with pytest.raises(DataContractError, match="not JSON") as raised:
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")
    assert "private-test-token" not in str(raised.value)
