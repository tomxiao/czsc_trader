# Risk ownership: SRT-18
"""Activation and decoding of historical observation declarations."""
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import DataIdentity, Dataset
from strategy_runtime.dataset_observations import (
    DatasetObservationBinding, DatasetObservationInput, ObservationAvailability,
    PreparedObservationTable, TableObservationStatus,
)
from strategy_runtime.observation_preparation import resolve_observation_requests


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


def test_SRT_18_C05_historical_observation_contract_cannot_execute(tmp_path, activation_table):
    from dataflows import BarFrequency, MarketId
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
    with pytest.raises(ValueError, match="V5 DFLS step contract"):
        AccountDecisionEngine(c, p)


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
