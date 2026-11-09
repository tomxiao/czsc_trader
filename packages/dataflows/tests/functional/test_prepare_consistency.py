"""Regression checks for batch consistency and typed subset reads."""

from dataclasses import replace
import sqlite3

import pandas as pd
import pytest
from ohlcv_test_support import ohlcv_fixture_metadata

from dataflows import (
    DataCoverageRequirement,
    DataRequest,
    DataStatus,
    Dataset,
    PreparePolicy,
    PrepareStatus,
    canonical_frame_sha256,
)


def _request():
    return DataRequest(Dataset.SHIBOR_DAILY, None, "2026-09-14", "2026-09-16", None)


def _rates():
    return pd.DataFrame({
        "Date": pd.date_range("2026-09-14", periods=3),
        "OvernightRate": [1.0, 1.1, 1.2],
    })


def _minute_fixture_metadata():
    clocks = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
    minute = pd.DataFrame({
        "Date": pd.to_datetime([f"2026-09-14 {clock}" for clock in clocks]),
        "Open": 1., "High": 1., "Low": 1., "Close": 1., "Volume": 100., "Amount": 100.,
    })
    daily = pd.DataFrame({
        "Date": pd.to_datetime(["2026-09-14"]), "Open": 1., "High": 1., "Low": 1.,
        "Close": 1., "Volume": 800., "Amount": 800.,
    })
    return {"vendor": "fixture", **ohlcv_fixture_metadata(
        daily, start="2026-09-14", end="2026-09-14", intraday=minute, frequency="30m",
    )}


def test_DFLS_09_C01_refresh_deduplicates_acquisition_but_checks_each_coverage(flow_factory):
    calls = []

    def provider(request):
        calls.append(request)
        return _rates(), {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    first = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=2))
    second = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=3))
    prepared = flows.prepare((first, second), policy=PreparePolicy.REFRESH)
    assert prepared.ready and len(calls) == 1
    reused = flows.prepare((first, second), policy=PreparePolicy.REUSE)
    assert reused.ready and reused.reference == prepared.reference
    reordered = flows.prepare((second, first), policy=PreparePolicy.REUSE)
    assert reordered.ready and reordered.reference != prepared.reference
    assert tuple(item.request for item in reordered.items) == (second, first) and len(calls) == 1
    assert flows.fetch(first, prepared=prepared.reference).ready
    assert flows.fetch(second, prepared=prepared.reference).ready

    excessive = replace(second, coverage=DataCoverageRequirement(minimum_observations=4))
    assert flows.fetch(excessive, prepared=prepared.reference).status is DataStatus.INCOMPLETE
    assert len(calls) == 1
    rejected = flows.prepare((first, excessive), policy=PreparePolicy.REFRESH)
    assert len(calls) == 2
    assert rejected.status is PrepareStatus.PARTIAL and rejected.reference is None
    assert [item.status for item in rejected.items] == [DataStatus.READY, DataStatus.INCOMPLETE]










def test_DFLS_09_C02_conflicting_overlap_prevents_batch_publication(flow_factory, tmp_path):
    calls = []
    conflicting = True

    def provider(request):
        calls.append(request)
        frame = _rates()
        frame = frame.loc[frame.Date.between(request.start, request.end)].copy()
        if conflicting and request.start == "2026-09-15":
            frame.loc[frame.Date.eq("2026-09-15"), "OvernightRate"] = 9.9
        return frame, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    result = flows.prepare(
        (_request(), replace(_request(), start="2026-09-15")), policy=PreparePolicy.REFRESH,
    )
    assert len(calls) == 2
    assert result.status is PrepareStatus.FAILED and result.reference is None
    assert all(item.error.code == "INCONSISTENT_PREPARATION" for item in result.items)
    with sqlite3.connect(tmp_path / "space-0" / "assets.sqlite3") as connection:
        assert [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("assets", "asset_lookup", "preparations")] == [0, 0, 0]
    conflicting = False
    retried = flows.prepare(
        (_request(), replace(_request(), start="2026-09-15")), policy=PreparePolicy.REUSE,
    )
    assert retried.ready and len(calls) == 4
    for request in (_request(), replace(_request(), start="2026-09-15")):
        assert flows.fetch(request, prepared=retried.reference).dataframe.OvernightRate.max() == 1.2




@pytest.mark.parametrize("categories, ordered", [
    (["b", "a"], False),
    (["a", "b"], True),
], ids=['DFLS-03-C02', 'DFLS-03-C03'])
def test_categorical_domain_and_order_are_part_of_content_identity(categories, ordered):
    original = pd.DataFrame({"Class": pd.Categorical(["a", "b"], categories=["a", "b"])})
    changed = pd.DataFrame({
        "Class": pd.Categorical(["a", "b"], categories=categories, ordered=ordered),
    })
    assert original.Class.astype(str).tolist() == changed.Class.astype(str).tolist()
    assert canonical_frame_sha256(original) != canonical_frame_sha256(changed)
    expected = canonical_frame_sha256(original)
    original.attrs = {"quality_evidence": {"sessions": ["2026-09-14", "2026-09-15"]}}
    source = original.copy()
    assert canonical_frame_sha256(original) == expected
    pd.testing.assert_frame_equal(original, source, check_exact=True)
    assert original.attrs == source.attrs










@pytest.mark.parametrize("strict_first", [
    False,
    True,
], ids=['DFLS-09-C03', 'DFLS-09-C04'])
def test_reuse_refreshes_once_for_all_requirements_independent_of_order(flow_factory, strict_first):
    calls = []
    source = _rates().iloc[:1].copy()

    def provider(request):
        calls.append(request)
        return source, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    original = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert original.ready and len(calls) == 1
    source = _rates().iloc[:2].copy()
    strict = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=2))
    requests = (strict, _request()) if strict_first else (_request(), strict)
    prepared = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert prepared.ready and len(calls) == 2
    assert all(item.status is DataStatus.READY for item in prepared.items)
    for request in requests:
        result = flows.fetch(request, prepared=prepared.reference)
        assert result.ready and len(result.dataframe) == 2
