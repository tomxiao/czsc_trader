# Risk ownership: TDR-28 E2E-07
"""Explicit seed-only periods never fabricate or fetch inactive dynamic inputs."""

from test_v4_inspection_roundtrip import prepare_raw_reference
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataset, MarketId, ProviderBinding, EquityProduct, TimeInterval, DataIdentity
from strategy_runtime import (
    DatasetObservationInput,
    DatasetObservationBinding,
    ObservationAvailability,
    TableObservationStatus,
    PreparedObservationTable,
    equity_source_hash,
)
from strategy_runtime.observation_preparation import resolve_observation_requests
from czsc_trader.research_tools import ResearchExecutionSession
from paper_trading_engine.equity_advice import prepare_equity_decision
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4Inputs
from adjusted_observation_support import setup_adjusted


def fixture(tmp_path, market, *, start=date(2026, 10, 14), missing=False):
    context, request, products, _, _ = setup_adjusted(tmp_path, market)
    declaration = DatasetObservationInput(
        "increment",
        Dataset.SHIBOR_DAILY,
        history_start=date(2026, 10, 11),
        availability=ObservationAvailability(request.candidate.instrument.timezone, "17:00"),
        required_from=start,
    )
    root = request.candidate.source_root
    (root / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision, AccountStepResult, StateRecord, TableObservationStatus\n"
        "def step(ctx, state):\n"
        '    view = ctx.observations["increment"]\n'
        "    active = view.status is TableObservationStatus.ACTIVE\n"
        "    assert bool(view.rows) == active\n"
        '    return AccountStepResult(AccountDecision.from_facts(int(active), "activation", '
        'facts={"status":view.status.value}, next_watch="next source day"), cycle_values=StateRecord())\n',
        encoding="utf-8",
    )
    candidate = replace(
        request.candidate,
        definition=replace(
            request.candidate.definition,
            source_sha256=equity_source_hash(root, ("strategy.py",)),
            observation_inputs=(declaration,),
        ),
    )
    calls = []

    def fetch(query):
        calls.append(query)
        days = pd.DatetimeIndex([]) if missing else pd.date_range(query.start, query.end)
        return pd.DataFrame({"Date": days, "OvernightRate": [2.0] * len(days)}), {
            "primary_key": ["Date"]
        }

    context.data._providers[Dataset.SHIBOR_DAILY.value] = ProviderBinding("increment", "v1", fetch)
    return context, replace(request, candidate=candidate), products, calls


@pytest.mark.parametrize("market", [MarketId.US])
@pytest.mark.parametrize("missing", [True])
def test_forward_recipe_transitions_from_inactive_binding_to_actual_request(
    tmp_path, market, missing
):
    context, request, products, calls = fixture(tmp_path, market, missing=missing)
    # Prepare a seed-only recipe ending before the dynamic source starts.
    from dataflows.equity_data import equity_metadata, sessions_from_metadata, session_record

    def ranged(binding):
        def fetch(query):
            frame, metadata = binding.fetch(query)
            p = query.parameters
            days = frame.Date.dt.tz_convert(p.instrument.timezone).dt.date
            frame = frame.loc[(days >= p.query.start) & (days <= p.query.end)].copy()
            source_sessions = sessions_from_metadata(metadata)
            sessions = tuple(
                s for s in source_sessions if p.query.start <= s.session_date <= p.query.end
            )
            following = next((s for s in source_sessions if s.session_date > p.query.end), None)
            following_record = (
                session_record(following)
                if following is not None
                else metadata.get("following_session")
            )
            metadata = {
                **metadata,
                **equity_metadata(query, sessions, availability_basis="SYNTHETIC_BAR_CLOSE"),
            }
            if (
                p.query.product in (EquityProduct.TRADING_FACTS, EquityProduct.SESSIONS)
                and following_record is not None
            ):
                metadata["following_session"] = following_record
            return frame, metadata

        return ProviderBinding(binding.name, binding.revision, fetch)

    context.data._equity_providers = {
        k: ranged(v) for k, v in context.data._equity_providers.items()
    }
    row = products[EquityProduct.BARS].iloc[1]
    seed_window = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        request = context.evaluation.prepare(
            replace(request, window=seed_window), execution=session
        ).request
    assert not calls
    recipe = FormalV4Inputs(
        "a" * 64,
        request.input_binding.for_observations(),
        request.fee_rate,
        prepare_raw_reference(context, request),
    )
    client = FormalV4AdviceClient(
        repo_root=tmp_path,
        store=SimpleNamespace(virtual_account=lambda account: {"last_decision_payload": None}),
        dataflows=context.data,
        data_dir=tmp_path / "forward",
    )
    first = client._forward_inputs(
        "fixture", recipe, seed_window, cutoff=seed_window.start, candidate=request.candidate
    )
    client._save_interval(client._interval_path("fixture", recipe.release_hash, seed_window), first)
    assert first.binding.observation_bindings[0].request is None
    assert not calls
    with patch.object(
        context.data, "prepare", side_effect=AssertionError("pinned interval must be reused")
    ):
        assert (
            client._forward_inputs(
                "fixture",
                recipe,
                seed_window,
                cutoff=seed_window.start,
                candidate=request.candidate,
            )
            == first
        )
    row = products[EquityProduct.BARS].iloc[-1]
    later = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    if missing:
        with pytest.raises(ValueError, match="preparation is incomplete"):
            client._forward_inputs(
                "fixture", recipe, later, cutoff=later.start, candidate=request.candidate
            )
        assert len(calls) == 1
        assert not client._interval_path("fixture", recipe.release_hash, later).exists()
        return
    active = client._forward_inputs(
        "fixture", recipe, later, cutoff=later.start, candidate=request.candidate
    )
    (binding,) = active.binding.observation_bindings
    assert binding.request.start == "2026-10-11"
    assert binding.request.end == "2026-10-14"
    assert binding.content_sha256 and binding.inactive_through is None
    assert len(calls) == 1
    from paper_trading_engine.execution_inputs import resolve_live_context

    calendar_request = next(
        query
        for role, query in active.binding.bind_requests(active.strategy_requests)
        if role == "sessions"
    )
    calendar = context.data.fetch(calendar_request, prepared=active.binding.prepared)
    assert calendar.ready
    sessions = sessions_from_metadata(calendar.identity.metadata)
    # The synthetic calendar ends on Thursday; Friday is explicitly known for
    # the host's T+1 availability calculation, without adding a future price bar.
    tail = sessions[-1]
    assert tail.session_date == date(2026, 10, 15)
    next_session = replace(
        tail,
        session_date=date(2026, 10, 16),
        segments=tuple(
            TimeInterval(part.start + timedelta(days=1), part.end + timedelta(days=1))
            for part in tail.segments
        ),
    )
    calendar_metadata = {
        **calendar.identity.metadata,
        "sessions": [session_record(s) for s in (*sessions, next_session)],
    }
    execution_context = resolve_live_context(
        request.candidate, later, calendar.dataframe, calendar_metadata
    )
    online = prepare_equity_decision(
        context.data,
        request.candidate,
        active.binding,
        active.strategy_requests,
        later,
        fee_rate=request.fee_rate,
        live=True,
        execution_context=execution_context,
        execution_reference=active.execution_reference.fetch(
            context.data, later, latency_seconds=context.execution_spec.data_latency_seconds
        ),
    )
    from strategy_runtime.account_planning import AccountDecisionEngine

    view = AccountDecisionEngine(request.candidate, online.v4_replay).table_views(later.start)[
        "increment"
    ]
    assert view.status is TableObservationStatus.ACTIVE and len(view) == 4


@pytest.fixture
def activation_table():
    declaration = DatasetObservationInput(
        "flow",
        Dataset.STOCK_MONEYFLOW,
        history_start=date(2026, 10, 10),
        availability=ObservationAvailability("Asia/Shanghai", "17:00", 1),
        required_from=date(2026, 10, 14),
    )
    data = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-10-10", "2026-10-14"]),
            "AvailableDate": pd.to_datetime(["2026-10-10", "2026-10-14"]),
            "Symbol": ["600000.SH"] * 2,
            "NetMoneyflow": [1.0, 2.0],
        }
    )
    identity = DataIdentity(
        Dataset.STOCK_MONEYFLOW.value,
        "fixture",
        None,
        "2026-10-10",
        "2026-10-14",
        "a" * 64,
        {
            "primary_key": ["Date", "Symbol"],
            "source_time_field": "Date",
            "availability_time_field": "AvailableDate",
            "source_calendar": "SSE",
            "available_at": "EXPLICIT",
            "request_range_policy": "EXACT",
        },
    )
    return declaration, PreparedObservationTable.from_frame(data, identity, declaration=declaration)


def test_SRT_18_C01_before_activation_does_not_request_data(tmp_path, activation_table):
    declaration, table = activation_table
    flows = SimpleNamespace(
        prepare=lambda *a, **k: pytest.fail("inactive must not acquire even calendar")
    )
    assert resolve_observation_requests(
        flows, (declaration,), date(2026, 10, 12), date(2026, 10, 13), source_root=tmp_path
    ) == (("observation:flow", None),)
    binding = DatasetObservationBinding(declaration, None, None, date(2026, 10, 13))
    assert DatasetObservationBinding.from_dict(MappingProxyType(binding.to_dict())) == binding
    assert "content_sha256" not in binding.to_dict() and "request" not in binding.to_dict()
    assert (
        table.view(datetime(2026, 10, 13, 17, tzinfo=ZoneInfo("Asia/Shanghai"))).status
        is TableObservationStatus.INACTIVE
    )


def test_SRT_18_C02_exact_activation_enables_existing_facts(activation_table):
    declaration, table = activation_table
    assert declaration.activation_at == datetime(2026, 10, 15, 17, tzinfo=ZoneInfo("Asia/Shanghai"))
    view = table.view(declaration.activation_at)
    assert view.status is TableObservationStatus.ACTIVE and len(view) == 2


def test_SRT_18_C03_seed_history_stays_hidden_before_activation(activation_table):
    declaration, table = activation_table
    before = table.view(declaration.activation_at - timedelta(seconds=1))
    assert before.status is TableObservationStatus.INACTIVE and not before.rows
    assert len(table.view(declaration.activation_at)) == 2


def test_SRT_18_C04_active_missing_data_is_an_error(tmp_path):
    context, request, _, calls = fixture(tmp_path, MarketId.CN, missing=True)
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        with pytest.raises(ValueError, match="preparation failed"):
            context.evaluation.prepare(request, execution=session)
    assert calls


def test_SRT_18_C05_active_stale_data_rejected(tmp_path, activation_table):
    from dataflows import BarFrequency
    from strategy_runtime import AccountDecisionEngine, StrategyComputation, PreparedObservations
    from packages.strategy_runtime.tests.v4_fixture_support import setup

    declaration, table = activation_table
    declaration = replace(declaration, max_staleness_days=0)
    c, p, _, bars, _, sessions, session_frame = setup(
        tmp_path,
        MarketId.CN,
        BarFrequency.DAILY,
        StrategyComputation.STATEFUL_STEP,
        with_executor=False,
    )
    c = replace(c, definition=replace(c.definition, observation_inputs=(declaration,)))
    p = PreparedObservations.from_frames(
        bars,
        c.definition.feature_graph,
        frequency=BarFrequency.DAILY,
        timezone=c.instrument.timezone,
        sessions=session_frame,
        trading_sessions=sessions,
        observation_tables={"flow": table},
    )
    with pytest.raises(ValueError, match="OBSERVATION_INPUT_STALE"):
        AccountDecisionEngine(c, p).table_views(declaration.activation_at)


def test_SRT_18_C06_required_from_cannot_precede_history(activation_table):
    declaration, _ = activation_table
    with pytest.raises(ValueError):
        replace(declaration, required_from=date(2026, 10, 9))


def test_SRT_18_C07_frozen_resource_cannot_have_dynamic_activation(activation_table):
    from strategy_runtime import FrozenDataAsset

    declaration, _ = activation_table
    with pytest.raises(ValueError):
        replace(
            declaration,
            dataset=Dataset.STRATEGY_FEATURE_EVIDENCE,
            symbol="S999-v1",
            history_end=date(2026, 10, 14),
            asset=FrozenDataAsset("seed.csv", "a" * 64),
        )
