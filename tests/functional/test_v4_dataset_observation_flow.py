# Risk ownership: TDR-28
"""Published tables keep their identity and causal views across V4 consumers."""

from test_v4_inspection_roundtrip import prepare_raw_reference
from dataclasses import replace
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataset, MarketId, ProviderBinding, EquityProduct, TimeInterval
from strategy_runtime import StrategyComputation, equity_source_hash
from strategy_runtime.dataset_observations import (
    DatasetObservationInput,
    FrozenDataAsset,
    ObservationAvailability,
)
from czsc_trader.research_tools import ResearchExecutionSession
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4Inputs
from adjusted_observation_support import setup_adjusted


def observation_fixture(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP):
    context, request, products, _, _ = setup_adjusted(tmp_path, market, computation)
    root = request.candidate.source_root
    asset = root / "seed.csv"
    asset.write_text("date,value\n2026-10-12,7\n", encoding="utf-8")
    availability = ObservationAvailability("Asia/Shanghai", "16:00")
    observations = (
        DatasetObservationInput(
            "weights", Dataset.INDEX_CONSTITUENT_WEIGHT, "000300.SH", availability=availability
        ),
        DatasetObservationInput("rate", Dataset.SHIBOR_DAILY, availability=availability),
        DatasetObservationInput(
            "seed",
            Dataset.STRATEGY_FEATURE_EVIDENCE,
            "S999-v1",
            history_start=date(2026, 10, 12),
            history_end=date(2026, 10, 12),
            asset=FrozenDataAsset("seed.csv", sha256(asset.read_bytes()).hexdigest()),
            availability=availability,
        ),
    )
    (root / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n"
        "def decision(ctx):\n"
        "    tables = ctx.observations\n"
        '    assert len(tables["weights"]) >= 2\n'
        '    assert len(tables["seed"]) == 1\n'
        '    return AccountDecision.from_facts(1, "table inputs", '
        'facts={"weights": len(tables["weights"]), "rate": len(tables["rate"])}, '
        'next_watch="next session")\n'
        "def step(ctx, state):\n"
        "    return AccountStepResult(decision(ctx), cycle_values=StateRecord())\n"
        "def batch(ctx):\n"
        "    return tuple(decision(row) for row in ctx.observations)\n",
        encoding="utf-8",
    )
    candidate = replace(
        request.candidate,
        definition=replace(
            request.candidate.definition,
            source_sha256=equity_source_hash(root, ("strategy.py",)),
            observation_inputs=observations,
        ),
    )
    calls = []

    def fetch(query):
        calls.append(query)
        days = pd.date_range(query.start, query.end, freq="D")
        if query.dataset is Dataset.INDEX_CONSTITUENT_WEIGHT:
            frame = pd.DataFrame(
                [
                    dict(Date=day, ConstituentSymbol=symbol, Weight=50.0)
                    for day in days
                    for symbol in ("600000.SH", "600001.SH")
                ]
            )
            return frame, {"primary_key": ["Date", "ConstituentSymbol"]}
        return pd.DataFrame(dict(Date=days, OvernightRate=2.0)), {"primary_key": ["Date"]}

    for dataset in (Dataset.INDEX_CONSTITUENT_WEIGHT, Dataset.SHIBOR_DAILY):
        context.data._providers[dataset.value] = ProviderBinding("tables", "v1", fetch)
    from dataflows.local_strategy_data import fetch_strategy_feature_evidence

    context.data._providers[Dataset.STRATEGY_FEATURE_EVIDENCE.value] = ProviderBinding(
        "seed", "v1", fetch_strategy_feature_evidence
    )
    return context, replace(request, candidate=candidate), products, calls


@pytest.mark.parametrize("market", [MarketId.CN])
def test_forward_tables_pin_intervals_and_keep_seed_bounds(tmp_path, market):
    context, request, products, _ = observation_fixture(tmp_path, market)
    with ResearchExecutionSession(context, experiment=request.experiment) as session:
        request = context.evaluation.prepare(request, execution=session).request
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
            metadata = {
                **metadata,
                **equity_metadata(query, sessions, availability_basis="SYNTHETIC_BAR_CLOSE"),
            }
            if following is not None and p.query.product in (
                EquityProduct.TRADING_FACTS,
                EquityProduct.SESSIONS,
            ):
                metadata["following_session"] = session_record(following)
            return frame, metadata

        return ProviderBinding(binding.name, binding.revision, fetch)

    context.data._equity_providers = {
        key: ranged(value) for key, value in context.data._equity_providers.items()
    }
    client = FormalV4AdviceClient(
        repo_root=tmp_path,
        store=SimpleNamespace(virtual_account=lambda account: {"last_decision_payload": None}),
        dataflows=context.data,
        data_dir=tmp_path / "forward",
    )
    recipe = FormalV4Inputs(
        "a" * 64,
        request.input_binding.for_observations(),
        request.fee_rate,
        prepare_raw_reference(context, request),
    )
    row = products[EquityProduct.BARS].iloc[1]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    value = client._forward_inputs(
        "fixture", recipe, interval, cutoff=interval.start, candidate=request.candidate
    )
    client._save_interval(client._interval_path("fixture", recipe.release_hash, interval), value)
    queries = {x.input.name: x.request for x in value.binding.observation_bindings}
    assert queries["seed"].start == queries["seed"].end == "2026-10-12"
    assert queries["rate"].end == ("2026-10-12" if market is MarketId.CN else "2026-10-13")
    with patch.object(
        context.data, "prepare", side_effect=AssertionError("must reuse pinned interval")
    ):
        assert (
            client._forward_inputs(
                "fixture", recipe, interval, cutoff=interval.start, candidate=request.candidate
            )
            == value
        )
    next_interval = TimeInterval(
        interval.start + timedelta(days=1), interval.end + timedelta(days=1)
    )
    following = client._forward_inputs(
        "fixture", recipe, next_interval, cutoff=next_interval.start, candidate=request.candidate
    )
    next_queries = {x.input.name: x.request for x in following.binding.observation_bindings}
    assert next_queries["seed"] == queries["seed"]
    assert next_queries["rate"].end > queries["rate"].end


@pytest.fixture
def weekly_calendar(tmp_path):
    from dataflows import Dataflows, DataSpace, ProviderConfig

    closed = set()

    def calendar(query):
        days = pd.date_range(query.start, query.end)
        return pd.DataFrame(
            {
                "Date": days,
                "IsOpen": [
                    int(day.weekday() < 5 and day.strftime("%Y-%m-%d") not in closed)
                    for day in days
                ],
            }
        ), {}

    flows = Dataflows(
        base_dir=tmp_path,
        space=DataSpace(Path("calendar")),
        providers=ProviderConfig(
            bindings={Dataset.TRADING_CALENDAR: ProviderBinding("synthetic", "v1", calendar)}
        ),
    )
    return flows, closed


@pytest.mark.parametrize(
    "case",
    ["midweek", "holiday", "boundary", "partial_first", "fixed_end", "naive", "no_week"],
    ids=[
        "SRT-32-C01",
        "SRT-32-C02",
        "SRT-32-C03",
        "SRT-32-C04",
        "SRT-32-C05",
        "SRT-32-C06",
        "SRT-32-C07",
    ],
)
def test_completed_week_request_boundaries(tmp_path, weekly_calendar, case):
    from strategy_runtime.observation_preparation import resolve_observation_requests

    flows, closed = weekly_calendar
    zone = ZoneInfo("Asia/Shanghai")
    declaration = DatasetObservationInput(
        "weekly",
        Dataset.ETF_OHLCV,
        "588080.SH",
        frequency="weekly",
        availability=ObservationAvailability("Asia/Shanghai", "15:00"),
    )
    start = date(2026, 10, 5)
    moment = datetime(2026, 10, 14, 16, tzinfo=zone)
    expected = "2026-10-09"
    failure = None
    if case == "holiday":
        closed.add("2026-10-16")
        moment = datetime(2026, 10, 15, 15, tzinfo=zone)
        expected = "2026-10-15"
    elif case == "boundary":
        moment = datetime(2026, 10, 16, 14, 59, 59, tzinfo=zone)
    elif case == "partial_first":
        start = date(2026, 10, 6)
        declaration = replace(declaration, history_start=start)
        failure = "start omits source sessions"
    elif case == "fixed_end":
        declaration = replace(declaration, history_start=start, history_end=date(2026, 10, 14))
        failure = "fixed weekly observation end"
    elif case == "naive":
        moment = moment.replace(tzinfo=None)
        failure = "aware cutoff"
    elif case == "no_week":
        start = date(2026, 10, 12)
        failure = "no completed source trading week"
    if failure:
        with pytest.raises(ValueError, match=failure):
            resolve_observation_requests(
                flows, (declaration,), start, moment.date(), source_root=tmp_path, as_of=moment
            )
    else:
        ((_, query),) = resolve_observation_requests(
            flows, (declaration,), start, moment.date(), source_root=tmp_path, as_of=moment
        )
        assert query.end == expected
        if case == "boundary":
            moment = moment.replace(hour=15, minute=0, second=0)
            ((_, complete),) = resolve_observation_requests(
                flows, (declaration,), start, moment.date(), source_root=tmp_path, as_of=moment
            )
            assert complete.end == "2026-10-16"
