"""Formal equity identity and causal decision behavior through public APIs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import pickle

import pandas as pd
import pytest
from dataflows import InstrumentId, MarketId, AssetClass, BarFrequency, TimeInterval
from strategy_runtime import (EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash,
    ResearchExecutionSpec, UsEquitySpec, AccountPolicy, CashAvailabilityPolicy, EquityPortfolio, StrategyRuntime)


def candidate(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'rules.py').write_text('THRESHOLD = 10\n', encoding='utf-8')
    (root / 'strategy.py').write_text('from .rules import THRESHOLD\nfrom strategy_runtime import EquityDecision\n'
        'counter = 0\ndef decide(ctx):\n global counter\n counter += 1\n'
        ' return EquityDecision.from_facts(int(ctx.history.Close.iloc[-1] >= ctx.parameters["threshold"] and counter == 1), '
        '"threshold decision", facts={"close": ctx.history.Close.iloc[-1], "threshold": ctx.parameters["threshold"]}, next_watch="next bar")\n', encoding='utf-8')
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    files = ('rules.py', 'strategy.py')
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'), spec, 1,
        'strategy:decide', files, equity_source_hash(root, files), '{"threshold":10}')
    return EquityStrategyCandidate('S999', 'C0001', definition, root)


def test_formal_equity_portable_identity_and_stateless_decisions(tmp_path):
    original = candidate(tmp_path / 'original')
    relocated = candidate(tmp_path / 'relocated')
    assert original.content_identity == relocated.content_identity
    assert pickle.loads(pickle.dumps(original)) == original
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(original.definition.to_dict()))) == original.definition
    changed = replace(original, definition=replace(original.definition, parameters_json='{"threshold":11}'))
    assert changed.content_identity != original.content_identity
    with pytest.raises(ValueError, match='parameter type differs'):
        replace(original.definition, parameters_json='{"threshold":true}')
    runtime = StrategyRuntime(execution_spec=original.definition.execution_spec)
    assert runtime.identify(original, dependencies=()) == original.content_identity
    instance = runtime.create(original)
    end = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    history = pd.DataFrame({'Date': [end], 'AvailableDate': [end], 'Close': [10.]})
    interval = TimeInterval(end, end + timedelta(minutes=30))
    first = instance.plan(history, interval, EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    second = instance.plan(history, interval, EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    assert first == second and first.target == 1
    assert first.explanation['basis'][1] == {'key': 'threshold', 'text': '10'}
    assert runtime.create(changed).plan(history, interval, EquityPortfolio(1000., 0, 0., 0), fee_rate=.001).target == 0
    (original.source_root / 'rules.py').write_text('THRESHOLD = 11\n', encoding='utf-8')
    with pytest.raises(ValueError, match='closure changed'):
        original.verify()


def test_formal_equity_rejects_undeclared_import_and_future_history(tmp_path):
    value = candidate(tmp_path)
    future = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
    history = pd.DataFrame({'Date': [future], 'AvailableDate': [future], 'Close': [10.]})
    with pytest.raises(ValueError, match='CAUSAL_TIME'):
        StrategyRuntime(execution_spec=value.definition.execution_spec).create(value).plan(history,
            TimeInterval(future - timedelta(minutes=30), future), EquityPortfolio(1000., 0, 0., 0), fee_rate=.001)
    (tmp_path / 'rules.py').write_text('import unlisted_dependency\n', encoding='utf-8')
    with pytest.raises(ValueError, match='undeclared equity dependency'):
        replace(value, definition=replace(value.definition,
            source_sha256=equity_source_hash(tmp_path, value.definition.source_files)))


def test_formal_decision_observes_split_before_planning(tmp_path):
    from trading_execution_engine.equity import EquityHistoricalExecutor
    value = candidate(tmp_path)
    value = replace(value, definition=replace(value.definition, parameters_json='{"threshold":1}'))
    start = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    starts = [start + timedelta(minutes=30 * i) for i in range(3)]
    ends = [x + timedelta(minutes=30) for x in starts]
    bars = pd.DataFrame({'BarStart': starts, 'Date': ends, 'AvailableDate': ends,
                         'Open': [10., 10., 5.], 'High': [10., 10., 5.],
                         'Low': [10., 10., 5.], 'Close': [10., 10., 5.], 'Volume': 10000.})
    constraints = pd.DataFrame({'Date': starts, 'AvailableDate': starts, 'QuantityStep': 1,
                                'PriceTick': .01, 'Tradable': True})
    actions = pd.DataFrame([{'Date': starts[2], 'AvailableDate': starts[2], 'EventId': 'split',
                             'Kind': 'SPLIT', 'Ratio': 2., 'CashPerShare': 0., 'PayAt': None}])
    executor = EquityHistoricalExecutor(specification=value.definition.execution_spec,
                                         initial_cash=1000., fee_rate=.001, actions=actions)
    result = StrategyRuntime(execution_spec=value.definition.execution_spec).create(value).run_window(
        bars, constraints, executor, start=starts[1], end=ends[-1], fee_rate=.001)
    assert result.account_points.iloc[-1].quantity == 196
    assert result.decisions.iloc[-1].reference_price == 5.
    assert result.decisions.iloc[-1].side == 'HOLD'
