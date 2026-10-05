"""Offline checks of the public two-phase API and managed asset lifecycle."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
import multiprocessing
from pathlib import Path
import sqlite3
from threading import Barrier
from uuid import uuid4

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from dataflows import (
    DataCoverageRequirement, Dataflows, DataRequest, DataSpace, DataStatus,
    Dataset, PreparePolicy, PrepareStatus, ProviderBinding, ProviderConfig,
)
from dataflows import asset_store


def _frame(offset=0.0):
    return pd.DataFrame({
        "Date": pd.date_range("2026-09-14", periods=3),
        "Open": [1.0 + offset, 1.1 + offset, 1.2 + offset],
        "High": [1.2 + offset, 1.3 + offset, 1.4 + offset],
        "Low": [0.9 + offset, 1.0 + offset, 1.1 + offset],
        "Close": [1.1 + offset, 1.2 + offset, 1.3 + offset],
        "Volume": [100, 120, 140],
        "Amount": [105.1234567890123, 138.000000000001, 175.9],
    })


def _request(symbol="518850.SH"):
    return DataRequest(Dataset.ETF_OHLCV, symbol, "2026-09-14", "2026-09-16", "2026-09-16")


def _flows(base_dir, provider, name="space"):
    return Dataflows(
        base_dir=base_dir, space=DataSpace(Path(name)),
        providers=ProviderConfig(bindings={
            Dataset.ETF_OHLCV: ProviderBinding("synthetic", "v1", provider),
        }),
    )


def _database(base_dir, name="space"):
    return base_dir / name / "assets.sqlite3"


def _counts(base_dir, name="space"):
    with sqlite3.connect(_database(base_dir, name).as_uri() + "?mode=ro", uri=True) as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("assets", "preparations"))


def _must_not_fetch(request):
    raise AssertionError("supplier must not be called")


def test_refresh_keeps_old_reference_and_reopen_reuses_assets(tmp_path):
    calls = []
    source = _frame()

    def provider(request):
        calls.append(request)
        return source, {"vendor": "synthetic"}

    flows = _flows(tmp_path, provider)
    first = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
    assert first.ready
    with sqlite3.connect(_database(tmp_path).as_uri() + "?mode=ro", uri=True) as conn:
        acquired = conn.execute("SELECT acquired_at FROM assets").fetchone()[0]
        prepared_at = conn.execute("SELECT prepared_at FROM preparations").fetchone()[0]
    assert datetime.fromisoformat(acquired).utcoffset() == timedelta(0)
    assert datetime.fromisoformat(prepared_at).utcoffset() == timedelta(0)
    assert acquired <= prepared_at
    old = flows.fetch(_request(), prepared=first.reference)
    source = _frame(10)
    refreshed = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert refreshed.ready and refreshed.reference != first.reference
    assert len(calls) == 2
    assert_frame_equal(flows.fetch(_request(), prepared=first.reference).dataframe, old.dataframe)
    assert flows.fetch(_request(), prepared=refreshed.reference).dataframe["Close"].iloc[0] == 11.1
    with sqlite3.connect(_database(tmp_path).as_uri() + "?mode=ro", uri=True) as conn:
        acquisition_times = conn.execute("SELECT acquired_at FROM assets ORDER BY acquired_at").fetchall()
    same = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert same.ready and same.reference != refreshed.reference and _counts(tmp_path) == (2, 3)
    with sqlite3.connect(_database(tmp_path).as_uri() + "?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT acquired_at FROM assets ORDER BY acquired_at").fetchall() == acquisition_times
    reopened = _flows(tmp_path, _must_not_fetch)
    reused = reopened.prepare((_request(),), policy=PreparePolicy.REUSE)
    assert reused.ready and _counts(tmp_path) == (2, 4)
    assert_frame_equal(reopened.fetch(_request(), prepared=reused.reference).dataframe,
                       flows.fetch(_request(), prepared=refreshed.reference).dataframe)


def test_partial_prepare_preserves_success_for_retry_without_batch_reference(tmp_path):
    calls = []
    failing = True

    def provider(request):
        calls.append(request.symbol)
        if failing and request.symbol == "518880.SH":
            raise RuntimeError("source unavailable")
        return _frame(), {"vendor": "synthetic"}

    flows = _flows(tmp_path, provider)
    requests = (_request(), _request("518880.SH"))
    partial = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert partial.status is PrepareStatus.PARTIAL and partial.reference is None
    assert [item.status for item in partial.items] == [DataStatus.READY, DataStatus.FAILED]
    assert _counts(tmp_path) == (1, 0)
    failing = False
    retry = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert retry.ready
    assert calls == ["518850.SH", "518880.SH", "518880.SH"]
    assert _counts(tmp_path) == (2, 1)


def test_failed_refresh_leaves_previous_lookup_and_reference_usable(tmp_path):
    flows = _flows(tmp_path, lambda request: (_frame(), {"vendor": "synthetic"}))
    original = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
    broken = _flows(tmp_path, _must_not_fetch)
    failed = broken.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert failed.status is PrepareStatus.FAILED
    assert failed.reference is None and _counts(tmp_path) == (1, 1)
    assert broken.fetch(_request(), prepared=original.reference).ready
    reused = broken.prepare((_request(),), policy=PreparePolicy.REUSE)
    assert reused.ready and _counts(tmp_path) == (1, 2)


def test_cross_space_unknown_and_tampered_references_fail(tmp_path):
    def provider(request):
        return _frame(), {"vendor": "synthetic"}
    flows = _flows(tmp_path, provider)
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
    other = _flows(tmp_path, _must_not_fetch, "other")
    assert other.fetch(_request(), prepared=prepared.reference).error.code == "SPACE_MISMATCH"
    unknown = replace(prepared.reference, preparation_id=uuid4())
    assert flows.fetch(_request(), prepared=unknown).error.code == "UNKNOWN_REF"
    incorrect = replace(prepared.reference, manifest_sha256="0" * 64)
    assert flows.fetch(_request(), prepared=incorrect).error.code == "PREPARATION_CORRUPT"


@pytest.mark.parametrize("target, expected", [
    ("manifest", "PREPARATION_CORRUPT"),
    ("payload", "ASSET_CORRUPT"),
    ("missing_asset", "ASSET_MISSING"),
])
def test_corrupt_or_missing_assets_never_trigger_supplier_fallback(tmp_path, target, expected):
    calls = []

    def provider(request):
        calls.append(request)
        return _frame(), {"vendor": "synthetic"}

    flows = _flows(tmp_path, provider)
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
    assert prepared.ready
    with sqlite3.connect(_database(tmp_path)) as conn:
        if target == "manifest":
            conn.execute("UPDATE preparations SET manifest='[]'")
        elif target == "payload":
            conn.execute("UPDATE assets SET payload=?", (b"corrupt",))
        else:
            conn.execute("DELETE FROM assets")
    result = flows.fetch(_request(), prepared=prepared.reference)
    assert result.status is DataStatus.FAILED and result.error.code == expected
    assert result.dataframe.empty and result.identity is None and len(calls) == 1


def test_fetch_is_read_only_and_subset_bound_coverage_is_not_asset_identity(tmp_path):
    calls = []

    def provider(request):
        calls.append(request)
        return _frame(), {"vendor": "synthetic"}

    flows = _flows(tmp_path, provider)
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
    stronger = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=3))
    reused = flows.prepare((stronger,), policy=PreparePolicy.REUSE)
    assert reused.ready and _counts(tmp_path) == (1, 2) and len(calls) == 1
    before = _database(tmp_path).stat().st_mtime_ns
    subset = replace(_request(), start="2026-09-15")
    result = flows.fetch(subset, prepared=prepared.reference)
    assert result.ready and result.prepared == prepared.reference
    assert len(result.dataframe) == 2
    outside = replace(_request(), start="2026-09-13")
    assert flows.fetch(outside, prepared=prepared.reference).error.code == "REQUEST_NOT_PREPARED"
    insufficient = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=4))
    assert flows.fetch(insufficient, prepared=prepared.reference).status is DataStatus.INCOMPLETE
    assert _database(tmp_path).stat().st_mtime_ns == before and len(calls) == 1


def test_pandas_schema_precision_and_detached_frames_survive_reopen(tmp_path):
    source = _frame()
    source["PublishedAt"] = pd.date_range("2026-09-14", periods=3, tz="Asia/Shanghai")
    source["NullableCount"] = pd.array([1, None, 3], dtype="Int64")
    source["Class"] = pd.Categorical(["b", "a", "b"], categories=["b", "a"], ordered=True)
    source["NullableText"] = pd.array(["a", None, "c"], dtype="string")
    flows = _flows(tmp_path, lambda request: (source, {"vendor": "synthetic"}))
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert prepared.ready
    reopened = _flows(tmp_path, _must_not_fetch)
    first = reopened.fetch(_request(), prepared=prepared.reference)
    assert first.ready
    assert_frame_equal(first.dataframe, source, check_exact=True)
    first.dataframe.loc[0, "Close"] = 99
    assert_frame_equal(reopened.fetch(_request(), prepared=prepared.reference).dataframe,
                       source, check_exact=True)


def _process_prepare(base_dir):
    """Importable spawn worker; supplier call receipt is separate from DFLS assets."""
    base_dir = Path(base_dir)

    def provider(request):
        with (base_dir / "supplier-calls.txt").open("a", encoding="utf-8") as stream:
            stream.write("call\n")
        return _frame(), {"vendor": "synthetic"}

    flows = _flows(base_dir, provider)
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
    if not prepared.ready:
        raise AssertionError(str(prepared.items))
    result = flows.fetch(_request(), prepared=prepared.reference)
    assert result.ready
    return str(prepared.reference.space_id), result.identity.content_sha256


def test_threads_create_same_space_concurrently_and_prepare_once(tmp_path):
    barrier = Barrier(4)

    def worker():
        barrier.wait(timeout=10)
        return _process_prepare(str(tmp_path))

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda index: worker(), range(4)))
    assert len(set(results)) == 1
    assert (tmp_path / "supplier-calls.txt").read_text().splitlines() == ["call"]
    assert _counts(tmp_path) == (1, 4)
    assert not list((tmp_path / "space").glob("*.initializing.sqlite3*"))


def test_spawn_processes_share_first_space_and_prepare_once(tmp_path):
    with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context("spawn")) as executor:
        results = list(executor.map(_process_prepare, [str(tmp_path)] * 3))
    assert len(set(results)) == 1
    assert (tmp_path / "supplier-calls.txt").read_text().splitlines() == ["call"]
    assert _counts(tmp_path) == (1, 3)


@pytest.mark.parametrize("path", [Path("."), Path("../escape"), Path("a/../../escape")])
def test_invalid_space_paths_are_rejected(path):
    with pytest.raises(ValueError):
        DataSpace(path)


def test_absolute_space_path_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        DataSpace(tmp_path / "space")


@pytest.mark.parametrize("payload", [b"", b"not a SQLite database"])
def test_existing_uninitialized_or_corrupt_database_is_not_recreated(tmp_path, payload):
    database = _database(tmp_path)
    database.parent.mkdir()
    database.write_bytes(payload)
    with pytest.raises(asset_store.StoreError) as error:
        _flows(tmp_path, _must_not_fetch)
    assert error.value.code == "SPACE_CORRUPT"
    assert database.read_bytes() == payload


def test_lock_timeout_returns_failure_without_provider_fallback(tmp_path, monkeypatch):
    flows = _flows(tmp_path, _must_not_fetch)
    connect = sqlite3.connect

    def short_timeout(*args, **kwargs):
        kwargs["timeout"] = 0.01
        return connect(*args, **kwargs)

    with connect(_database(tmp_path)) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        monkeypatch.setattr(asset_store.sqlite3, "connect", short_timeout)
        result = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
        assert result.status is PrepareStatus.FAILED and result.reference is None
        assert result.items[0].error.code == "SPACE_LOCK_TIMEOUT"
        blocker.rollback()


def test_unserializable_provider_metadata_is_structured_failure(tmp_path):
    flows = _flows(tmp_path, lambda request: (_frame(), {"vendor": "synthetic", "invalid": object()}))
    result = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert result.status is PrepareStatus.FAILED and result.reference is None
    assert result.items[0].error.code == "ASSET_SERIALIZATION_FAILED"
    assert _counts(tmp_path) == (0, 0)
