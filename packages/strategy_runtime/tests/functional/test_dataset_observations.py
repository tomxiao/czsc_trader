"""Causal table inputs and opt-in planning facts on the shared V4 engine."""

from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import pickle

import pandas as pd
import pytest
from dataflows import DataIdentity, Dataset, MarketId, BarFrequency
from strategy_runtime import (
    DatasetObservationInput,
    FrozenDataAsset,
    ObservationAvailability,
    PreparedObservationTable,
    StrategyComputation,
)
from packages.strategy_runtime.tests.v4_fixture_support import setup


def identity(
    dataset=Dataset.INDEX_CONSTITUENT_WEIGHT, symbol="000905.SH", *, available="AvailableDate"
):
    return DataIdentity(
        dataset.value,
        "fixture",
        symbol,
        "2026-01-01",
        "2026-01-03",
        "a" * 64,
        dict(
            source_time_field="Date",
            availability_time_field=available,
            source_calendar="SSE",
            available_at="EXPLICIT",
            request_range_policy="EXACT",
            primary_key=["Date", "ConstituentSymbol"]
            if dataset is Dataset.INDEX_CONSTITUENT_WEIGHT
            else ["Date"],
        ),
    )


def test_SRT_17_C01_panel_visibility_keeps_same_day_rows_and_delayed_publication():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02"], utc=True),
            "AvailableDate": pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-02"], utc=True),
            "ConstituentSymbol": ["A", "B", "A"],
            "Weight": [1.0, 2.0, 3.0],
        }
    )
    table = PreparedObservationTable.from_frame(frame, identity())
    table = pickle.loads(pickle.dumps(table))
    view = table.view(datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert view.observation_count == view.session_count == 2
    assert view.latest_session == date(2026, 1, 2)
    later = table.view(datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert later.observation_count == 3
    assert later.session_count == 2
    assert later.latest_session == view.latest_session
    assert tuple(row["Weight"] for row in pickle.loads(pickle.dumps(later)).rows) == (1., 2., 3.)
    assert [(row["ConstituentSymbol"], row["Weight"]) for row in view.rows] == [
        ("A", 1.0),
        ("A", 3.0),
    ]
    assert view.observation_count == 2
    assert len(table.view(datetime(2026, 1, 3, tzinfo=timezone.utc))) == 3
    assert table.view(datetime(2026, 1, 3, tzinfo=timezone.utc)).session_count == 2
    with pytest.raises(TypeError):
        view.rows[0]["Weight"] = 10
    copied = view.to_frame()
    copied.loc[0, "Weight"] = 999
    frame.loc[0, "Weight"] = 888
    assert view.rows[0]["Weight"] == 1.0
    with pytest.raises(ValueError, match="duplicated"):
        PreparedObservationTable.from_frame(pd.concat([frame, frame.iloc[[0]]]), identity())
    with pytest.raises(ValueError, match="exceeds availability"):
        PreparedObservationTable.from_frame(
            frame.assign(AvailableDate=pd.Timestamp("2025-12-31", tz="UTC")), identity()
        )


def test_SRT_19_C03_resource_path_case_alias_is_rejected_before_registration(tmp_path):
    c, *_ = setup(tmp_path, MarketId.US, BarFrequency.DAILY, StrategyComputation.STATEFUL_STEP)
    seed = DatasetObservationInput(
        "seed",
        Dataset.STRATEGY_FEATURE_EVIDENCE,
        "S999-v1",
        history_start=date(2026, 1, 1),
        history_end=date(2026, 1, 2),
        asset=FrozenDataAsset("seed.csv", "a" * 64),
    )
    other = replace(seed, name="alias", asset=FrozenDataAsset("Seed.csv", "a" * 64))
    with pytest.raises(ValueError, match="case-insensitive"):
        replace(c.definition, observation_inputs=(seed, other))


def test_SRT_17_C02_date_only_requires_publication_assumption():
    frame = pd.DataFrame({"Date": pd.to_datetime(["2026-11-02"]), "Close": [1.0]})
    with pytest.raises(ValueError, match="explicit publication"):
        PreparedObservationTable.from_frame(
            frame, identity(Dataset.GLOBAL_INDEX_DAILY, "SPX", available="Date")
        )


def test_SRT_17_C03_new_york_close_boundary():
    frame = pd.DataFrame({"Date": pd.to_datetime(["2026-11-02"]), "Close": [1.0]})
    declaration = DatasetObservationInput(
        "spx",
        Dataset.GLOBAL_INDEX_DAILY,
        "SPX",
        availability=ObservationAvailability("America/New_York", "16:00"),
    )
    table = PreparedObservationTable.from_frame(
        frame,
        identity(Dataset.GLOBAL_INDEX_DAILY, "SPX", available="Date"),
        declaration=declaration,
    )
    assert not table.view(datetime(2026, 11, 2, 20, 59, tzinfo=timezone.utc)).rows
    assert len(table.view(datetime(2026, 11, 2, 21, tzinfo=timezone.utc))) == 1


def test_SRT_17_C04_returned_table_frame_is_detached():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-01"], utc=True),
            "AvailableDate": pd.to_datetime(["2026-01-02"], utc=True),
            "ConstituentSymbol": ["A"],
            "Weight": [1.0],
        }
    )
    table = PreparedObservationTable.from_frame(frame, identity())
    view = table.view(datetime(2026, 1, 2, tzinfo=timezone.utc))
    copy = view.to_frame()
    copy.loc[0, "Weight"] = 999.0
    assert view.rows[0]["Weight"] == 1.0
    assert table.view(datetime(2026, 1, 2, tzinfo=timezone.utc)).rows[0]["Weight"] == 1.0


@pytest.mark.parametrize("conflict", [False, True], ids=["SRT-17-C05", "SRT-17-C06"])
def test_product_key_is_declared_not_guessed(conflict):
    metadata = dict(
        source_time_field="Date",
        availability_time_field="Date",
        source_calendar="SSE",
        available_at="source close",
        request_range_policy="EXACT",
    )
    if conflict:
        metadata["primary_key"] = ["Date"]
    value = DataIdentity(
        Dataset.INDEX_CONSTITUENT_WEIGHT.value if conflict else "unknown.product",
        "fixture",
        None,
        "2026-01-01",
        "2026-01-02",
        "a" * 64,
        metadata,
    )
    with pytest.raises(
        ValueError, match="dataset contract" if conflict else "no declared primary key"
    ):
        _ = value.primary_key


def test_SRT_19_C02_fixed_resource_hash_mismatch(tmp_path):
    source = tmp_path / "seed.csv"
    source.write_text("Date,value\n2026-01-01,1\n", encoding="utf8")
    item = DatasetObservationInput(
        "seed",
        Dataset.STRATEGY_FEATURE_EVIDENCE,
        "S999-v1",
        history_start=date(2026, 1, 1),
        history_end=date(2026, 1, 2),
        asset=FrozenDataAsset("seed.csv", sha256(source.read_bytes()).hexdigest()),
    )
    source.write_text("changed", encoding="utf8")
    with pytest.raises(ValueError, match="content differs"):
        item.request(date(2026, 2, 1), date(2026, 2, 3), source_root=tmp_path)


def test_SRT_19_C04_resource_path_cannot_escape():
    with pytest.raises(ValueError, match="relative"):
        FrozenDataAsset("../seed.csv", "a" * 64)


def test_SRT_19_C05_frozen_seed_requires_fixed_range():
    with pytest.raises(ValueError):
        DatasetObservationInput(
            "seed",
            Dataset.STRATEGY_FEATURE_EVIDENCE,
            "S999-v1",
            asset=FrozenDataAsset("seed.csv", "a" * 64),
        )
