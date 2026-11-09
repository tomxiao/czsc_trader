"""DFLS-12/13/14: classify transport once, then verify each public route."""
import json
import pandas as pd
import pytest
import requests
from dataflows import (DataContractError, DataRequest, DataStatus, Dataset, PreparePolicy,
                       SourceNotReadyError, SourceRequestError)
from dataflows import tushare_common


def response(status=200, payload=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload if payload is not None else {
        "code": 0, "data": {"fields": ["ts_code", "trade_date"],
                            "items": [["600722.SH", "20261015"]]},
    }).encode()
    return result


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-test-token")
    calls = []
    def install(result):
        def post(url, **kwargs):
            calls.append((url, kwargs))
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(tushare_common.requests, "post", post)
        return calls
    return install


@pytest.mark.parametrize("status,error_type,code,retryable", [
    (503, SourceNotReadyError, "SOURCE_NOT_READY", True),
    (429, SourceNotReadyError, "SOURCE_NOT_READY", True),
    (401, SourceRequestError, "SOURCE_REQUEST_FAILED", False),
], ids=['DFLS-12-C01', 'DFLS-12-C02', 'DFLS-12-C03'])
def test_http_classification_has_one_request_and_no_secret(transport,status,error_type,code,retryable):
    calls = transport(response(status))
    with pytest.raises(error_type) as caught:
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert caught.value.context == {"vendor": "tushare", "api": "daily", "http_status": status}
    assert "private-test-token" not in str(caught.value)
    assert len(calls) == 1


def test_DFLS_12_C04_timeout_is_typed_and_redacted(transport):
    calls = transport(requests.Timeout("private-test-token"))
    with pytest.raises(SourceNotReadyError) as caught:
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")
    assert caught.value.context == {"vendor": "tushare", "api": "daily", "exception_type": "Timeout"}
    assert "private-test-token" not in str(caught.value)
    assert len(calls) == 1


def test_DFLS_12_C05_business_rejection_preserves_code_not_vendor_message(transport):
    calls = transport(response(payload={"code":2002,"msg":"private-test-token unauthorized","data":None}))
    with pytest.raises(SourceRequestError) as caught:
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")
    assert caught.value.context["vendor_code"] == 2002
    assert caught.value.context["http_status"] == 200
    assert not caught.value.retryable and "private-test-token" not in str(caught.value)
    assert len(calls) == 1


def test_DFLS_12_C06_non_json_body_never_leaks_credentials(transport):
    result = response()
    result._content = b"<html>private-test-token</html>"
    transport(result)
    with pytest.raises(DataContractError, match="not JSON") as caught:
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")
    assert "private-test-token" not in str(caught.value)


def test_DFLS_13_C01_query_keeps_dispatch_fields_timeout_and_rows(transport):
    calls = transport(response())
    frame = tushare_common.get_tushare_pro().daily(ts_code="600722.SH", fields="ts_code,trade_date")
    pd.testing.assert_frame_equal(frame,pd.DataFrame({"ts_code":["600722.SH"],"trade_date":["20261015"]}))
    url, sent = calls[0]
    assert len(calls) == 1 and url.endswith("/daily") and sent["timeout"] == 30
    assert sent["json"] == {"api_name":"daily","token":"private-test-token",
        "params":{"ts_code":"600722.SH","ts_type_name":url.rsplit("/",1)[0]},"fields":"ts_code,trade_date"}


def test_DFLS_13_C02_legitimate_empty_suspension_keeps_schema(transport):
    fields = ["ts_code","trade_date","suspend_type","suspend_timing"]
    transport(response(payload={"code":0,"data":{"fields":fields,"items":[]}}))
    frame = tushare_common.get_tushare_pro().suspend_d(ts_code="600722.SH")
    assert frame.empty and frame.columns.tolist() == fields


@pytest.mark.parametrize("payload", [
    {"code":0,"data":{"fields":["x","x"],"items":[]}},
    {"code":0,"data":{"fields":["x"],"items":[[1,2]]}},
    {"code":False,"data":{}},
], ids=['DFLS-13-C03', 'DFLS-13-C04', 'DFLS-13-C05'])
def test_schema_is_not_misreported_as_empty(transport,payload):
    transport(response(payload=payload))
    with pytest.raises(DataContractError):
        tushare_common.get_tushare_pro().daily(ts_code="600722.SH")


@pytest.mark.parametrize("dataset,http_status,status,code,retryable,api", [
    (Dataset.STOCK_UNADJUSTED_DAILY,503,DataStatus.WAITING_SOURCE,"SOURCE_NOT_READY",True,"daily"),
    (Dataset.STOCK_OHLCV,401,DataStatus.FAILED,"SOURCE_REQUEST_FAILED",False,"daily"),
    (Dataset.SECURITY_PRICE_LIMITS,429,DataStatus.WAITING_SOURCE,"SOURCE_NOT_READY",True,"stk_limit"),
    (Dataset.SECURITY_TRADING_STATUS,503,DataStatus.WAITING_SOURCE,"SOURCE_NOT_READY",True,"daily"),
], ids=['DFLS-14-C01', 'DFLS-14-C02', 'DFLS-14-C03', 'DFLS-14-C04'])
def test_native_route_public_failure_has_no_published_identity(flow_factory,transport,dataset,http_status,status,code,retryable,api):
    calls = transport(response(http_status))
    request = DataRequest(dataset,"600722.SH","2026-10-15","2026-10-15","2026-10-15")
    result = flow_factory().prepare((request,),policy=PreparePolicy.REUSE)
    assert not result.ready and result.reference is None
    item, = result.items
    assert item.status is status and item.identity is None
    assert (item.error.code,item.error.retryable) == (code,retryable)
    assert item.error.context == {
        "dataset": str(request.dataset), "symbol": request.symbol,
        "start": request.start, "end": request.end,
        "vendor":"tushare", "api":api, "http_status":http_status,
    }
    assert "private-test-token" not in str(item.error)
    assert len(calls) == 1
