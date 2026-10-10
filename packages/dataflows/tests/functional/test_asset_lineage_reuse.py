"""Exact-byte lineage reuse never replaces current payload or numerical checks."""

from hashlib import sha256
import pickle
import sqlite3

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset, PreparePolicy
from dataflows import asset_store, facade


def _publication(flow_factory):
    frame = pd.DataFrame({"Date": pd.date_range("2026-09-14", periods=3),
                          "OvernightRate": [1.0, 1.1, 1.2]})
    request = DataRequest(Dataset.SHIBOR_DAILY, None, "2026-09-14", "2026-09-16", None)
    flows = flow_factory({Dataset.SHIBOR_DAILY: lambda request: (
        frame, {"vendor": "fixture", "note": {"items": ["original"]}},
    )})
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready
    assert flows.fetch(request, prepared=prepared.reference).ready
    return flows, request, prepared


def test_warm_lineage_reuse_keeps_numeric_checks_and_independent_returned_values(flow_factory, monkeypatch):
    flows, request, prepared = _publication(flow_factory)
    original = facade.canonical_frame_sha256
    numeric_checks = []

    def tracked(frame):
        numeric_checks.append(True)
        return original(frame)

    def no_recursive_expansion(identity, warnings):
        pytest.fail("identical authenticated bytes must reuse their lineage digest")

    monkeypatch.setattr(facade, "canonical_frame_sha256", tracked)
    monkeypatch.setattr(asset_store, "_lineage_digest", no_recursive_expansion)
    first = flows.fetch(request, prepared=prepared.reference)
    assert first.ready and numeric_checks
    first.dataframe.loc[0, "OvernightRate"] = 999.
    first.identity.metadata["note"]["items"][0] = "changed"
    numeric_checks.clear()
    second = flows.fetch(request, prepared=prepared.reference)
    assert second.ready and numeric_checks
    assert second.dataframe.loc[0, "OvernightRate"] == 1.
    assert second.identity.metadata["note"]["items"] == ["original"]


@pytest.mark.parametrize("change", ["checksum", "numeric", "metadata", "warnings"])
def test_warm_lineage_does_not_accept_changed_current_asset(flow_factory, change):
    flows, request, prepared = _publication(flow_factory)
    with sqlite3.connect(flows._store.path) as connection:
        asset_id, payload = connection.execute("SELECT asset_id,payload FROM assets").fetchone()
        frame, identity, warnings = pickle.loads(payload)
        if change == "checksum":
            connection.execute("UPDATE assets SET payload_sha256=?", ("0" * 64,))
        else:
            if change == "numeric":
                frame.loc[0, "OvernightRate"] += 10.
            elif change == "metadata":
                identity["metadata"]["note"]["items"][0] = "changed"
            else:
                warnings = (*warnings, "changed")
            payload = pickle.dumps((frame, identity, warnings), protocol=5)
            connection.execute("UPDATE assets SET payload=?,payload_sha256=? WHERE asset_id=?",
                               (payload, sha256(payload).hexdigest(), asset_id))
    fetched = flows.fetch(request, prepared=prepared.reference)
    assert fetched.status is DataStatus.FAILED and fetched.error.code == "ASSET_CORRUPT"
    reused = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert not reused.ready and reused.items[0].error.code == "ASSET_CORRUPT"


def test_lineage_reuse_preserves_identity_metadata_normalization(flow_factory):
    flows, request, prepared = _publication(flow_factory)
    with sqlite3.connect(flows._store.path) as connection:
        asset_id, payload = connection.execute("SELECT asset_id,payload FROM assets").fetchone()
        frame, identity, warnings = pickle.loads(payload)
        original = identity["metadata"]["source_time_field"]
        identity["metadata"]["source_time_field"] = f" {original} "
        payload = pickle.dumps((frame, identity, warnings), protocol=5)
        connection.execute("UPDATE assets SET payload=?,payload_sha256=? WHERE asset_id=?",
                           (payload, sha256(payload).hexdigest(), asset_id))
    result = flows.fetch(request, prepared=prepared.reference)
    assert result.ready and result.identity.metadata["source_time_field"] == original


def test_payload_over_cache_budget_is_fully_validated_without_retention(flow_factory, monkeypatch):
    asset_store._cached_lineage_digest.cache_clear()
    monkeypatch.setattr(asset_store, "_LINEAGE_CACHE_MAX_PAYLOAD", 1)
    flows, request, prepared = _publication(flow_factory)
    assert flows.fetch(request, prepared=prepared.reference).ready
    assert asset_store._cached_lineage_digest.cache_info().currsize == 0


def test_cached_prepare_uses_its_existing_transaction_for_manifest(flow_factory, monkeypatch):
    flows, request, prepared = _publication(flow_factory)

    def no_additional_reader():
        pytest.fail("cached prepare must use its existing authenticated transaction")

    monkeypatch.setattr(flows._store, "_reader", no_additional_reader)
    result = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert result.ready and result.reference == prepared.reference
