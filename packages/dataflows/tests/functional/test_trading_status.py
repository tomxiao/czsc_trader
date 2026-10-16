"""Public preparation distinguishes proven suspensions from missing observations."""
from pathlib import Path

import pandas as pd
import pytest

from dataflows import DataRequest, Dataflows, DataSpace, Dataset, PreparePolicy, ProviderConfig


class SessionSource:
    def __init__(self, missing=False, proof=True, intraday=False):
        self.missing, self.proof, self.intraday = missing, proof, intraday

    def stock_basic(self, **kwargs):
        return pd.DataFrame({"ts_code": [kwargs["ts_code"]], "list_date": ["20000101"]})

    fund_basic = stock_basic

    def trade_cal(self, **kwargs):
        dates = pd.date_range(kwargs["start_date"], kwargs["end_date"])
        return pd.DataFrame({"cal_date": dates.strftime("%Y%m%d"), "is_open": (dates.weekday < 5).astype(int)})

    def daily(self, **kwargs):
        dates = list(pd.bdate_range("2026-09-14", "2026-09-18").strftime("%Y%m%d"))
        if self.missing:
            dates.remove("20260916")
        return pd.DataFrame({"ts_code": kwargs["ts_code"], "trade_date": dates, "vol": 100})

    fund_daily = daily

    def suspend_d(self, **kwargs):
        rows = [{"ts_code": kwargs["ts_code"], "trade_date": "20260916", "suspend_type": "S",
                 "suspend_timing": "09:30-10:00" if self.intraday else None}] if self.proof and (self.missing or self.intraday) else []
        return pd.DataFrame(rows, columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"])


@pytest.mark.parametrize("symbol,missing,proof,intraday,ready", [
    ("600722.SH", False, True, False, True),
    ("510500.SH", False, True, False, False),
    ("600722.SH", True, True, False, True),
    ("600722.SH", True, False, False, False),
    ("600722.SH", True, True, True, False),
    ("600722.SH", False, True, True, False),
    ("510500.SH", True, True, False, False),
])
def test_native_status_preparation_requires_explicit_suspension_evidence(
    tmp_path, monkeypatch, symbol, missing, proof, intraday, ready,
):
    source = SessionSource(missing, proof, intraday)
    monkeypatch.setattr("dataflows.tushare_common.get_tushare_pro", lambda _: source)
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path("data")), providers=ProviderConfig())
    request = DataRequest(Dataset.SECURITY_TRADING_STATUS, symbol, "2026-09-14", "2026-09-18", "2026-09-18")
    prepared = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert prepared.ready is ready
    if ready:
        fetched = flows.fetch(request, prepared=prepared.reference)
        assert fetched.ready and len(fetched.dataframe) == 5
        assert fetched.dataframe.Status.tolist() == (["TRADING", "TRADING", "SUSPENDED", "TRADING", "TRADING"]
                                                     if missing else ["TRADING"] * 5)
        # A pinned read must work after supplier access becomes unavailable.
        monkeypatch.setattr(source, "daily", lambda **_: pytest.fail("supplier called"))
        assert flows.fetch(request, prepared=prepared.reference).ready
    else:
        assert prepared.reference is None and prepared.items[0].error is not None
