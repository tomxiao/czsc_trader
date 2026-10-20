from dataclasses import replace
from datetime import date, datetime

import pandas as pd
import pytest
from dataflows import PreparePolicy
from strategy_runtime import (
    DecisionFeedback, HistoryCalculationContext, RuntimeCompatibilityError, RuntimeContractError,
    SignalHistoryMode, StrategyInit, StrategyRuntime, TradableWindow, implementation_sha256,
)

from test_public_runtime import _flows


def _candidate(runtime_candidate, *, strict=True, kernel=True):
    path = runtime_candidate.source_root / 'strategies/current_fixture.py'
    source = path.read_text(encoding='utf-8')
    if strict:
        source = source.replace('StrategyImplementation,', 'StrategyImplementationV2,')
        source = source.replace('(StrategyImplementation):', '(StrategyImplementationV2):')
    if kernel:
        source = source.replace('def calculate_history(self, inputs, sessions):',
            'def calculate_context_history(self, inputs, context):\n        sessions = context.sessions')
    path.write_text(source, encoding='utf-8')
    payload = dict(runtime_candidate.payload)
    payload['runtime'] = {**dict(payload['runtime']), 'contract_version': 2,
        'source_sha256': implementation_sha256(('strategies/current_fixture.py',),
                                               source_root=runtime_candidate.source_root)}
    return replace(runtime_candidate, payload=payload)


def test_strict_runtime_requires_one_explicit_context_kernel(runtime_candidate):
    candidate = _candidate(runtime_candidate, kernel=False)
    with pytest.raises(RuntimeCompatibilityError, match='calculate_context_history'):
        StrategyRuntime().describe(candidate)


def test_contract_two_rejects_legacy_implementation(runtime_candidate):
    candidate = _candidate(runtime_candidate, strict=False, kernel=False)
    with pytest.raises(RuntimeCompatibilityError, match='requires StrategyImplementationV2'):
        StrategyRuntime().describe(candidate)


def test_contract_two_factory_cannot_return_a_legacy_instance(runtime_candidate):
    path = runtime_candidate.source_root / 'strategies/current_fixture.py'
    legacy = path.read_text(encoding='utf-8').replace(
        'class ' + runtime_candidate.payload['runtime']['qualname'] + '(', 'class LegacyFixture(')
    legacy = '\n'.join(line for line in legacy.splitlines() if not line.startswith('from __future__'))
    candidate = _candidate(runtime_candidate)
    source = path.read_text(encoding='utf-8').replace('return cls(parameters)', 'return LegacyFixture(parameters)')
    path.write_text(source + '\n' + legacy + '\n', encoding='utf-8')
    payload = dict(candidate.payload)
    payload['runtime'] = {**dict(payload['runtime']), 'source_sha256': implementation_sha256(
        ('strategies/current_fixture.py',), source_root=candidate.source_root)}
    with pytest.raises(RuntimeCompatibilityError, match='factory must return StrategyImplementationV2'):
        StrategyRuntime().describe(replace(candidate, payload=payload))


def test_feedback_declaration_is_typed_and_bound_to_candidate_identity(runtime_candidate):
    candidate = _candidate(runtime_candidate)
    runtime = StrategyRuntime()
    unknown = runtime.identify(candidate, dependencies=())
    declared = replace(candidate, payload={**dict(candidate.payload), 'decision_feedback': 'MARKET_INTENT'})
    assert runtime.describe(declared).decision_feedback is DecisionFeedback.MARKET_INTENT
    assert runtime.identify(declared, dependencies=()).content_sha256 != unknown.content_sha256
    assert runtime.describe(declared).runtime_sha256 != runtime.describe(candidate).runtime_sha256
    with pytest.raises(RuntimeContractError, match='feedback declaration'):
        replace(candidate, payload={**dict(candidate.payload), 'decision_feedback': True})
    unsupported = replace(candidate, payload={**dict(candidate.payload), 'decision_feedback': 'CONFIRMED_EXECUTION'})
    with pytest.raises(RuntimeCompatibilityError, match='not implemented'):
        runtime.describe(unsupported)


def test_context_rejects_missing_coverage_and_future_or_untyped_dates():
    window = TradableWindow(date(2026, 9, 2), date(2026, 9, 3))
    signals = (date(2026, 9, 1), date(2026, 9, 2))
    with pytest.raises(RuntimeContractError, match='omits'):
        HistoryCalculationContext(SignalHistoryMode.WINDOW, window, signals, signals[:1])
    with pytest.raises(RuntimeContractError, match='last signal'):
        HistoryCalculationContext(SignalHistoryMode.WINDOW, window, signals, (*signals, date(2026, 9, 3)))
    with pytest.raises(RuntimeContractError, match='ordered unique dates'):
        HistoryCalculationContext(SignalHistoryMode.WINDOW, window,
                                  (datetime(2026, 9, 1),), signals)


def test_modes_share_kernel_with_isolated_initial_state_and_full_feature_warmup(
    tmp_path, runtime_candidate,
):
    candidate = _candidate(runtime_candidate)
    path = candidate.source_root / 'strategies/current_fixture.py'
    source = path.read_text(encoding='utf-8')
    source = source.replace('                1,\n                CutoffRule.SIGNAL_SESSION,',
                            '                3,\n                CutoffRule.SIGNAL_SESSION,')
    source = source.replace('if first_signal <= day <= last_signal',
        'if min(date.fromisoformat(r.start) for r in requests.values()) <= day <= last_signal')
    source = source[:source.index('    def calculate_context_history')] + '''    def calculate_context_history(self, inputs, context):
        values = inputs['flow'].set_index(pd.to_datetime(inputs['flow'].Date)).Flow
        indicator = values.rolling(2, min_periods=2).mean()
        held = 0
        rows = []
        for day in context.sessions:
            if held >= 2:
                held = 0
                target = 0.0
            elif indicator.loc[day] > self.definition.parameters.values['threshold']:
                held += 1
                target = 1.0
            else:
                target = 0.0
            rows.append({'target_position': target, 'fixture_signal': indicator.loc[day]})
        return pd.DataFrame(rows, index=context.sessions)
'''
    path.write_text(source, encoding='utf-8')
    payload = dict(candidate.payload)
    payload['runtime'] = {**dict(payload['runtime']), 'source_sha256': implementation_sha256(
        ('strategies/current_fixture.py',), source_root=candidate.source_root)}
    candidate = replace(candidate, payload=payload)
    flows = _flows(tmp_path)
    window = TradableWindow(date(2026, 9, 2), date(2026, 9, 3))
    strategy = StrategyRuntime(dataflows=flows).create(StrategyInit(candidate, window, tmp_path / 'v2'))
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    independent = strategy.inspect_signals(history_mode=SignalHistoryMode.WINDOW)
    continuous = strategy.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)
    assert independent.index.tolist() == [pd.Timestamp('2026-09-01'), pd.Timestamp('2026-09-02')]
    assert independent.fixture_signal.iloc[0] == pytest.approx(0.8)
    assert independent.target_position.tolist() == [1.0, 1.0]
    assert continuous.loc['2026-09-02', 'target_position'] == 0.0
    pd.testing.assert_frame_equal(independent, strategy.inspect_signals())
    second = StrategyRuntime(dataflows=flows).create(StrategyInit(candidate, window, tmp_path / 'fresh'))
    second.prepare_data(policy=PreparePolicy.REUSE)
    pd.testing.assert_frame_equal(independent, second.inspect_signals())


@pytest.mark.parametrize('modes', [
    (SignalHistoryMode.WINDOW, SignalHistoryMode.CONTINUOUS),
    (SignalHistoryMode.CONTINUOUS, SignalHistoryMode.WINDOW),
])
def test_mutating_kernel_cannot_contaminate_other_modes_or_instances(
    tmp_path, runtime_candidate, modes,
):
    candidate = _candidate(runtime_candidate)
    path = candidate.source_root / 'strategies/current_fixture.py'
    source = path.read_text(encoding='utf-8')
    source = source[:source.index('    def calculate_context_history')] + '''    def calculate_context_history(self, inputs, context):
        inputs['flow'].loc[:, 'Flow'] += 1.0
        values = inputs['flow'].set_index(pd.to_datetime(inputs['flow'].Date)).Flow
        return pd.DataFrame({'target_position': 1.0,
                             'fixture_signal': values.reindex(context.sessions).to_numpy()},
                            index=context.sessions)
'''
    path.write_text(source, encoding='utf-8')
    payload = dict(candidate.payload)
    payload['runtime'] = {**dict(payload['runtime']), 'source_sha256': implementation_sha256(
        ('strategies/current_fixture.py',), source_root=candidate.source_root)}
    candidate = replace(candidate, payload=payload)
    flows = _flows(tmp_path)
    window = TradableWindow(date(2026, 9, 2), date(2026, 9, 3))

    def prepared_instance(directory):
        strategy = StrategyRuntime(dataflows=flows).create(StrategyInit(candidate, window, directory))
        preparation = strategy.prepare_data(policy=PreparePolicy.REUSE)
        return strategy, preparation

    strategy, preparation = prepared_instance(tmp_path / 'mutating')
    binding = strategy.input_binding
    prices = strategy.inspect_price_history()
    histories = {}
    for mode in modes:
        histories[mode] = strategy.inspect_signals(history_mode=mode)
        assert histories[mode].fixture_signal.to_list() == pytest.approx([1.8, 1.8])
        assert strategy.input_binding == binding
        assert strategy.prepare_data(binding=binding).data_identity == preparation.data_identity
        pd.testing.assert_frame_equal(prices, strategy.inspect_price_history())

    for mode in modes:
        fresh, fresh_preparation = prepared_instance(tmp_path / f'fresh-{mode.value}')
        assert fresh_preparation.data_identity == preparation.data_identity
        pd.testing.assert_frame_equal(histories[mode], fresh.inspect_signals(history_mode=mode))
        pd.testing.assert_frame_equal(histories[mode], strategy.inspect_signals(history_mode=mode))
