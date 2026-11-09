"""Public planning checks for strategy-owned observation-only history columns."""

from datetime import date, datetime
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

import pandas as pd
from czsc_trader.application.ec_boundary import session_execution_plan
from execution_channels.serialization import from_record, to_record
from execution_channels.session_contracts import (
    PortfolioSnapshot as ChannelPortfolio,
    ExecutionState as ChannelState,
)
from dataflows import (
    PreparePolicy,
    DataRequest,
    DataResult,
    DataIdentity,
    DataStatus,
    Dataset,
    canonical_frame_sha256,
)

from strategy_runtime import (
    ExecutionState,
    PortfolioSnapshot,
    SignalHistoryMode,
    StrategyCandidate,
    StrategyInit,
    StrategyRuntime,
    TradableWindow,
    TradingPoint,
    implementation_sha256,
)
from strategy_runtime.observation import observe_strategy_proposal
from strategy_runtime.data import PreparedStrategyData
from strategy_runtime.models import ExecutionPricingData
from strategy_runtime.preparation import PreparedInputs, prepared_inputs_identity
from packages.strategy_runtime.tests.session_runtime_support import _flows


def observed_candidate(candidate, body, *, invalid_trade=False):
    path = candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8")
    source += """
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
"""
    source += "\n".join("        " + line for line in body.splitlines()) + "\n"
    if invalid_trade:
        source = source.replace(
            "return super().calculate_history(inputs, context.sessions)",
            "return super().calculate_history(inputs, context.sessions).assign(target_position=2.0)",
        )
    path.write_text(source, encoding="utf-8", newline="\n")
    payload = json.loads(json.dumps(dict(candidate.payload), default=dict))
    payload["runtime"].update(
        qualname="ObservedFixture",
        contract_version=2,
        source_sha256=implementation_sha256(
            tuple(payload["runtime"]["source_files"]), source_root=candidate.source_root
        ),
    )
    return StrategyCandidate(
        candidate.strategy_family_id, candidate.candidate_id, payload, candidate.source_root
    )


def ready_instance(tmp_path, candidate):
    day = date(2026, 9, 3)
    runtime = StrategyRuntime(dataflows=_flows(tmp_path / "flows"))
    instance = runtime.create(
        StrategyInit(candidate, TradableWindow(day, day), tmp_path / "runtime")
    )
    instance.prepare_data(policy=PreparePolicy.REUSE)
    return instance


def observation_instance(tmp_path, candidate):
    """Actual runtime and typed admitted facts; observation validation has no DFLS I/O."""
    day, signal_day = date(2026, 9, 3), date(2026, 9, 2)
    window = TradableWindow(day, day)
    instance = StrategyRuntime().create(StrategyInit(candidate, window, tmp_path / "runtime"))
    frame = pd.DataFrame({"Date": pd.to_datetime([signal_day]), "Flow": [1.0]})
    request = DataRequest(
        Dataset.ETF_SHARE_SIZE,
        "588080.SH",
        signal_day.isoformat(),
        signal_day.isoformat(),
        signal_day.isoformat(),
    )
    identity = DataIdentity(
        str(request.dataset),
        "synthetic",
        request.symbol,
        signal_day.isoformat(),
        signal_day.isoformat(),
        canonical_frame_sha256(frame),
        {
            "source_time_field": "Date",
            "availability_time_field": "Date",
            "source_calendar": "SSE",
            "available_at": "SESSION_CLOSE",
            "request_range_policy": "EXACT",
        },
    )
    results = {"flow": DataResult(DataStatus.READY, frame, identity)}
    signal_dates = {day: signal_day}
    inputs = PreparedInputs(
        instance.identity,
        window,
        signal_day,
        prepared_inputs_identity(
            strategy=instance.identity,
            tradable_window=window,
            available_through=signal_day,
            signal_dates=signal_dates,
            results=results,
        ),
        {"flow": request},
        results,
        (signal_day, day),
        signal_dates,
        (signal_day,),
    )
    prices = pd.DataFrame({"Date": pd.to_datetime([signal_day]), "Close": [10.0]})
    instance._prepared_data = PreparedStrategyData.from_inputs(
        inputs=inputs, pricing=ExecutionPricingData(instance.identity.symbol, prices, prices)
    )
    return instance


def plan(instance, mode):
    now = datetime(2026, 9, 2, 22, tzinfo=ZoneInfo("Asia/Shanghai"))
    return session_execution_plan(
        instance.propose_at(point=TradingPoint(date(2026, 9, 3), now), history_mode=mode),
        from_record(
            ChannelPortfolio,
            to_record(
                PortfolioSnapshot(
                    "fixture", "588080.SH", Decimal("100000"), Decimal("100000"), 0, 0, now
                )
            ),
        ),
        from_record(ChannelState, to_record(ExecutionState(0, now))),
    )


def observe(instance, mode, result):
    point = TradingPoint(result.trading_date, result.generated_at)
    proposal = instance.propose_at(point=point, history_mode=mode)
    return observe_strategy_proposal(
        instance.definition, proposal, plan_identity=result.plan_identity, action=result.action
    )


def test_SRT_26_C03_observation_history_mutations_are_isolated_from_trading_and_prepared_inputs(
    tmp_path, runtime_candidate
):
    candidate = observed_candidate(
        runtime_candidate,
        """signal = history["fixture_signal"].copy()
history["target_position"] = 0.0
inputs["flow"]["Flow"] = -999.0
return pd.DataFrame({"obs_signal": signal}, index=history.index)""",
    )
    instance = ready_instance(tmp_path, candidate)
    for mode in SignalHistoryMode:
        result = plan(instance, mode)
        history = instance.inspect_signals(history_mode=mode)
        assert result.target_position == 1.0 and result.target_quantity > 0
        assert history["target_position"].eq(1).all()
        assert history["fixture_signal"].eq(1).all() and history["obs_signal"].eq(1).all()
        observation = observe(instance, mode, result)
        assert observation.signal_panel.series[0].value == 1.0
        assert observation.series[0].value == 1.0
        assert result.evidence["action"] == "BUY"
    # A second mode recalculates from the authenticated input, not the observer's mutations.
    assert plan(instance, SignalHistoryMode.WINDOW).target_position == 1.0
