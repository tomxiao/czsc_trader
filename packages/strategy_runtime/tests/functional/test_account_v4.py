"""V4 computation/clock parity and actual position execution, using synthetic facts."""

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json

import pandas as pd
import pytest
from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, TradingSession, TimeInterval
from strategy_runtime import EquityStrategyDefinition, StrategyComputation
from strategy_runtime.equity_replay import PreparedObservations
from execution_channels.historical import PortfolioHistoricalExecutor
from czsc_trader.application.account_replay import run_replay
from czsc_trader.application.ec_boundary import execution_spec


from packages.strategy_runtime.tests.v4_fixture_support import setup


@pytest.mark.parametrize(
    "mode",
    [
        "MARKET_INTENT",
    ],
    ids=["SRT-03-C08"],
)
def test_account_replay_rejects_retired_feedback_contract(tmp_path, mode):
    candidate, _, _, _, _, _, _ = setup(
        tmp_path, MarketId.US, BarFrequency.M30, StrategyComputation.STATEFUL_STEP
    )
    with pytest.raises(ValueError, match="requires CONFIRMED_EXECUTION feedback"):
        replace(candidate.definition, feedback_mode=mode)


EXPLICIT = """from strategy_runtime import AccountDecision,AccountStepResult
from strategy_runtime.equity_replay import StateRecord
def step(ctx,state):
    target=(.02,.015,0.)[min(ctx.portfolio.revision,2)]
    feedback=ctx.position.active or ctx.position.latest_closed
    facts={'buys':feedback.buy_fills if feedback else 0,'sells':feedback.sell_fills if feedback else 0}
    return AccountStepResult(AccountDecision.from_facts(target,'position ladder',facts=facts,next_watch='next bar'),cycle_values=StateRecord())
"""


@pytest.mark.parametrize(
    "computation",
    [
        StrategyComputation.STATEFUL_STEP,
    ],
    ids=["SRT-14-C05"],
)
def test_future_suffix_does_not_change_prefix_accounts(tmp_path, computation):
    c, p, e, b, r, sessions, frame = setup(
        tmp_path / "first", MarketId.US, BarFrequency.M30, computation
    )
    end = b.Date.iloc[-1].to_pydatetime()
    first = run_replay(
        p, c, e, constraints=r, start=b.BarStart.iloc[1].to_pydatetime(), end=end, fee_rate=0.001
    ).execution_result
    altered = b.copy()
    altered.loc[8:, ["Open", "High", "Low", "Close"]] *= 10
    current = PreparedObservations.from_frames(
        altered,
        c.definition.feature_graph,
        frequency=BarFrequency.M30,
        timezone=c.instrument.timezone,
        sessions=frame,
        trading_sessions=sessions,
    )
    second = run_replay(
        current,
        c,
        PortfolioHistoricalExecutor(
            specification=execution_spec(c.definition.execution_spec),
            initial_cash=100000.0,
            fee_rate=0.001,
            price_basis="HFQ",
        ),
        constraints=r,
        start=b.BarStart.iloc[1].to_pydatetime(),
        end=end,
        fee_rate=0.001,
    ).execution_result
    for key in ("cash", "quantity", "equity"):
        assert (
            first.account_points[key].iloc[:7].tolist()
            == second.account_points[key].iloc[:7].tolist()
        )
    assert (
        first.decisions.explanation.iloc[:7].tolist()
        == second.decisions.explanation.iloc[:7].tolist()
    )


def test_SRT_08_C06_v4_rejects_mismatched_prepared_frequency(tmp_path):
    c, p, e, b, constraints, _, _ = setup(
        tmp_path, MarketId.US, BarFrequency.M30, StrategyComputation.STATEFUL_STEP
    )
    with pytest.raises(ValueError, match="decision clock"):
        run_replay(
            replace(p, frequency=BarFrequency.DAILY),
            c,
            e,
            constraints=constraints,
            start=b.BarStart.iloc[1].to_pydatetime(),
            end=b.Date.iloc[-1].to_pydatetime(),
            fee_rate=0.001,
        )


def test_SRT_09_C05_execution_quote_role_is_typed_and_not_an_auxiliary_alias(tmp_path):
    from dataflows import SourceRef, EquityProduct
    from strategy_runtime import ExecutionInput, EquityAuxiliaryInput

    c, _, _, _, _, _, _ = setup(
        tmp_path, MarketId.CN, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP
    )
    source = SourceRef("synthetic", "v1")
    execution = ExecutionInput(c.instrument, source, BarFrequency.M30)
    definition = replace(c.definition, execution_input=execution)
    assert (
        EquityStrategyDefinition.from_dict(json.loads(json.dumps(definition.to_dict())))
        == definition
    )
    assert execution.data_key(EquityProduct.BARS) == "execution:bars"
    assert {
        x.parameters.query.product for x in execution.requests(date(2024, 3, 4), date(2024, 3, 8))
    } == {EquityProduct.BARS, EquityProduct.SESSIONS}
    aux = EquityAuxiliaryInput("execution_alias", c.instrument, source, BarFrequency.M30, 1, 3600)
    assert replace(definition, auxiliary_inputs=(aux,)).auxiliary_inputs == (aux,)
    with pytest.raises(ValueError, match="DAILY"):
        replace(
            definition,
            execution_spec=replace(definition.execution_spec, decision_clock=BarFrequency.M30),
        )


def test_SRT_27_C02_legacy_definitions_do_not_acquire_v4_fields_or_cn_auxiliary(tmp_path):
    from dataflows import SourceRef
    from strategy_runtime import EquityAuxiliaryInput

    c, _, _, _, _, _, _ = setup(
        tmp_path, MarketId.US, BarFrequency.M30, StrategyComputation.STATEFUL_STEP
    )
    legacy = replace(
        c.definition,
        contract_version=2,
        computation=None,
        feature_graph=None,
        state_schema=None,
        execution_policy=None,
        analysis_price="RAW",
    )
    with pytest.raises(ValueError, match="unsupported equity definition"):
        replace(c.definition, contract_version=3, computation=None, execution_policy=None)
    encoded = legacy.to_dict()
    assert encoded["runtime_kind"] == "US_EQUITY"
    assert "computation" not in encoded and "execution_input" not in encoded
    aux = EquityAuxiliaryInput(
        "cn_market",
        InstrumentId(MarketId.CN, AssetClass.ETF, "588080.SH"),
        SourceRef("synthetic", "v1"),
        BarFrequency.DAILY,
        1,
        86400,
    )
    assert replace(c.definition, auxiliary_inputs=(aux,)).auxiliary_inputs == (aux,)
    with pytest.raises(ValueError, match="legacy auxiliary"):
        replace(legacy, auxiliary_inputs=(aux,))


@pytest.mark.parametrize(
    "market",
    [
        MarketId.CN,
        MarketId.US,
    ],
    ids=["SRT-15-C01", "SRT-15-C02"],
)
def test_calendar_breaks_and_dst_drive_actual_clock_without_filling_closed_time(tmp_path, market):
    c, _, e, old, old_rules, _, _ = setup(
        tmp_path, market, BarFrequency.M30, StrategyComputation.STATEFUL_STEP
    )
    zone = ZoneInfo(c.instrument.timezone)
    if market is MarketId.CN:
        days = (date(2024, 3, 4), date(2024, 3, 5))
        clocks = ((9, 30, 11, 30), (13, 0, 15, 0))
    else:
        days = (date(2024, 3, 8), date(2024, 3, 11))
        clocks = ((9, 30, 11, 30),)
    sessions = tuple(
        TradingSession(
            day,
            str(zone),
            tuple(
                TimeInterval(
                    datetime(day.year, day.month, day.day, a, b, tzinfo=zone),
                    datetime(day.year, day.month, day.day, d, f, tzinfo=zone),
                )
                for a, b, d, f in clocks
            ),
        )
        for day in days
    )
    periods = tuple(interval for session in sessions for interval in session.bars(BarFrequency.M30))
    starts = pd.DatetimeIndex([interval.start for interval in periods]).tz_convert("UTC")
    ends = pd.DatetimeIndex([interval.end for interval in periods]).tz_convert("UTC")
    bars = old.iloc[: len(periods)].copy()
    bars["BarStart"], bars["Date"], bars["AvailableDate"] = starts, ends, ends
    rules = old_rules.iloc[: len(periods)].copy()
    rules["Date"], rules["AvailableDate"], rules["BuySellableAt"] = starts, starts, starts
    calendar = pd.DataFrame(
        {
            "Date": [s.segments[0].start for s in sessions],
            "AvailableDate": [s.segments[0].start for s in sessions],
            "SessionDate": [s.session_date.isoformat() for s in sessions],
        }
    )
    prepared = PreparedObservations.from_frames(
        bars,
        c.definition.feature_graph,
        frequency=BarFrequency.M30,
        timezone=c.instrument.timezone,
        sessions=calendar,
        trading_sessions=sessions,
    )
    # Reset the synthetic NONE timestamp to this independently declared history.
    account = run_replay(
        prepared,
        c,
        PortfolioHistoricalExecutor(
            specification=execution_spec(c.definition.execution_spec),
            initial_cash=100000.0,
            fee_rate=0.001,
            price_basis="HFQ",
        ),
        constraints=rules,
        start=starts[1].to_pydatetime(),
        end=ends[-1].to_pydatetime(),
        fee_rate=0.001,
    ).execution_result
    assert len(account.account_points) == len(periods) - 1
    assert account.account_daily.session.tolist() == [day.isoformat() for day in days]
    if market is MarketId.CN:
        assert not any(
            11 * 60 + 30 <= value.hour * 60 + value.minute < 13 * 60
            for value in starts.tz_convert(zone)
        )
    else:
        assert starts[0].hour == 14 and starts[4].hour == 13


@pytest.mark.parametrize("target", [0.0, 1.0], ids=["SRT-03-C01", "SRT-03-C02"])
def test_v4_accepts_position_target_boundaries(target):
    from strategy_runtime import AccountDecision

    decision = AccountDecision.from_facts(
        target, "position", facts={"target": target}, next_watch="next bar"
    )
    assert decision.target == target and decision.explanation.judgment == "position"


@pytest.mark.parametrize("target", [float("nan"), 1.1], ids=["SRT-03-C03", "SRT-03-C04"])
def test_v4_rejects_invalid_target(target):
    from strategy_runtime import AccountDecision

    with pytest.raises(ValueError):
        AccountDecision.from_facts(target, "position", facts={}, next_watch="next")


@pytest.mark.parametrize(
    "field", ["price", "quantity", "cash"], ids=["SRT-03-C05", "SRT-03-C06", "SRT-03-C07"]
)
def test_position_decision_has_no_execution_amounts(field):
    from strategy_runtime import AccountDecision

    with pytest.raises(TypeError):
        AccountDecision.from_facts(0.5, "position", facts={}, next_watch="next", **{field: 1})


@pytest.mark.parametrize(
    "defect", ["batch_state", "policy", "raw"], ids=["SRT-03-C09", "SRT-03-C10", "SRT-03-C11"]
)
def test_v4_definition_rejects_ambiguous_responsibility(tmp_path, defect):
    from strategy_runtime import StrategyStateSchema, StateField, StateValueType

    c, *_ = setup(
        tmp_path,
        MarketId.US,
        BarFrequency.DAILY,
        StrategyComputation.STATEFUL_STEP,
        with_executor=False,
    )
    changes = (
        {
            "computation": StrategyComputation.BATCH_HISTORY,
            "state_schema": StrategyStateSchema((StateField("counter", StateValueType.INT),)),
        }
        if defect == "batch_state"
        else {"execution_policy": None}
        if defect == "policy"
        else {"analysis_price": "RAW"}
    )
    with pytest.raises(TypeError if defect == "policy" else ValueError):
        replace(c.definition, **changes)
