"""RAW execution publication cannot replace the strategy's HFQ input contract."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from dataflows import (AssetClass, BarFrequency, EquityProduct, EquityQuery,
    EquitySession, InstrumentId, MarketId, PreparedDataRef, PriceAdjustment,
    SourceRef, TimeInterval)
from dataflows.equity_contracts import EquityParameters
from paper_trading_engine.execution_reference import ExecutionReferenceBinding, PreparedExecutionReference


@pytest.mark.parametrize('market,symbol', [(MarketId.CN, '510500.SH'), (MarketId.US, 'MU')])
def test_raw_execution_reference_roundtrip_causality_and_integrity(market, symbol):
    instrument = InstrumentId(market, AssetClass.ETF if market is MarketId.CN else AssetClass.STOCK, symbol)
    query = EquityQuery(EquityProduct.BARS, date(2026, 10, 1), date(2026, 10, 5),
                        BarFrequency.DAILY, PriceAdjustment.NONE, EquitySession.REGULAR)
    parameters = EquityParameters(instrument, SourceRef('fixture', 'v1'), query)
    binding = ExecutionReferenceBinding(parameters, PreparedDataRef(uuid4(), uuid4(), 'a'*64), 'b'*64)
    assert ExecutionReferenceBinding.from_dict(binding.to_dict()) == binding
    with pytest.raises(ValueError, match='independent RAW'):
        replace(binding, parameters=replace(parameters, query=replace(query, adjustment=PriceAdjustment.BACKWARD)))
    start = datetime(2026, 10, 5, tzinfo=timezone.utc)
    frame = pd.DataFrame({'Date': [start-timedelta(days=1), start+timedelta(days=1)],
        'AvailableDate': [start-timedelta(days=1), start+timedelta(days=1)], 'Close': [10., 99.]})
    class Data:
        def fetch(self, request, *, prepared):
            assert request == binding.request and prepared == binding.prepared
            return SimpleNamespace(ready=True, dataframe=frame,
                                   identity=SimpleNamespace(content_sha256='b'*64))
    reference = binding.fetch(Data(), TimeInterval(start, start+timedelta(hours=1)), latency_seconds=0)
    assert reference.price == Decimal('10')
    assert reference.observed_through < start
    with pytest.raises(ValueError, match='changed'):
        replace(binding, content_sha256='c'*64).fetch(Data(), TimeInterval(start, start+timedelta(hours=1)), latency_seconds=0)


@pytest.mark.parametrize('price', [Decimal('0'), Decimal('-1'), Decimal('NaN'), Decimal('Infinity')])
def test_execution_reference_rejects_invalid_price(price):
    with pytest.raises(ValueError, match='positive'):
        PreparedExecutionReference(price, datetime(2026, 10, 5, tzinfo=timezone.utc), 'a'*64)
