"""Public planning checks for strategy-owned observation-only history columns."""

from datetime import date, datetime
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

import pytest
from dataflows import PreparePolicy

from strategy_runtime import (
    ExecutionState, PortfolioSnapshot, RuntimeContractError, SignalHistoryMode,
    StrategyCandidate, StrategyInit, StrategyRuntime, TradableWindow, TradingPoint,
    implementation_sha256, materialize_observation,
)
from test_public_runtime import _flows


def observed_candidate(candidate, body, *, invalid_trade=False):
    path = candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8")
    source += '''
from dataclasses import replace
from strategy_runtime import StrategyImplementationV2, SignalGroup, SignalSeriesDefinition, SignalPanelDefinition

class ObservedFixture(CandidateFixture, StrategyImplementationV2):
    def __init__(self, parameters):
        super().__init__(parameters)
        panel = SignalPanelDefinition(
            (SignalGroup("condition", "Condition", "ratio", "fixture"),),
            (SignalSeriesDefinition("signal", "Observed signal", "condition", "obs_signal"),),
        )
        self._definition = replace(self._definition, observation=replace(self._definition.observation, signal_panel=panel))

    def calculate_context_history(self, inputs, context):
        return super().calculate_history(inputs, context.sessions)

    def observation_history(self, inputs, context, history):
'''
    source += "\n".join("        " + line for line in body.splitlines()) + "\n"
    if invalid_trade:
        source = source.replace(
            "return super().calculate_history(inputs, context.sessions)",
            "return super().calculate_history(inputs, context.sessions).assign(target_position=2.0)",
        )
    path.write_text(source, encoding="utf-8", newline="\n")
    payload = json.loads(json.dumps(dict(candidate.payload), default=dict))
    payload["runtime"].update(
        qualname="ObservedFixture", contract_version=2,
        source_sha256=implementation_sha256(tuple(payload["runtime"]["source_files"]), source_root=candidate.source_root),
    )
    return StrategyCandidate(candidate.strategy_family_id, candidate.candidate_id, payload, candidate.source_root)


def ready_instance(tmp_path, candidate):
    day = date(2026, 9, 3)
    runtime = StrategyRuntime(dataflows=_flows(tmp_path / "flows"))
    instance = runtime.create(StrategyInit(candidate, TradableWindow(day, day), tmp_path / "runtime"))
    instance.prepare_data(policy=PreparePolicy.REUSE)
    return instance


def plan(instance, mode):
    now = datetime(2026, 9, 2, 22, tzinfo=ZoneInfo("Asia/Shanghai"))
    return instance.plan_at(
        point=TradingPoint(date(2026, 9, 3), now),
        portfolio=PortfolioSnapshot("fixture", "588080.SH", Decimal("100000"), Decimal("100000"), 0, 0, now),
        state=ExecutionState(0, now), history_mode=mode,
    )


def test_observation_history_mutations_are_isolated_from_trading_and_prepared_inputs(tmp_path, runtime_candidate):
    candidate = observed_candidate(runtime_candidate, '''signal = history["fixture_signal"].copy()
history["target_position"] = 0.0
inputs["flow"]["Flow"] = -999.0
return pd.DataFrame({"obs_signal": signal}, index=history.index)''')
    instance = ready_instance(tmp_path, candidate)
    for mode in SignalHistoryMode:
        result = plan(instance, mode)
        history = instance.inspect_signals(history_mode=mode)
        assert result.target_position == 1.0 and result.target_quantity > 0
        assert history["target_position"].eq(1).all()
        assert history["fixture_signal"].eq(1).all() and history["obs_signal"].eq(1).all()
        observation = materialize_observation(instance.definition, result)
        assert observation.signal_panel.series[0].value == 1.0
        assert observation.series[0].value == 1.0
        assert result.evidence["action"] == "BUY"
    # A second mode recalculates from the authenticated input, not the observer's mutations.
    assert plan(instance, SignalHistoryMode.WINDOW).target_position == 1.0


@pytest.mark.parametrize("body,match", [
    ('return pd.DataFrame({"obs_undeclared": 1.0}, index=history.index)', "declared obs_"),
    ('return pd.DataFrame({"target_position": 0.0}, index=history.index)', "declared obs_"),
    ('return pd.DataFrame({"obs_signal": 1.0}, index=history.index + pd.Timedelta(days=1))', "preserve trading sessions"),
    ('return pd.DataFrame([[1.0, 2.0]] * len(history), index=history.index, columns=["obs_signal", "obs_signal"])', "preserve trading sessions"),
    ('return pd.DataFrame({"obs_signal": [[1.0]] * len(history)}, index=history.index)', "scalar values"),
    ('return pd.DataFrame({"obs_signal": float("inf")}, index=history.index)', "finite values"),
    ('raise ValueError("observer failed")', "observer failed"),
])
def test_observation_history_cannot_change_contract_fields_or_session_alignment(tmp_path, runtime_candidate, body, match):
    instance = ready_instance(tmp_path, observed_candidate(runtime_candidate, body))
    result = plan(instance, SignalHistoryMode.CONTINUOUS)
    assert result.target_position == 1.0 and result.target_quantity > 0
    assert result.evidence["action"] == "BUY"
    assert match in result.evidence["_observation_error"]
    assert not any(name.startswith("obs_") for name in result.evidence)
    with pytest.raises(RuntimeContractError, match="signal panel calculation unavailable"):
        materialize_observation(instance.definition, result)


def test_invalid_trading_history_still_blocks_planning_before_observation_is_run(tmp_path, runtime_candidate):
    candidate = observed_candidate(runtime_candidate, 'raise ValueError("observer must not run")', invalid_trade=True)
    instance = ready_instance(tmp_path, candidate)
    with pytest.raises(RuntimeContractError, match="history contains invalid target positions"):
        plan(instance, SignalHistoryMode.CONTINUOUS)
