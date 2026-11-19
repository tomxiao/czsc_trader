"""Request lookup stays bounded as immutable preparation history grows."""

from datetime import date, timedelta
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from dataflows import Dataflows, DataRequest, DataSpace, Dataset, PreparePolicy, ProviderBinding, ProviderConfig
from dataflows.contract import DATA_CONTRACT_VERSION


def test_new_request_does_not_decode_unrelated_preparations(tmp_path, monkeypatch):
    def provider(request):
        return pd.DataFrame({'Date': pd.to_datetime([request.start]), 'OvernightRate': [1.]}), {'vendor': 'fixture'}

    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('space')),
        providers=ProviderConfig(bindings={Dataset.SHIBOR_DAILY: ProviderBinding('fixture', 'v1', provider)}))
    for index in range(12):
        day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
        result = flows.prepare((DataRequest(Dataset.SHIBOR_DAILY, None, day, day, None),), policy=PreparePolicy.REUSE)
        assert result.ready

    def unrelated_manifest(*args, **kwargs):
        raise AssertionError('new request decoded unrelated immutable preparation')

    monkeypatch.setattr(flows._store, 'load_preparation', unrelated_manifest)
    fresh = flows.prepare((DataRequest(Dataset.SHIBOR_DAILY, None, '2026-02-02', '2026-02-02', None),),
                         policy=PreparePolicy.REUSE)
    assert fresh.ready


@pytest.mark.parametrize('rebuild', ['clear', 'drop'])
def test_rebuilt_lookup_preserves_historical_contract_conflict(tmp_path, rebuild):
    def provider(request):
        return pd.DataFrame({'Date': pd.to_datetime([request.start]), 'OvernightRate': [1.]}), {'vendor': 'fixture'}

    configuration = ProviderConfig(bindings={Dataset.SHIBOR_DAILY: ProviderBinding('fixture', 'v1', provider)})
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('space')), providers=configuration)
    flows._contract_version = DATA_CONTRACT_VERSION - 1
    request = DataRequest(Dataset.SHIBOR_DAILY, None, '2026-01-01', '2026-01-01', None)
    old = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert old.ready
    with sqlite3.connect(tmp_path / 'space/assets.sqlite3') as connection:
        connection.execute('DELETE FROM asset_lookup')
        connection.execute('DROP TABLE preparation_lookup' if rebuild == 'drop' else 'DELETE FROM preparation_lookup')

    def forbidden(request):
        raise AssertionError('historical contract conflict must be reported before supplier acquisition')

    current = Dataflows(base_dir=tmp_path, space=DataSpace(Path('space')),
        providers=ProviderConfig(bindings={Dataset.SHIBOR_DAILY: ProviderBinding('fixture', 'v2', forbidden)}))
    rejected = current.prepare((request,), policy=PreparePolicy.REUSE)
    assert not rejected.ready
    assert rejected.items[0].error.code == 'DATA_CONTRACT_VERSION_MISMATCH'
    with sqlite3.connect(tmp_path / 'space/assets.sqlite3') as connection:
        assert connection.execute('SELECT COUNT(*) FROM preparations').fetchone()[0] == 1


def test_older_writer_publications_are_incrementally_indexed(tmp_path, monkeypatch):
    def provider(request):
        return pd.DataFrame({'Date': pd.to_datetime([request.start]), 'OvernightRate': [1.]}), {'vendor': 'fixture'}

    configuration = ProviderConfig(bindings={Dataset.SHIBOR_DAILY: ProviderBinding('fixture', 'v1', provider)})
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('space')), providers=configuration)
    first = DataRequest(Dataset.SHIBOR_DAILY, None, '2026-01-01', '2026-01-01', None)
    assert flows.prepare((first,), policy=PreparePolicy.REUSE).ready
    with sqlite3.connect(tmp_path / 'space/assets.sqlite3') as connection:
        original_cursor = connection.execute(
            "SELECT preparation_id FROM preparation_lookup WHERE request_key='contract-index:v1'",
        ).fetchone()[0]
    second = DataRequest(Dataset.SHIBOR_DAILY, None, '2026-01-02', '2026-01-02', None)
    flows._contract_version = DATA_CONTRACT_VERSION - 1
    assert flows.prepare((second,), policy=PreparePolicy.REFRESH).ready
    with sqlite3.connect(tmp_path / 'space/assets.sqlite3') as connection:
        # An older writer retains the existing lookup rows but adds a publication
        # without maintaining the new contract index or its high-water cursor.
        connection.execute("DELETE FROM preparation_lookup WHERE request_key LIKE 'contract:%' AND preparation_id<>?",
                           (original_cursor,))
        connection.execute("UPDATE preparation_lookup SET preparation_id=? WHERE request_key='contract-index:v1'",
                           (original_cursor,))
        connection.execute('DELETE FROM asset_lookup')
        connection.execute("DELETE FROM preparation_lookup WHERE request_key NOT LIKE 'contract%' ")
    current = Dataflows(base_dir=tmp_path, space=DataSpace(Path('space')), providers=configuration)
    calls = []
    original = current._store.load_preparation
    def load(reference, **kwargs):
        calls.append(reference.preparation_id)
        return original(reference, **kwargs)
    monkeypatch.setattr(current._store, 'load_preparation', load)
    rejected = current.prepare((second,), policy=PreparePolicy.REUSE)
    assert rejected.items[0].error.code == 'DATA_CONTRACT_VERSION_MISMATCH'
    assert len(set(calls)) == 1
