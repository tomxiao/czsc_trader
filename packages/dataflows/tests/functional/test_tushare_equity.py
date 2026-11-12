"""Exercise real CN normalization through mocked provider responses and pinned assets."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from dataflows import (AssetClass, BarFrequency, Dataflows, DataSpace, EquityDataRequest,
                       EquityProduct, EquityQuery, InstrumentId, MarketId, PreparePolicy,
                       PriceAdjustment, ProviderConfig, SourceRef, tushare_equity_observation_bindings)
from dataflows import tushare_equity, tushare_etf, tushare_stock
from dataflows.equity_data import sessions_from_metadata
from dataflows.errors import DataContractError


class Pro:
    defect = None

    def stock_basic(self, *, ts_code, fields):
        return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20000101"]})

    fund_basic = stock_basic

    def trade_cal(self, *, exchange, start_date, end_date):
        assert exchange in {"SSE", "SZSE"}
        days = pd.date_range(start_date, end_date)
        frame = pd.DataFrame({"cal_date": days.strftime("%Y%m%d"),
                              "is_open": (days.dayofweek < 5).astype(int)})
        return frame.iloc[:-1] if self.defect == "calendar_gap" else frame

    def daily(self, **kwargs):
        return pd.DataFrame({"trade_date": ["20260928"], "open": [4.], "high": [4.],
                             "low": [4.], "close": [4.], "vol": [8.], "amount": [3.2]})

    fund_daily = daily

    def stk_factor_pro(self, *, ts_code, start_date, end_date, fields):
        return pd.DataFrame({"ts_code": [ts_code], "trade_date": ["20260928"],
            "open_hfq": [8.], "high_hfq": [8.], "low_hfq": [8.],
            "close_hfq": [8.], "vol": [8.], "amount": [3.2]})

    def stk_mins(self, **kwargs):
        assert kwargs["freq"] == "30min"
        stamps = pd.date_range("2026-09-28 10:00", "2026-09-28 11:30", freq="30min").append(
            pd.date_range("2026-09-28 13:30", "2026-09-28 15:00", freq="30min"))
        return pd.DataFrame({"trade_time": stamps, "open": 4., "high": 4., "low": 4.,
                             "close": 4., "vol": 100., "amount": 400.})

    etf_mins = stk_mins

    def adj_factor(self, **kwargs):
        return pd.DataFrame({"trade_date": ["20260928"], "adj_factor": [2.]})

    fund_adj = adj_factor


def setup(monkeypatch, tmp_path, asset_class, frequency, *, space=None):
    client = Pro()
    for module in (tushare_stock, tushare_etf, tushare_equity):
        monkeypatch.setattr(module, "get_tushare_pro", lambda _: client)
    source = SourceRef("tushare", "cn-hfq-v1")
    symbol = "600406.SH" if asset_class is AssetClass.STOCK else "159915.SZ"
    instrument = InstrumentId(MarketId.CN, asset_class, symbol)
    requests = tuple(EquityDataRequest(instrument, source, EquityQuery(
        product, date(2026, 9, 26), date(2026, 9, 28), frequency,
        PriceAdjustment.BACKWARD if product is EquityProduct.BARS else PriceAdjustment.NONE))
        for product in (EquityProduct.BARS, EquityProduct.SESSIONS))
    bindings = tushare_equity_observation_bindings(source=source)
    # Adapter validation needs no database. Only the explicit publication cases
    # below create a space; schema creation/reopen is owned by test_data_space.
    flows = None if space is None else Dataflows(base_dir=tmp_path, space=space,
                     providers=ProviderConfig(bindings={}, equity_bindings=bindings))
    return client, requests, bindings, flows


@pytest.mark.parametrize("asset_class,frequency", [
    (AssetClass.STOCK, BarFrequency.DAILY),
    (AssetClass.ETF, BarFrequency.DAILY),
    (AssetClass.ETF, BarFrequency.M30),
], ids=['DFLS-15-C01', 'DFLS-15-C02', 'DFLS-15-C03'])
def test_cn_hfq_prepare_reload_preserves_prices_units_calendar_and_availability(
        monkeypatch, tmp_path, empty_space_factory, asset_class, frequency):
    client, requests, bindings, flows = setup(monkeypatch, tmp_path, asset_class, frequency,
        space=empty_space_factory("assets"))
    prepared = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert prepared.ready, [i.error for i in prepared.items]
    fetched = flows.fetch(requests[0], prepared=prepared.reference)
    assert fetched.ready, fetched.error
    frame, metadata = fetched.dataframe, fetched.identity.metadata
    assert frame.Close.eq(8.).all()
    provider_adjusted = asset_class is AssetClass.STOCK and frequency is BarFrequency.DAILY
    assert frame.Volume.sum() == (800. if provider_adjusted else 400.)
    assert frame.Amount.sum() == 3200.
    sessions = sessions_from_metadata(metadata)
    assert len(sessions) == 1 and len(sessions[0].segments) == 2
    assert metadata["adjustment"] == "hfq"
    assert metadata['acquisition_method'] == ('PROVIDER_ADJUSTED' if provider_adjusted else 'DFLS_ADJUSTED')
    if provider_adjusted:
        assert metadata['price_source_api'] == 'tushare.stk_factor_pro'
        assert metadata['source_response_sha256']
        assert frame.AvailableDate.dt.tz_convert('Asia/Shanghai').dt.hour.eq(20).all()
    else:
        assert metadata["adjustment_factor_source"] == ("adj_factor" if asset_class is AssetClass.STOCK else "fund_adj")
        assert metadata["adjustment_factor_revision_history_verified"] is False
        assert metadata['raw_input_sha256'] and metadata['adjustment_algorithm']
    if not provider_adjusted and (frequency is BarFrequency.DAILY or asset_class is AssetClass.ETF):
        assert frame.AvailableDate.dt.tz_convert("Asia/Shanghai").dt.hour.eq(17).all()
    elif not provider_adjusted:
        assert frame.AvailableDate.equals(frame.Date)
        assert frame.Date.dt.tz_convert("Asia/Shanghai").dt.strftime("%H:%M").tolist() == [
            "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]
    calendar = flows.fetch(requests[1], prepared=prepared.reference)
    assert calendar.ready and calendar.dataframe.SessionDate.tolist() == ["2026-09-28"]
    assert sessions_from_metadata(calendar.identity.metadata) == sessions
    # The persisted reference is self-contained and does not reconnect to Tushare.
    client.defect = "calendar_gap"
    offline = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig(bindings={}))
    reloaded = offline.fetch(requests[0], prepared=prepared.reference)
    assert reloaded.ready and reloaded.identity == fetched.identity
    pd.testing.assert_frame_equal(reloaded.dataframe, frame)








@pytest.mark.parametrize('asset_class,frequency', [
    (AssetClass.STOCK, BarFrequency.DAILY),
    (AssetClass.ETF, BarFrequency.M30),
], ids=['DFLS-15-C04', 'DFLS-15-C07'])
def test_cn_explicit_raw_binding_preserves_unadjusted_prices(monkeypatch, tmp_path, asset_class, frequency):
    _, requests, _, _ = setup(monkeypatch,tmp_path,asset_class,frequency)
    p=requests[0].parameters
    req=EquityDataRequest(p.instrument,p.source,EquityQuery(EquityProduct.BARS,
        p.query.start,p.query.end,frequency,PriceAdjustment.NONE))
    bindings=tushare_equity.tushare_equity_bindings(source=p.source)
    frame,metadata=bindings[req.parameters.provider_key].fetch(req)
    assert frame.Close.eq(4.).all()
    assert frame.Volume.sum()==800.
    assert metadata['adjustment']=='none'
    assert metadata['acquisition_method']=='PROVIDER_RAW'
    assert metadata['publication_time_verified'] is False


@pytest.mark.parametrize('defect', [
    'permission',
], ids=['DFLS-15-C05'])
def test_provider_adjusted_failure_never_switches_to_computed_method(monkeypatch, tmp_path, defect):
    client, requests, bindings, _ = setup(monkeypatch, tmp_path, AssetClass.STOCK, BarFrequency.DAILY)
    original = client.stk_factor_pro

    def response(**kwargs):
        if defect == 'permission':
            raise RuntimeError('provider permission denied')
        frame = original(**kwargs)
        if defect == 'missing_fields':
            return frame.drop(columns=['close_hfq'])
        if defect == 'wrong_instrument':
            frame['ts_code'] = '000001.SZ'
        return pd.concat([frame, frame]) if defect == 'duplicate' else frame

    def forbidden(*args, **kwargs):
        raise AssertionError('a supplier failure must not change the acquisition method')

    monkeypatch.setattr(client, 'stk_factor_pro', response)
    monkeypatch.setattr(tushare_equity, 'fetch_stock_ohlcv', forbidden)
    req = requests[0]
    with pytest.raises((RuntimeError, DataContractError)):
        bindings[req.parameters.provider_key].fetch(req)



@pytest.mark.parametrize('asset_class', [AssetClass.STOCK, AssetClass.ETF])
@pytest.mark.parametrize('adjustment', [PriceAdjustment.NONE, PriceAdjustment.BACKWARD])
def test_partial_cn_bars_do_not_require_the_unfinished_daily_bar(monkeypatch, tmp_path, asset_class, adjustment):
    from dataclasses import replace
    from datetime import datetime
    from zoneinfo import ZoneInfo

    client, requests, _, _ = setup(monkeypatch, tmp_path, asset_class, BarFrequency.M30)
    def unfinished(**kwargs):
        raise AssertionError('current daily bar is not yet available')
    monkeypatch.setattr(client, 'daily', unfinished)
    monkeypatch.setattr(client, 'fund_daily', unfinished)
    p = requests[0].parameters
    cutoff = datetime(2026, 9, 28, 11, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
    req = EquityDataRequest(p.instrument, p.source,
        replace(p.query, completed_through=cutoff, adjustment=adjustment))
    bindings = tushare_equity.tushare_equity_bindings(source=p.source)
    frame, metadata = bindings[p.provider_key].fetch(req)
    assert len(frame) == 4 and frame.Date.iloc[-1] == cutoff
    assert metadata['completed_through'] == cutoff.astimezone(ZoneInfo('UTC')).isoformat()
    assert frame.Close.eq(4. if adjustment is PriceAdjustment.NONE else 8.).all()
    if asset_class is AssetClass.ETF and adjustment is PriceAdjustment.BACKWARD:
        assert (frame.AvailableDate > cutoff).all()
