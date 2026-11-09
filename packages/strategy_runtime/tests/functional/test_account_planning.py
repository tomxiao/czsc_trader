"""SRT-22/23: decisions consume confirmed typed facts; EC ledger math is elsewhere."""

from dataclasses import replace
from datetime import datetime, timezone
import json
import pytest
from dataflows import BarFrequency, MarketId, TimeInterval
from strategy_runtime import (
    AccountDecisionEngine,
    AccountStrategyState,
    AccountSnapshot,
    EquityPortfolio,
    CycleState,
    PositionFeedback,
    StateRecord,
    StrategyComputation,
    PreparedObservations,
    RecognizedAccountEvent,
    RecognizedEventKind,
    equity_source_hash,
    check_account_batch_consistency,
)
from packages.strategy_runtime.tests.v4_fixture_support import setup


def facts(candidate, prepared, index=1):
    interval = TimeInterval(prepared._data.starts[index], prepared._data.ends[index])
    portfolio = EquityPortfolio(100000.0, 0, 0.0, 0)
    account = AccountSnapshot(
        candidate.instrument,
        candidate.definition.execution_spec.account.currency,
        interval.start,
        0,
        100000.0,
        100000.0,
        0.0,
        0,
        0,
    )
    return interval, portfolio, account


@pytest.mark.parametrize(
    "market,frequency,computation",
    [
        (MarketId.CN, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP),
        (MarketId.US, BarFrequency.M30, StrategyComputation.BATCH_HISTORY),
    ],
    ids=["SRT-23-C01", "SRT-23-C02"],
)
def test_independent_decision_calls_preserve_targets_and_caller_state(
    tmp_path, market, frequency, computation
):
    c, p, _, bars, _, _, _ = setup(tmp_path, market, frequency, computation, with_executor=False)
    state = AccountStrategyState()
    actual = []
    for index in range(1, len(bars)):
        engine = AccountDecisionEngine(c, p)
        state = AccountStrategyState.from_dict(json.loads(json.dumps(state.to_dict())))
        interval, portfolio, account = facts(c, p, index)
        before = state.to_dict()
        result = engine.propose(
            interval,
            portfolio,
            account,
            state,
            PositionFeedback(),
            owner="durable-account",
            fee_rate=0.001,
        )
        assert state.to_dict() == before
        actual.append(result.proposal.decision.target)
        assert not hasattr(result.proposal.decision, "orders")
        state = AccountStrategyState(
            0,
            result.proposal.account,
            None,
            engine.state_binding("durable-account", 0.001),
            result.next_event_cursor,
        )
    assert actual == [(0.25, 0.5, 0.25, 0.0)[int(value - 10) % 4] for value in bars.Close.iloc[:-1]]


@pytest.mark.parametrize(
    "wrong_owner",
    [
        False,
        True,
    ],
    ids=["SRT-22-C04", "SRT-22-C03"],
)
def test_state_binding_tracks_account_not_prepared_history(tmp_path, wrong_owner):
    c, p, _, bars, _, sessions, session_frame = setup(
        tmp_path,
        MarketId.US,
        BarFrequency.DAILY,
        StrategyComputation.STATEFUL_STEP,
        with_executor=False,
    )
    short = PreparedObservations.from_frames(
        bars.iloc[:3],
        c.definition.feature_graph,
        frequency=BarFrequency.DAILY,
        timezone=c.instrument.timezone,
        sessions=session_frame.iloc[:3],
        trading_sessions=sessions[:3],
    )
    first, second = AccountDecisionEngine(c, short), AccountDecisionEngine(c, p)
    assert short.identity != p.identity
    assert first.state_binding("account", 0.001) == second.state_binding("account", 0.001)
    interval, portfolio, account = facts(c, p)
    state = AccountStrategyState(
        binding=first.state_binding("other" if wrong_owner else "account", 0.001)
    )
    if wrong_owner:
        with pytest.raises(ValueError, match="another account"):
            second.propose(
                interval,
                portfolio,
                account,
                state,
                PositionFeedback(),
                owner="account",
                fee_rate=0.001,
            )
    else:
        second.propose(
            interval, portfolio, account, state, PositionFeedback(), owner="account", fee_rate=0.001
        )


@pytest.mark.parametrize(
    "fault",
    [
        "future_event",
        "cursor",
    ],
    ids=["SRT-22-C05", "SRT-22-C06"],
)
def test_proposal_rejects_unconfirmed_future_or_regressing_event_cursor(tmp_path, fault):
    c, p, *_ = setup(
        tmp_path,
        MarketId.US,
        BarFrequency.DAILY,
        StrategyComputation.STATEFUL_STEP,
        with_executor=False,
    )
    interval, portfolio, account = facts(c, p, 2)
    if fault == "future_event":
        event = RecognizedAccountEvent(
            "future", RecognizedEventKind.POSITION_ADJUSTMENT, interval.end, 0, 0, 1.0, 0.0
        )
        state = AccountStrategyState()
        kwargs = dict(events=(event,))
    else:
        state = AccountStrategyState(event_cursor=2)
        kwargs = dict(next_event_cursor=1)
    with pytest.raises(ValueError, match="future facts" if fault == "future_event" else "cursor"):
        AccountDecisionEngine(c, p).propose(
            interval,
            portfolio,
            account,
            state,
            PositionFeedback(),
            owner="account",
            fee_rate=0.001,
            **kwargs,
        )


def test_SRT_22_C01_state_roundtrip_preserves_types_and_cursor():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state = AccountStrategyState(
        3,
        StateRecord((("flag", False), ("anchor", stamp))),
        CycleState("cycle", stamp, StateRecord((("entry", 12.0),))),
        "identity",
        7,
    )
    value = json.loads(json.dumps(state.to_dict()))
    assert AccountStrategyState.from_dict(value) == state
    del value["event_cursor"]
    with pytest.raises(ValueError, match="unsupported account strategy state"):
        AccountStrategyState.from_dict(value)


def test_SRT_22_C07_propose_does_not_commit_caller_owned_state(tmp_path):
    c, p, *_ = setup(
        tmp_path,
        MarketId.CN,
        BarFrequency.DAILY,
        StrategyComputation.STATEFUL_STEP,
        with_executor=False,
    )
    interval, portfolio, account = facts(c, p)
    state = AccountStrategyState()
    before = state.to_dict()
    proposal = AccountDecisionEngine(c, p).propose(
        interval, portfolio, account, state, PositionFeedback(), owner="account", fee_rate=0.001
    )
    assert proposal.proposal.decision.target == 0.25
    assert state.to_dict() == before and state.binding is None
    assert account.quantity == 0 and portfolio.quantity == 0


def test_SRT_23_C03_batch_requires_one_decision_per_observation(tmp_path):
    c, p, *_ = setup(
        tmp_path,
        MarketId.US,
        BarFrequency.M30,
        StrategyComputation.BATCH_HISTORY,
        with_executor=False,
    )
    (tmp_path / "strategy.py").write_text("def calculate(ctx):\n    return ()\n", encoding="utf-8")
    c = replace(
        c,
        definition=replace(
            c.definition, source_sha256=equity_source_hash(tmp_path, ("strategy.py",))
        ),
    )
    interval, portfolio, account = facts(c, p)
    with pytest.raises(TypeError, match="one AccountDecision per observation"):
        AccountDecisionEngine(c, p).propose(
            interval,
            portfolio,
            account,
            AccountStrategyState(),
            PositionFeedback(),
            owner="account",
            fee_rate=0.001,
        )


@pytest.mark.parametrize(
    "cross_observation",
    [
        True,
    ],
    ids=["SRT-23-C04"],
)
def test_batch_consistency_reports_exact_differing_points(tmp_path, cross_observation):
    c, p, _, bars, _, _, _ = setup(
        tmp_path,
        MarketId.US,
        BarFrequency.M30,
        StrategyComputation.BATCH_HISTORY,
        with_executor=False,
    )
    if cross_observation:
        (tmp_path / "strategy.py").write_text(
            """from strategy_runtime import AccountDecision
def calculate(ctx):
    return tuple(AccountDecision.from_facts(float(index%2),"sequence-dependent",
        facts={"index":index},next_watch="next") for index,row in enumerate(ctx.observations))
""",
            encoding="utf-8",
        )
        c = replace(
            c,
            definition=replace(
                c.definition, source_sha256=equity_source_hash(tmp_path, ("strategy.py",))
            ),
        )
    result = check_account_batch_consistency(
        c, p, start=bars.BarStart.iloc[1].to_pydatetime(), end=bars.Date.iloc[-1].to_pydatetime()
    )
    assert result.checked_points == len(bars) - 1
    assert result.consistent is (not cross_observation)
    if cross_observation:
        assert result.differing_points == tuple(
            stamp.to_pydatetime() for stamp in bars.BarStart.iloc[2:]
        )


def test_SRT_22_C02_nonempty_account_schema_requires_initial_values(tmp_path):
    from strategy_runtime import StrategyStateSchema, StateField, StateValueType

    c, *_ = setup(
        tmp_path,
        MarketId.US,
        BarFrequency.DAILY,
        StrategyComputation.STATEFUL_STEP,
        with_executor=False,
    )
    with pytest.raises(ValueError, match="state"):
        replace(
            c.definition,
            state_schema=StrategyStateSchema((StateField("counter", StateValueType.INT),)),
        )


@pytest.mark.parametrize(
    "scenario",
    ["fills", "unfilled", "adjustment", "suppressed"],
    ids=["SRT-24-C01", "SRT-24-C02", "SRT-24-C03", "SRT-24-C04"],
)
def test_confirmed_feedback_is_the_only_account_input(tmp_path, scenario):
    from strategy_runtime import PositionCycle

    c, p, _, bars, _, sessions, session_frame = setup(
        tmp_path,
        MarketId.US,
        BarFrequency.DAILY,
        StrategyComputation.STATEFUL_STEP,
        with_executor=False,
    )
    source = """from strategy_runtime import AccountDecision,AccountStepResult,StateRecord
def step(ctx,state):
    cycle=ctx.position.active
    event=ctx.events[0] if ctx.events else None
    values={'cost':cycle.buy_cost if cycle else 0.,'fees':cycle.fees if cycle else 0.,'buys':cycle.buy_fills if cycle else 0,'active':cycle is not None,'reason':event.reason if event else 'NONE','before':event.quantity_before if event else 0,'after':event.quantity_after if event else 0}
    return AccountStepResult(AccountDecision.from_facts(0.,'confirmed',facts=values,next_watch='next'),state.account,StateRecord())
"""
    (tmp_path / "strategy.py").write_text(source, encoding="utf8")
    c = replace(
        c,
        definition=replace(
            c.definition, source_sha256=equity_source_hash(tmp_path, ("strategy.py",))
        ),
    )
    interval, portfolio, account = facts(c, p, 2)
    state = AccountStrategyState()
    position = PositionFeedback()
    events = ()
    if scenario == "fills":
        entry = TimeInterval(p._data.starts[0], p._data.ends[0])
        last = TimeInterval(p._data.starts[1], p._data.ends[1])
        position = PositionFeedback(PositionCycle("cycle", entry, last, 3, 30.3, 0.0, 0.3, 2, 0))
        portfolio = EquityPortfolio(100000.0, 3, 0.0, 0, cycle_entry=entry.start, cycle_cost=30.3)
        state = AccountStrategyState(cycle=CycleState("cycle", entry.start, StateRecord()))
        account = replace(account, quantity=3, sellable_quantity=3)
    elif scenario in {"adjustment", "suppressed"}:
        events = (
            RecognizedAccountEvent(
                "external", RecognizedEventKind.POSITION_ADJUSTMENT, interval.start, 0, 0, 1.0, 0.0
            ),
        )
        if scenario == "suppressed":
            changed = bars.copy()
            changed["BarStatus"] = "OBSERVED"
            changed.loc[1, "BarStatus"] = "ZERO_VOLUME"
            changed.loc[1, "Volume"] = 0.0
            p = PreparedObservations.from_frames(
                changed,
                c.definition.feature_graph,
                frequency=BarFrequency.DAILY,
                timezone=c.instrument.timezone,
                sessions=session_frame,
                trading_sessions=sessions,
            )
    result = AccountDecisionEngine(c, p).propose(
        interval, portfolio, account, state, position, owner="test", fee_rate=0.001, events=events
    )
    if scenario == "suppressed":
        assert result.suppressed and result.next_event_cursor == state.event_cursor
    else:
        values = {item.key: item.text for item in result.proposal.decision.explanation.basis}
        if scenario == "fills":
            assert values["cost"] == "30.3" and values["fees"] == "0.3" and values["buys"] == "2"
        elif scenario == "unfilled":
            assert values["active"] == "False" and state.cycle is None
        else:
            assert values["reason"] == "UNKNOWN" and values["before"] == values["after"] == "0"
            assert result.next_event_cursor == 1
