from dataclasses import replace
from datetime import date

import pandas as pd
import pytest
from dataflows import PreparePolicy
from strategy_runtime import (
    RuntimeCompatibilityError,
    SignalHistoryMode,
    StrategyInit,
    StrategyRuntime,
    TradableWindow,
    implementation_sha256,
)

from packages.strategy_runtime.tests.session_runtime_support import _flows


def _candidate(runtime_candidate, *, strict=True, kernel=True):
    path = runtime_candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8")
    if strict:
        source = source.replace("StrategyImplementation,", "StrategyImplementationV2,")
        source = source.replace("(StrategyImplementation):", "(StrategyImplementationV2):")
    if kernel:
        source = source.replace(
            "def calculate_history(self, inputs, sessions):",
            "def calculate_context_history(self, inputs, context):\n        sessions = context.sessions",
        )
    path.write_text(source, encoding="utf-8")
    payload = dict(runtime_candidate.payload)
    payload["runtime"] = {
        **dict(payload["runtime"]),
        "contract_version": 2,
        "source_sha256": implementation_sha256(
            ("strategies/current_fixture.py",), source_root=runtime_candidate.source_root
        ),
    }
    return replace(runtime_candidate, payload=payload)


def test_SRT_27_C01_contract_two_factory_cannot_return_a_legacy_instance(runtime_candidate):
    path = runtime_candidate.source_root / "strategies/current_fixture.py"
    legacy = path.read_text(encoding="utf-8").replace(
        "class " + runtime_candidate.payload["runtime"]["qualname"] + "(", "class LegacyFixture("
    )
    legacy = "\n".join(
        line for line in legacy.splitlines() if not line.startswith("from __future__")
    )
    candidate = _candidate(runtime_candidate)
    source = path.read_text(encoding="utf-8").replace(
        "return cls(parameters)", "return LegacyFixture(parameters)"
    )
    path.write_text(source + "\n" + legacy + "\n", encoding="utf-8")
    payload = dict(candidate.payload)
    payload["runtime"] = {
        **dict(payload["runtime"]),
        "source_sha256": implementation_sha256(
            ("strategies/current_fixture.py",), source_root=candidate.source_root
        ),
    }
    with pytest.raises(
        RuntimeCompatibilityError, match="factory must return StrategyImplementationV2"
    ):
        StrategyRuntime().describe(replace(candidate, payload=payload))


@pytest.mark.parametrize(
    "modes",
    [
        (SignalHistoryMode.WINDOW, SignalHistoryMode.CONTINUOUS),
    ],
    ids=["SRT-13-C04"],
)
def test_mutating_kernel_cannot_contaminate_other_modes_or_instances(
    tmp_path,
    runtime_candidate,
    modes,
):
    candidate = _candidate(runtime_candidate)
    path = candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8")
    source = (
        source[: source.index("    def calculate_context_history")]
        + """    def calculate_context_history(self, inputs, context):
        inputs['flow'].loc[:, 'Flow'] += 1.0
        values = inputs['flow'].set_index(pd.to_datetime(inputs['flow'].Date)).Flow
        return pd.DataFrame({'target_position': 1.0,
                             'fixture_signal': values.reindex(context.sessions).to_numpy()},
                            index=context.sessions)
"""
    )
    path.write_text(source, encoding="utf-8")
    payload = dict(candidate.payload)
    payload["runtime"] = {
        **dict(payload["runtime"]),
        "source_sha256": implementation_sha256(
            ("strategies/current_fixture.py",), source_root=candidate.source_root
        ),
    }
    candidate = replace(candidate, payload=payload)
    flows = _flows(tmp_path)
    window = TradableWindow(date(2026, 9, 2), date(2026, 9, 3))

    def prepared_instance(directory, *, binding=None):
        strategy = StrategyRuntime(dataflows=flows).create(
            StrategyInit(candidate, window, directory)
        )
        preparation = (
            strategy.prepare_data(policy=PreparePolicy.REUSE)
            if binding is None
            else strategy.prepare_data(binding=binding)
        )
        return strategy, preparation

    strategy, preparation = prepared_instance(tmp_path / "mutating")
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
        # Fresh instances load the same authenticated input binding, without
        # preparing its unchanged supplier inputs again. Each retains its own
        # materialized frames, context directory and history cache.
        fresh, fresh_preparation = prepared_instance(
            tmp_path / f"fresh-{mode.value}", binding=binding
        )
        assert fresh_preparation.data_identity == preparation.data_identity
        pd.testing.assert_frame_equal(histories[mode], fresh.inspect_signals(history_mode=mode))
        pd.testing.assert_frame_equal(histories[mode], strategy.inspect_signals(history_mode=mode))


@pytest.fixture
def mode_strategy(tmp_path, runtime_candidate):
    candidate = _candidate(runtime_candidate)
    path = candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "                1,\n                CutoffRule.SIGNAL_SESSION,",
        "                3,\n                CutoffRule.SIGNAL_SESSION,",
    )
    source = source.replace(
        "if first_signal <= day <= last_signal",
        "if min(date.fromisoformat(r.start) for r in requests.values()) <= day <= last_signal",
    )
    source = (
        source[: source.index("    def calculate_context_history")]
        + """    def calculate_context_history(self, inputs, context):
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
"""
    )
    path.write_text(source, encoding="utf-8")
    payload = dict(candidate.payload)
    payload["runtime"] = {
        **dict(payload["runtime"]),
        "source_sha256": implementation_sha256(
            ("strategies/current_fixture.py",), source_root=candidate.source_root
        ),
    }
    candidate = replace(candidate, payload=payload)
    flows = _flows(tmp_path)
    window = TradableWindow(date(2026, 9, 2), date(2026, 9, 3))
    strategy = StrategyRuntime(dataflows=flows).create(
        StrategyInit(candidate, window, tmp_path / "v2")
    )
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    return strategy, candidate, flows, window, tmp_path


def test_SRT_13_C01_continuous_uses_all_calculation_sessions(mode_strategy):
    strategy, _, _, _, _ = mode_strategy
    actual = strategy.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)
    assert tuple(actual.index.date) == strategy._prepared_data.calculation_dates()
    assert len(actual) > 2


def test_SRT_13_C02_window_uses_full_feature_warmup(mode_strategy):
    strategy, _, _, _, _ = mode_strategy
    actual = strategy.inspect_signals(history_mode=SignalHistoryMode.WINDOW)
    assert actual.index.tolist() == [pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02")]
    assert actual.fixture_signal.iloc[0] == pytest.approx(0.8)
    assert actual.target_position.tolist() == [1.0, 1.0]


def test_SRT_13_C03_window_starts_independent_state(mode_strategy):
    strategy, candidate, flows, window, root = mode_strategy
    continuous = strategy.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)
    independent = strategy.inspect_signals(history_mode=SignalHistoryMode.WINDOW)
    assert continuous.loc["2026-09-02", "target_position"] == 0.0
    assert independent.loc["2026-09-02", "target_position"] == 1.0
    fresh = StrategyRuntime(dataflows=flows).create(StrategyInit(candidate, window, root / "fresh"))
    fresh.prepare_data(binding=strategy.input_binding, persist=False)
    pd.testing.assert_frame_equal(fresh.inspect_signals(), independent)


def test_SRT_13_C05_caller_mutation_cannot_modify_other_modes(mode_strategy):
    strategy, _, _, _, _ = mode_strategy
    original = strategy.inspect_signals(history_mode=SignalHistoryMode.WINDOW)
    continuous = strategy.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)
    changed = strategy.inspect_signals(history_mode=SignalHistoryMode.WINDOW)
    changed.loc[:, "target_position"] = 99.0
    pd.testing.assert_frame_equal(strategy.inspect_signals(), original)
    pd.testing.assert_frame_equal(
        strategy.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS), continuous
    )
