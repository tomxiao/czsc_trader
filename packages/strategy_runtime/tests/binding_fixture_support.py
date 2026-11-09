"""Adjusted observation roles preserve raw execution and shared physical calendars."""




from datetime import date




from uuid import uuid4




from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparedDataRef, PriceAdjustment, SourceRef)


from strategy_runtime import EquityAuxiliaryInput, EquityAuxiliaryBinding, EquityInputBinding




def binding_fixture(market):
    instrument = InstrumentId(market, AssetClass.STOCK, 'LITE' if market is MarketId.US else '600000.SH')
    source = SourceRef('fixture', 'v1')
    start, end = date(2026, 10, 12), date(2026, 10, 16)
    auxiliary = EquityAuxiliaryInput('adjusted', instrument, source, BarFrequency.DAILY, 2, 86400, 'HFQ')
    primary = tuple((p.name.lower(), EquityDataRequest(instrument, source,
        EquityQuery(p, start, end, BarFrequency.DAILY, adjustment=PriceAdjustment.NONE if p is EquityProduct.SESSIONS else PriceAdjustment.BACKWARD))) for p in EquityProduct)
    items = primary + tuple((auxiliary.data_key(r.parameters.query.product), r) for r in auxiliary.requests(start, end))
    binding = EquityInputBinding(PreparedDataRef(uuid4(), uuid4(), 'a' * 64), instrument,
        'b' * 64, tuple((key, 'c' * 64) for key, _ in primary), 2,
        (EquityAuxiliaryBinding(auxiliary, 'c' * 64, 'c' * 64),),
        request_bindings=tuple((key, r.parameters) for key, r in items))
    return binding, items
