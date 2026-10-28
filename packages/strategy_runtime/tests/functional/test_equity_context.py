"""Declared auxiliary/session inputs: causal slicing, identity and isolation."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import pickle
from uuid import uuid4

import pandas as pd
import pytest
from dataflows import (InstrumentId, MarketId, AssetClass, BarFrequency, TimeInterval,
                       TradingSession, SourceRef, PreparedDataRef, EquityProduct)
from strategy_runtime import (EquityAuxiliaryInput, EquityAuxiliaryBinding, EquityInputBinding,
    EquityStrategyCandidate, EquityStrategyDefinition, EquityPortfolio,
    DecisionPoint, ResearchExecutionSpec, UsEquitySpec, AccountPolicy, CashAvailabilityPolicy,
    StrategyRuntime, equity_source_hash, build_equity_decision_context)


def make_candidate(root, *, enabled=True, latency=0):
    root.mkdir(parents=True, exist_ok=True)
    source = ('from strategy_runtime import EquityDecision\n'
        'def decide(ctx):\n'
        ' values = list(ctx.auxiliary_histories)\n'
        ' previous = ctx.auxiliary_histories[values[0]].Close.iloc[-1] if values else 0\n'
        ' if values: ctx.auxiliary_histories[values[0]].iloc[-1, 4] = 999\n'
        ' return EquityDecision.from_facts(int(bool(values)), "declared context", '
        'facts={"aliases": str(values), "close": previous, "session": str(ctx.session), '
        '"available": str(ctx.session_available_at)}, next_watch="next interval")\n')
    (root / 'strategy.py').write_text(source, encoding='utf-8')
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.,
        data_latency_seconds=latency)
    auxiliary = EquityAuxiliaryInput('market', InstrumentId(MarketId.US, AssetClass.ETF, 'SPY'),
        SourceRef('synthetic', 'v1'), BarFrequency.M30, 2, 3600)
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'), spec,
        1, 'strategy:decide', ('strategy.py',), equity_source_hash(root, ('strategy.py',)),
        auxiliary_inputs=(auxiliary,) if enabled else (), session_context=enabled)
    return EquityStrategyCandidate('S999', 'C0001', definition, root)


def fixture(day=date(2025, 11, 28), *, close_hour=18):
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=14, minute=30)
    session = TradingSession(day, 'America/New_York',
        (TimeInterval(start, start.replace(hour=close_hour, minute=0)),))
    decision = start + timedelta(hours=1)
    point = DecisionPoint(decision, decision, TimeInterval(decision, decision + timedelta(minutes=30)))
    ends = [decision - timedelta(minutes=30), decision, decision + timedelta(minutes=30)]
    aux = pd.DataFrame({'Date': ends, 'AvailableDate': ends, 'Open': 10., 'High': 11.,
                        'Close': [10., 11., 10.], 'Low': 9., 'Volume': 100.})
    primary = aux.iloc[:2].copy(deep=True)
    sessions = pd.DataFrame({'Date': [start], 'AvailableDate': [start], 'SessionDate': [day.isoformat()]})
    return primary, aux, point, sessions, (session,)


def build(value, data, **overrides):
    history, aux, point, sessions, calendar = data
    arguments = dict(auxiliary_histories={'market': aux}, sessions=sessions, trading_sessions=calendar)
    arguments.update(overrides)
    return build_equity_decision_context(value.definition, history, EquityPortfolio(1000., 0, 0., 0),
                                        point, **arguments)


def test_auxiliary_definition_binding_roundtrip_and_legacy_identity(tmp_path):
    value = make_candidate(tmp_path)
    definition = value.definition
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(definition.to_dict()))) == definition
    assert pickle.loads(pickle.dumps(value)) == value
    old = replace(definition, auxiliary_inputs=(), session_context=False)
    assert 'auxiliary_inputs' not in old.to_dict() and 'session_context' not in old.to_dict()
    assert old.content_identity != definition.content_identity
    assert EquityStrategyDefinition.from_dict(old.to_dict()) == old
    item = definition.auxiliary_inputs[0]
    auxbinding = EquityAuxiliaryBinding(item, 'b' * 64, 'c' * 64)
    binding = EquityInputBinding(PreparedDataRef(uuid4(), uuid4(), 'a' * 64), definition.instrument,
        definition.execution_spec.fingerprint, tuple((p, 'd' * 64) for p in
        ('bars', 'sessions', 'actions', 'constraints')), 1, (auxbinding,))
    assert EquityInputBinding.from_dict(json.loads(json.dumps(binding.to_dict()))) == binding
    requests = item.requests(date(2025, 1, 1), date(2025, 1, 2))
    assert [binding.request_key(r) for r in requests] == ['auxiliary:market:bars', 'auxiliary:market:sessions']
    assert binding.expected_identities[item.data_key(EquityProduct.BARS)] == 'b' * 64
    with pytest.raises(TypeError):
        binding.expected_identities['bars'] = 'e' * 64
    with pytest.raises(ValueError, match='duplicate auxiliary alias'):
        replace(definition, auxiliary_inputs=(item, item))


@pytest.mark.parametrize(('field', 'bad'), [('warmup_bars', True), ('warmup_bars', 0),
    ('max_age_seconds', float('nan')), ('max_age_seconds', -1), ('max_age_seconds', True),
    ('analysis_price', 'QFQ'), ('name', 'market:bars')])
def test_auxiliary_illegal_declaration(tmp_path, field, bad):
    item = make_candidate(tmp_path).definition.auxiliary_inputs[0]
    with pytest.raises((ValueError, TypeError)):
        replace(item, **{field: bad})


def test_public_plan_context_causal_slice_halfday_and_isolation(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    context = build(value, data)
    assert len(context.auxiliary_histories['market']) == 2
    assert context.session.segments[-1].end.hour == 18
    assert context.session_available_at == data[3].AvailableDate.iloc[0].to_pydatetime()
    with pytest.raises(TypeError):
        context.auxiliary_histories['new'] = data[1]
    first = value.decide(context)
    second = value.decide(context)
    assert first == second
    assert context.auxiliary_histories['market'].Close.iloc[-1] == 11.
    assert data[1].Close.tolist() == [10., 11., 10.]
    instance = StrategyRuntime(execution_spec=value.definition.execution_spec).create(value)
    result = instance.plan(data[0], data[2].execution_interval, EquityPortfolio(1000., 0, 0., 0),
        fee_rate=.001, auxiliary_histories={'market': data[1]}, sessions=data[3], trading_sessions=data[4])
    assert result.target == 1


def test_auxiliary_delayed_availability_warmup_staleness_and_missing(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    delayed = data[1].copy(deep=True)
    delayed.loc[1, 'AvailableDate'] += timedelta(seconds=1)
    with pytest.raises(ValueError, match='WARMUP_INSUFFICIENT'):
        build(value, data, auxiliary_histories={'market': delayed})
    with pytest.raises(ValueError, match='UNAVAILABLE'):
        build(value, data, auxiliary_histories={})
    missing = data[1].copy(deep=True)
    missing['BarStatus'] = ['OBSERVED', 'MISSING', 'OBSERVED']
    with pytest.raises(ValueError, match='UNAVAILABLE: latest'):
        build(value, data, auxiliary_histories={'market': missing})
    zero = data[1].copy(deep=True)
    zero.loc[1, 'Volume'] = 0
    with pytest.raises(ValueError, match='zero-volume'):
        build(value, data, auxiliary_histories={'market': zero})
    aged = data[1].iloc[:2].copy(deep=True)
    aged['Date'] -= timedelta(hours=2)
    aged['AvailableDate'] -= timedelta(hours=2)
    with pytest.raises(ValueError, match='STALE'):
        build(value, data, auxiliary_histories={'market': aged})
    latency = replace(value, definition=replace(value.definition,
        execution_spec=replace(value.definition.execution_spec, data_latency_seconds=1)))
    with pytest.raises(ValueError, match='WARMUP_INSUFFICIENT'):
        build(latency, (data[0].iloc[:1].copy(), *data[1:]))


def test_direct_decision_rejects_future_auxiliary_session_and_strips_undeclared(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    context = build(value, data)
    with pytest.raises(ValueError, match='future auxiliary'):
        value.decide(replace(context, auxiliary_histories={'market': data[1]}))
    with pytest.raises(ValueError, match='not yet available'):
        value.decide(replace(context, session_available_at=context.point.decision_at + timedelta(seconds=1)))
    with pytest.raises(TypeError, match='typed availability'):
        value.decide(replace(context, session_available_at=context.session_available_at.isoformat()))
    with pytest.raises(ValueError, match='UNAVAILABLE'):
        value.decide(replace(context, auxiliary_histories={}))
    legacy = replace(value, definition=replace(value.definition, auxiliary_inputs=(), session_context=False))
    decision = legacy.decide(replace(context, auxiliary_histories={'future': data[1]}, session_available_at='invalid'))
    assert decision.target == 0
    assert decision.explanation.basis[-1].text == 'None'


def test_session_dst_exact_interval_and_calendar_mismatch(tmp_path):
    value = make_candidate(tmp_path)
    data = fixture(date(2025, 3, 10), close_hour=20)
    session = data[4][0]
    start = session.segments[0].start - timedelta(hours=1)
    actual = TradingSession(session.session_date, session.timezone, (TimeInterval(start, start.replace(hour=20, minute=0)),))
    table = data[3].copy(deep=True)
    table['Date'] = table['AvailableDate'] = start
    context = build(value, data, sessions=table, trading_sessions=(actual,))
    assert context.session.segments[0].start.hour == 13
    table['SessionDate'] = '2025-03-11'
    with pytest.raises(ValueError, match='calendar evidence'):
        build(value, data, sessions=table, trading_sessions=(actual,))
    with pytest.raises(ValueError, match='exact execution interval'):
        value.decide(replace(context, session=TradingSession(actual.session_date, actual.timezone,
            (TimeInterval(start, start + timedelta(minutes=30)),))))


def test_daily_auxiliary_at_intraday_decision_uses_completed_prior_day(tmp_path):
    value, data = make_candidate(tmp_path), fixture(date(2025, 12, 1), close_hour=21)
    declaration = replace(value.definition.auxiliary_inputs[0], instrument=value.instrument,
        frequency=BarFrequency.DAILY, warmup_bars=1, max_age_seconds=72 * 3600)
    value = replace(value, definition=replace(value.definition, auxiliary_inputs=(declaration,)))
    dates = [datetime(2025, 11, 27, 21, tzinfo=timezone.utc),
             datetime(2025, 11, 28, 18, tzinfo=timezone.utc),
             datetime(2025, 12, 1, 21, tzinfo=timezone.utc)]
    daily = pd.DataFrame({'Date': dates, 'AvailableDate': dates, 'Open': 10., 'High': 11.,
                         'Low': 9., 'Close': [10., 11., 10.], 'Volume': 100.})
    context = build(value, data, auxiliary_histories={'market': daily})
    assert context.auxiliary_histories['market'].Date.tolist() == dates[:2]
    assert context.auxiliary_histories['market'].Close.iloc[-1] == 11.
    # Calendar age includes the weekend; no automatic trading-day tolerance.
    tight = replace(value, definition=replace(value.definition,
        auxiliary_inputs=(replace(declaration, max_age_seconds=48 * 3600),)))
    with pytest.raises(ValueError, match='STALE'):
        build(tight, data, auxiliary_histories={'market': daily})
    delayed = daily.copy(deep=True)
    delayed.loc[1, 'AvailableDate'] = data[2].decision_at + timedelta(seconds=1)
    with pytest.raises(ValueError, match='STALE'):
        build(value, data, auxiliary_histories={'market': delayed})
    with pytest.raises(ValueError, match='future auxiliary'):
        value.decide(replace(context, auxiliary_histories={'market': daily}))


def test_auxiliary_context_exposes_only_canonical_observations(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    auxiliary = data[1].copy(deep=True)
    extra = {'future_forecast': [900]}
    auxiliary['VendorExtra'] = [extra, extra, extra]
    auxiliary['Amount'] = [1000., 1100., 1000.]
    auxiliary['BarStart'] = auxiliary.Date - timedelta(minutes=30)
    context = build(value, data, auxiliary_histories={'market': auxiliary})
    assert list(context.auxiliary_histories['market']) == [
        'Date', 'AvailableDate', 'BarStart', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount']
    assert context.auxiliary_histories['market'].Amount.tolist() == [1000., 1100.]
    value.decide(context)
    assert extra == {'future_forecast': [900]}
    auxiliary.loc[1, 'Amount'] = float('nan')
    with pytest.raises(ValueError, match='Amount must be finite'):
        build(value, data, auxiliary_histories={'market': auxiliary})
