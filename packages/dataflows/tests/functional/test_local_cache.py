from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import multiprocessing
import sqlite3
import time

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from dataflows import (
    CachePolicy, DataCoverageRequirement, Dataflows, DataRequest, DataStatus,
    Dataset, LocalCacheConfig,
)


def _frame():
    return pd.DataFrame({
        "Date": pd.to_datetime(["2026-09-14", "2026-09-15"]),
        "Open": [1.0, 1.1], "High": [1.2, 1.3], "Low": [0.9, 1.0],
        "Close": [1.1, 1.2], "Volume": [100, 120], "Amount": [105.0, 138.0],
        "Category": pd.Categorical(["a", "b"]),
    })


def _request(**kwargs):
    return DataRequest(Dataset.ETF_OHLCV, "588080.SH", "2026-09-14", "2026-09-15", "2026-09-15", **kwargs)


def _config(root, **kwargs):
    return LocalCacheConfig(root, "fixture-v1", timedelta(hours=1), **kwargs)


def _flows(config, provider):
    return Dataflows({Dataset.ETF_OHLCV: provider}, cache=config)


def test_cache_identity_dtypes_detachment_and_credential_independence(tmp_path):
    calls = []

    def provider(request):
        calls.append(request)
        return _frame(), {"vendor": "test", "extra": ("a", "b")}

    flows = _flows(_config(tmp_path), provider)
    first = flows.fetch(_request(options={"env_file": "a.env"}))
    second = flows.fetch(_request(options={"env_file": "b.env"}))
    assert first.ready and second.ready
    assert len(calls) == 1
    assert first.identity == second.identity
    assert_frame_equal(first.dataframe, second.dataframe, check_exact=True)
    first.dataframe.loc[0, "Close"] = 42
    second.dataframe.loc[0, "Close"] = 43
    assert flows.fetch(_request()).dataframe.loc[0, "Close"] == 1.1
    assert len(calls) == 1
    flows.fetch(_request(coverage=DataCoverageRequirement(minimum_rows=2)))
    assert len(calls) == 2
    _flows(replace(_config(tmp_path), namespace="fixture-v2"), provider).fetch(_request())
    assert len(calls) == 3


def test_cache_policies_expiry_failure_and_corruption(tmp_path):
    calls = []

    def provider(request):
        calls.append(request)
        return _frame(), {"vendor": "test"}

    config = _config(tmp_path)
    only = _flows(replace(config, policy=CachePolicy.CACHE_ONLY), provider)
    assert only.fetch(_request()).error.code == "CACHE_MISS"
    assert not calls
    assert _flows(config, provider).fetch(_request()).ready
    assert only.fetch(_request()).ready
    path = next(tmp_path.rglob("*.sqlite3"))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE result SET created=0")
    assert only.fetch(_request()).error.code == "CACHE_EXPIRED"
    assert _flows(config, provider).fetch(_request()).ready
    assert len(calls) == 2

    def failure(request):
        raise RuntimeError("source unavailable")

    refresh = replace(config, policy=CachePolicy.REFRESH)
    failed = _flows(refresh, failure).fetch(_request())
    assert failed.status is DataStatus.FAILED and failed.dataframe.empty
    assert only.fetch(_request()).ready
    assert _flows(refresh, provider).fetch(_request()).ready
    assert len(calls) == 3
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE result SET payload=?", (b"corrupt",))
    assert _flows(config, provider).fetch(_request()).error.code == "CACHE_CORRUPT"
    assert len(calls) == 3
    assert _flows(refresh, provider).fetch(_request()).ready


def _process_fetch(root):
    def provider(request):
        with (root / "source_calls.txt").open("a") as stream:
            stream.write("fetch\n")
        time.sleep(0.1)
        return _frame(), {"vendor": "test"}

    result = _flows(_config(root), provider).fetch(_request())
    assert result.ready, result.error
    return result.identity.content_sha256


def test_cache_deduplicates_processes_and_threads(tmp_path):
    with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_process_fetch, [tmp_path] * 6))
    assert len(set(results)) == 1
    assert (tmp_path / "source_calls.txt").read_text().splitlines() == ["fetch"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(_process_fetch, [tmp_path] * 6)) == results


def test_cache_failure_not_published_and_local_evidence_always_validated(tmp_path):
    config = _config(tmp_path)
    result = _flows(config, lambda request: (pd.DataFrame(), {})).fetch(_request())
    assert result.status is DataStatus.EMPTY
    assert _flows(replace(config, policy=CachePolicy.CACHE_ONLY), None).fetch(_request()).error.code == "CACHE_MISS"
    request = DataRequest(
        Dataset.STRATEGY_FEATURE_EVIDENCE, None, "2026-09-14", "2026-09-15", None,
        options={"repository_root": tmp_path, "source_path": "missing.csv", "source_sha256": "0" * 64},
    )
    result = Dataflows(cache=config).fetch(request)
    assert not result.ready
    assert not result.error.code.startswith("CACHE_")


def test_cache_io_and_configuration_fail_explicitly(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    result = _flows(_config(blocked), lambda request: (_frame(), {})).fetch(_request())
    assert result.error.code == "CACHE_IO_ERROR"
    with pytest.raises(TypeError, match="policy"):
        _config(tmp_path, policy="READ_THROUGH")
    with pytest.raises(ValueError, match="max_age"):
        LocalCacheConfig(tmp_path, "fixture", timedelta(0))
    with pytest.raises(TypeError, match="root"):
        LocalCacheConfig(str(tmp_path), "fixture", timedelta(hours=1))


def test_cache_lock_timeout_does_not_fetch_or_return_stale_data(tmp_path, monkeypatch):
    config = _config(tmp_path)
    def provider(request):
        return _frame(), {"vendor": "test"}

    assert _flows(config, provider).fetch(_request()).ready
    path = next(tmp_path.rglob("*.sqlite3"))
    connect = sqlite3.connect
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        monkeypatch.setattr("dataflows.cache.sqlite3.connect", lambda path, timeout: connect(path, timeout=0))
        result = _flows(config, lambda request: pytest.fail("must not fetch while locked")).fetch(_request())
        assert result.error.code == "CACHE_LOCK_TIMEOUT"
        assert result.dataframe.empty
    finally:
        connection.close()
    assert _flows(config, provider).fetch(_request()).ready


def test_host_env_file_is_forwarded_without_process_environment_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    observed = []
    flows = Dataflows(
        {Dataset.ETF_OHLCV: lambda request: (observed.append(request) or _frame(), {"vendor": "test"})},
        env_file=tmp_path / ".env",
    )
    assert flows.fetch(_request()).ready
    assert observed[0].options["env_file"] == tmp_path / ".env"
    import os
    assert "TUSHARE_TOKEN" not in os.environ
