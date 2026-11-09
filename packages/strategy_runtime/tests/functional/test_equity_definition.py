"""Formal equity identity and causal decision behavior through public APIs."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pickle

import pandas as pd
import pytest
from dataflows import InstrumentId, MarketId, AssetClass, BarFrequency, TimeInterval
from strategy_runtime import (
    EquityStrategyDefinition,
    EquityStrategyCandidate,
    equity_source_hash,
    ResearchExecutionSpec,
    UsEquitySpec,
    AccountPolicy,
    CashAvailabilityPolicy,
    EquityPortfolio,
    EquityClosedCycle,
    EquityClosedCycleFeedback,
    EquityDecisionContext,
    DecisionPoint,
)


def candidate(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "rules.py").write_text("THRESHOLD = 10\n", encoding="utf-8")
    (root / "strategy.py").write_text(
        "from .rules import THRESHOLD\nfrom strategy_runtime import EquityDecision\n"
        "counter = 0\ndef decide(ctx):\n global counter\n counter += 1\n"
        ' return EquityDecision.from_facts(int(ctx.history.Close.iloc[-1] >= ctx.parameters["threshold"] and counter == 1), '
        '"threshold decision", facts={"close": ctx.history.Close.iloc[-1], "threshold": ctx.parameters["threshold"]}, next_watch="next bar")\n',
        encoding="utf-8",
    )
    spec = ResearchExecutionSpec(
        UsEquitySpec(),
        BarFrequency.M30,
        AccountPolicy("USD", CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        1,
        0.01,
        0.01,
        0.0,
    )
    files = ("rules.py", "strategy.py")
    definition = EquityStrategyDefinition(
        InstrumentId(MarketId.US, AssetClass.STOCK, "LITE"),
        spec,
        1,
        "strategy:decide",
        files,
        equity_source_hash(root, files),
        '{"threshold":10}',
        analysis_price="RAW",
    )
    return EquityStrategyCandidate("S999", "C0001", definition, root)


def closed_cycle():
    entry = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    return EquityClosedCycle(
        "cycle-1",
        TimeInterval(entry, entry + timedelta(minutes=30)),
        TimeInterval(entry + timedelta(hours=1), entry + timedelta(hours=1, minutes=30)),
        10,
        100.1,
        entry + timedelta(hours=1),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cycle_id", ""),
        ("entry_quantity", True),
        ("entry_quantity", 0),
        ("entry_quantity", 1.5),
        ("entry_cost", float("nan")),
        ("entry_cost", 0.0),
        ("entry_interval", {}),
        ("exit_observed_through", datetime(2026, 10, 1, 15)),
        ("exit_observed_through", datetime(2026, 10, 1, 14, 29, tzinfo=timezone.utc)),
        ("exit_observed_through", datetime(2026, 10, 1, 15, 1, tzinfo=timezone.utc)),
    ],
    ids=[
        "SRT-31-C02",
        "SRT-31-C03",
        "SRT-31-C04",
        "SRT-31-C05",
        "SRT-31-C06",
        "SRT-31-C07",
        "SRT-31-C08",
        "SRT-31-C09",
        "SRT-31-C10",
        "SRT-31-C11",
    ],
)
def test_closed_cycle_rejects_invalid_execution_facts(field, value):
    with pytest.raises((ValueError, TypeError)):
        replace(closed_cycle(), **{field: value})


def test_SRT_31_C01_closed_cycle_feedback_typed_states_and_portable_boundary():
    closed = closed_cycle()
    boundary = replace(closed, exit_observed_through=closed.entry_interval.end)
    assert boundary.exit_observed_through == closed.entry_interval.end
    local = replace(
        closed,
        exit_observed_through=closed.exit_observed_through.astimezone(timezone(timedelta(hours=8))),
    )
    assert local == closed
    feedback = EquityClosedCycleFeedback(closed)
    portfolio = EquityPortfolio(110.0, 0, 0.0, 2, closed_cycle_feedback=feedback)
    assert pickle.loads(pickle.dumps(portfolio)) == portfolio
    assert EquityClosedCycleFeedback().latest is None
    assert EquityPortfolio(100.0, 0, 0.0, 0).closed_cycle_feedback is None
    with pytest.raises(TypeError, match="typed latest"):
        EquityClosedCycleFeedback({"cycle_id": "not-a-cycle"})
    with pytest.raises(TypeError, match="typed closed"):
        replace(portfolio, closed_cycle_feedback={})


def feedback_candidate(root, mode):
    value = candidate(root)
    (root / "strategy.py").write_text(
        "from strategy_runtime import EquityDecision\n"
        "def decide(ctx):\n"
        "    p = ctx.portfolio\n"
        "    f = None if p is None else p.closed_cycle_feedback\n"
        '    state = "market" if p is None else "unavailable" if f is None else '
        '"empty" if f.latest is None else f.latest.cycle_id\n'
        '    return EquityDecision.from_facts(0, state, facts={"state":state}, next_watch="next bar")\n',
        encoding="utf-8",
    )
    return replace(
        value,
        definition=replace(
            value.definition,
            feedback_mode=mode,
            source_sha256=equity_source_hash(root, value.definition.source_files),
        ),
    )


@pytest.mark.parametrize(
    "violation",
    [
        "exit-in-future",
        "observation-in-future",
        "overlapping-current-cycle",
    ],
    ids=["SRT-31-C15", "SRT-31-C16", "SRT-31-C17"],
)
def test_closed_cycle_mode_rejects_noncausal_feedback(tmp_path, violation):
    value = feedback_candidate(tmp_path, "CONFIRMED_CLOSED_CYCLE_V1")
    closed = closed_cycle()
    now = closed.exit_interval.end
    observed = now
    portfolio = EquityPortfolio(
        100.0, 0, 0.0, 2, closed_cycle_feedback=EquityClosedCycleFeedback(closed)
    )
    if violation == "exit-in-future":
        now -= timedelta(minutes=1)
        observed = now
    elif violation == "observation-in-future":
        observed = closed.exit_observed_through - timedelta(minutes=1)
    else:
        portfolio = replace(
            portfolio, quantity=1, cycle_entry=closed.exit_interval.start, cycle_cost=10.0
        )
    point = DecisionPoint(observed, now, TimeInterval(now, now + timedelta(minutes=30)))
    context = EquityDecisionContext(pd.DataFrame(), portfolio, point, value.definition.parameters)
    with pytest.raises(ValueError, match="CAUSAL_TIME_VIOLATION"):
        value.decide(context)


@pytest.mark.parametrize(
    "mode",
    ["CONFIRMED_CLOSED_CYCLE_V1", "MARKET_INTENT", "CONFIRMED_EXECUTION"],
    ids=["SRT-31-C12", "SRT-31-C13", "SRT-31-C14"],
)
def test_closed_cycle_capability_mode_boundary(tmp_path, mode):
    value = feedback_candidate(tmp_path, mode)
    closed = closed_cycle()
    end = closed.exit_interval.end
    point = DecisionPoint(end, end, TimeInterval(end, end + timedelta(minutes=30)))
    portfolio = EquityPortfolio(
        100.0,
        0,
        0.0,
        2,
        closed_cycle_feedback=None
        if mode == "CONFIRMED_CLOSED_CYCLE_V1"
        else EquityClosedCycleFeedback(closed),
    )
    context = EquityDecisionContext(
        pd.DataFrame({"Date": [end], "AvailableDate": [end], "Close": [10.0]}),
        portfolio,
        point,
        value.definition.parameters,
    )
    if mode == "CONFIRMED_CLOSED_CYCLE_V1":
        with pytest.raises(ValueError, match="CLOSED_CYCLE_FEEDBACK_UNAVAILABLE"):
            value.decide(context)
    else:
        assert value.decide(context).reason == (
            "market" if mode == "MARKET_INTENT" else "unavailable"
        )
        assert (
            value.content_identity
            != replace(
                value,
                definition=replace(value.definition, feedback_mode="CONFIRMED_CLOSED_CYCLE_V1"),
            ).content_identity
        )
