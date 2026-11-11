"""Typed account projections preserve canonical records and immutable ownership."""
from dataclasses import replace
from decimal import Decimal
import json
import pickle

import pytest
from dataflows import BarFrequency, MarketId, TimeInterval
from strategy_runtime import (AccountDecisionEngine, AccountSnapshot, AccountStrategyState,
                              EquityPortfolio, PositionFeedback, StrategyComputation)
from execution_channels import contracts as ec
from execution_channels.policy import ExecutionPolicy
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import TradeIntent
from execution_channels.serialization import from_record, to_record
from czsc_trader.application import ec_boundary as boundary
from packages.strategy_runtime.tests.v4_fixture_support import setup


def prepared_facts(tmp_path, market=MarketId.US):
    candidate, prepared, _, _, _, _, _ = setup(tmp_path, market, BarFrequency.M30,
        StrategyComputation.STATEFUL_STEP, with_executor=False)
    interval = TimeInterval(prepared._data.starts[1], prepared._data.ends[1])
    account = AccountSnapshot(candidate.instrument, candidate.definition.execution_spec.account.currency,
        interval.start, 0, 100000., 100000., 0., 0, 0)
    return candidate, prepared, interval, account


@pytest.mark.parametrize('market', (MarketId.CN, MarketId.US))
def test_direct_plan_projection_matches_canonical_record_path(tmp_path, market):
    candidate, prepared, interval, account = prepared_facts(tmp_path, market)
    result = AccountDecisionEngine(candidate, prepared).propose(interval,
        EquityPortfolio(100000., 0, 0., 0), account, AccountStrategyState(), PositionFeedback(),
        owner='projection-account', fee_rate=.001)
    kwargs = dict(owner='projection-account', implementation=candidate.implementation_hash,
        fee_rate=.001, sell_remainder_policy='STRICT_STEP', reference_price=10.,
        execution_policy=candidate.definition.execution_policy)
    actual = boundary.execution_plan(result, account, candidate.definition.execution_spec, **kwargs)
    record = to_record(result.proposal.decision)
    record['explanation'] = {'facts': result.proposal.decision.explanation.to_dict()}
    expected = plan_account_decision(from_record(TradeIntent, record),
        from_record(ec.ReplayPoint, to_record(result.point)),
        from_record(ec.AccountSnapshot, to_record(account)), 10.,
        boundary.execution_spec(candidate.definition.execution_spec),
        owner=kwargs['owner'], implementation=kwargs['implementation'], fee_rate=.001,
        sell_remainder_policy=ec.SellRemainderPolicy.STRICT_STEP,
        execution_policy=from_record(ExecutionPolicy, to_record(candidate.definition.execution_policy)))
    assert actual == expected
    assert actual.plan_identity == expected.plan_identity


def test_feedback_projections_preserve_decimal_intervals_and_records(tmp_path):
    candidate, _, interval, account = prepared_facts(tmp_path)
    original = from_record(ec.AccountSnapshot, to_record(account))
    assert to_record(boundary.strategy_snapshot(original, candidate.instrument)) == to_record(original)
    position = ec.PositionCycle('cycle', ec.TimeInterval(interval.start, interval.end),
        ec.TimeInterval(interval.start, interval.end), 100, 1000., 0., 1., 1, 0)
    assert to_record(boundary.strategy_position(position)) == to_record(position)
    budget = ec.CycleBudget('cycle', 100, Decimal('.5'), Decimal('1000.1'),
        Decimal('1001.1001'), ec.EntryCyclePhase.ACTIVE)
    assert to_record(boundary.strategy_budget(budget)) == to_record(budget)
    event = ec.RecognizedAccountEvent('event', ec.RecognizedEventKind.POSITION_ADJUSTMENT,
        interval.start, 100, 200, 0., 0.)
    assert to_record(boundary.strategy_events((event,))) == to_record((event,))
    portfolio = ec.EquityPortfolio(100000., 0, 0., 2,
        closed_cycle_feedback=ec.EquityClosedCycleFeedback(ec.EquityClosedCycle('closed',
            ec.TimeInterval(interval.start, interval.end),
            ec.TimeInterval(interval.end, interval.end.replace(hour=interval.end.hour+1)),
            100, 1000., interval.end)))
    assert to_record(boundary.strategy_portfolio(portfolio)) == to_record(portfolio)


def test_cached_spec_preserves_exact_numeric_identity_and_rejects_mutable_input(tmp_path):
    candidate, _, _, _ = prepared_facts(tmp_path)
    spec = candidate.definition.execution_spec
    integer = replace(spec, slippage_bp=0)
    floating = replace(spec, slippage_bp=0.)
    first, second = boundary.execution_spec(integer), boundary.execution_spec(floating)
    assert first.fingerprint != second.fingerprint
    assert boundary.execution_spec(integer) is first
    with pytest.raises(TypeError, match='strategy execution specification'):
        boundary.execution_spec(to_record(integer))
    policy = boundary._execution_policy(boundary._IdentityKey(candidate.definition.execution_policy))
    with pytest.raises(TypeError):
        policy.settings['capital_mode'] = 'changed'


@pytest.mark.parametrize('project', (boundary.strategy_portfolio, boundary.strategy_position,
    boundary.strategy_feedback, boundary.strategy_budget, boundary.strategy_events))
def test_dynamic_projection_rejects_untyped_records(project):
    with pytest.raises(TypeError):
        project({})


def test_same_interval_observation_reuses_immutable_values_and_isolates_mapping(tmp_path, monkeypatch):
    candidate, prepared, interval, _ = prepared_facts(tmp_path)
    engine = AccountDecisionEngine(candidate, prepared)
    calls = []
    original = engine._features.at
    def observe(when):
        calls.append(when)
        return original(when)
    monkeypatch.setattr(engine._features, 'at', observe)
    first = engine.observation(interval)
    first[3]['foreign'] = object()
    second = engine.observation(interval)
    assert 'foreign' not in second[3]
    assert second[2] is first[2]
    assert calls == [interval.start]
    engine.observation(TimeInterval(prepared._data.starts[2], prepared._data.ends[2]))
    with pytest.raises(ValueError, match='causal time order'):
        engine.observation(interval)


def test_explicit_binding_keeps_owner_and_fee_validation(tmp_path, monkeypatch):
    candidate, prepared, interval, account = prepared_facts(tmp_path)
    engine = AccountDecisionEngine(candidate, prepared)
    def unexpected(*args):
        raise AssertionError('explicit binding must not compute another identity')
    monkeypatch.setattr(engine, 'state_binding', unexpected)
    args = (interval, EquityPortfolio(100000., 0, 0., 0), account, AccountStrategyState(), PositionFeedback())
    assert engine.propose(*args, owner='owner', fee_rate=.001, binding='explicit').point.execution_start == interval.start
    with pytest.raises(TypeError, match='owner identity'):
        engine.propose(*args, owner='', fee_rate=.001, binding='explicit')
    with pytest.raises(ValueError, match='fee must be finite'):
        engine.propose(*args, owner='owner', fee_rate=float('nan'), binding='explicit')


def test_parameter_reuse_preserves_definition_pickle_and_immutable_values(tmp_path):
    candidate, _, _, _ = prepared_facts(tmp_path)
    definition = replace(candidate.definition, parameters_json='{"scale":0.5}',
        parameter_schema_json='{"scale":{"type":"number"}}')
    assert definition.parameters is definition.parameters
    with pytest.raises(TypeError):
        definition.parameters['scale'] = 1.
    restored = pickle.loads(pickle.dumps(definition))
    assert restored.to_dict() == definition.to_dict()
    assert dict(restored.parameters) == json.loads(definition.parameters_json)
