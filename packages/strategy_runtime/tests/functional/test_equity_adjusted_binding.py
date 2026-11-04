"""Adjusted observation roles preserve raw execution and shared physical calendars."""
from dataclasses import replace
from datetime import date
import json
from uuid import uuid4

import pytest
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparedDataRef, PriceAdjustment, SourceRef)
from strategy_runtime import EquityAuxiliaryInput, EquityAuxiliaryBinding, EquityInputBinding
from test_equity_context import make_candidate


def binding_fixture(market):
    instrument = InstrumentId(market, AssetClass.STOCK, 'LITE' if market is MarketId.US else '600000.SH')
    source = SourceRef('fixture', 'v1')
    start, end = date(2026, 10, 12), date(2026, 10, 16)
    auxiliary = EquityAuxiliaryInput('adjusted', instrument, source, BarFrequency.DAILY, 2, 86400, 'HFQ')
    primary = tuple((p.name.lower(), EquityDataRequest(instrument, source,
        EquityQuery(p, start, end, BarFrequency.DAILY))) for p in EquityProduct)
    items = primary + tuple((auxiliary.data_key(r.parameters.query.product), r) for r in auxiliary.requests(start, end))
    binding = EquityInputBinding(PreparedDataRef(uuid4(), uuid4(), 'a' * 64), instrument,
        'b' * 64, tuple((key, 'c' * 64) for key, _ in primary), 2,
        (EquityAuxiliaryBinding(auxiliary, 'd' * 64, 'c' * 64),),
        request_bindings=tuple((key, r.parameters) for key, r in items))
    return binding, items


@pytest.mark.parametrize('market', (MarketId.CN, MarketId.US))
def test_hfq_roles_roundtrip_and_shared_calendar(market):
    binding, items = binding_fixture(market)
    serialized = json.loads(json.dumps(binding.to_dict()))
    assert EquityInputBinding.from_dict(serialized) == binding
    assert len(set(r.parameters for _, r in items)) == 5
    assert binding.bind_requests(tuple(r for _, r in items)) == items
    assert binding.bind_requests(tuple(dict((r.parameters, r) for _, r in items).values())) == items
    assert binding.request_key(items[-2][1]) == 'auxiliary:adjusted:bars'
    assert items[-2][1].parameters.query.adjustment is PriceAdjustment.BACKWARD
    assert items[-1][1].parameters.query.adjustment is PriceAdjustment.NONE
    with pytest.raises(ValueError, match='shared roles'):
        binding.request_key(items[-1][1])
    with pytest.raises(ValueError, match='bound product selection'):
        binding.bind_requests(tuple(r for _, r in items[:-2]))
    bad = replace(items[-2][1].parameters.query, adjustment=PriceAdjustment.FORWARD)
    request = EquityDataRequest(binding.instrument, items[-2][1].parameters.source, bad)
    with pytest.raises(ValueError, match='bound product selection'):
        binding.bind_requests(tuple(r for _, r in items) + (request,))


def test_binding_rejects_role_or_fingerprint_substitution():
    binding, items = binding_fixture(MarketId.US)
    with pytest.raises(ValueError, match='explicit request bindings'):
        replace(binding, request_bindings=())
    with pytest.raises(ValueError, match='exact product roles'):
        replace(binding, request_bindings=binding.request_bindings[:-1])
    with pytest.raises(ValueError, match='declared observation'):
        replace(binding, request_bindings=tuple((key,
            replace(p, query=replace(p.query, adjustment=PriceAdjustment.NONE))
            if key == 'auxiliary:adjusted:bars' else p) for key, p in binding.request_bindings))
    with pytest.raises(ValueError, match='inconsistent content'):
        replace(binding, auxiliary_inputs=(replace(binding.auxiliary_inputs[0], sessions_sha256='e' * 64),))
    with pytest.raises(ValueError, match='traded RAW'):
        replace(binding, request_bindings=tuple((key,
            replace(p, query=replace(p.query, adjustment=PriceAdjustment.BACKWARD))
            if key == 'bars' else p) for key, p in binding.request_bindings))


def test_hfq_requires_v4_and_primary_stays_raw(tmp_path):
    from strategy_runtime import StrategyComputation
    from strategy_runtime.equity_features import FeatureGraph
    from strategy_runtime.equity_replay import StrategyStateSchema
    candidate = make_candidate(tmp_path)
    definition = candidate.definition
    auxiliary = replace(definition.auxiliary_inputs[0], instrument=definition.instrument, analysis_price='HFQ')
    with pytest.raises(ValueError, match='require V4'):
        replace(definition, auxiliary_inputs=(auxiliary,))
    v4 = replace(definition, contract_version=4, feature_graph=FeatureGraph(), state_schema=StrategyStateSchema(),
        computation=StrategyComputation.STATEFUL_STEP, auxiliary_inputs=(auxiliary,))
    assert type(v4).from_dict(json.loads(json.dumps(v4.to_dict()))) == v4
    with pytest.raises(ValueError, match='analysis price contract'):
        replace(v4, analysis_price='HFQ')
    with pytest.raises(ValueError, match='duplicates the primary'):
        replace(v4, auxiliary_inputs=(replace(auxiliary, analysis_price='RAW'),))
    legacy = replace(definition, auxiliary_inputs=(), session_context=False)
    assert 'auxiliary_inputs' not in legacy.to_dict()
    binding, _ = binding_fixture(MarketId.US)
    old = replace(binding, auxiliary_inputs=(), request_bindings=())
    assert 'request_bindings' not in old.to_dict()
    assert type(old).from_dict(json.loads(json.dumps(old.to_dict()))) == old
