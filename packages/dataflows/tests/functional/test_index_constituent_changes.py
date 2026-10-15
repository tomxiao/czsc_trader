"""Official-event supplements stay explicit, bounded, and reproducible offline."""

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import requests

from dataflows import (
    Dataflows, DataRequest, DataSpace, DataStatus, Dataset, PreparePolicy, ProviderConfig,
)
from dataflows import index_constituent_changes


def _request(**kwargs):
    return DataRequest(**{
        "dataset": Dataset.INDEX_CONSTITUENT_CHANGES, "symbol": "000905.SH",
        "start": "2021-06-15", "end": "2021-06-15", "required_cutoff": "2021-06-15",
        "frequency": "event", **kwargs,
    })


def _flow(tmp_path):
    return Dataflows(base_dir=tmp_path, space=DataSpace(Path("market")), providers=ProviderConfig())


def test_verified_official_event_prepares_and_restores_without_network(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail("the immutable event supplement must not access a network provider")

    monkeypatch.setattr(requests.sessions.Session, "request", deny)
    flow = _flow(tmp_path)
    request = _request()
    prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    frame = result.dataframe
    assert len(frame) == 100
    assert frame.groupby("Change").size().to_dict() == {"ADD": 50, "REMOVE": 50}
    assert frame.ConstituentSymbol.is_unique
    assert set(frame.loc[frame.Change.eq("ADD"), "ConstituentSymbol"]).issuperset({"000671.SZ", "688208.SH"})
    assert "000008.SZ" in set(frame.loc[frame.Change.eq("REMOVE"), "ConstituentSymbol"])
    assert frame.Date.eq(pd.Timestamp("2021-06-15")).all()
    assert frame.AnnouncementDate.eq(pd.Timestamp("2021-05-28")).all()
    assert frame.EffectiveAfterClose.eq(pd.Timestamp("2021-06-11T15:00:00")).all()
    assert frame.AvailableDate.eq(pd.Timestamp("2026-10-15T15:22:16.780276")).all()
    assert "Weight" not in frame
    metadata = result.identity.metadata
    assert result.identity.source == "csindex"
    assert metadata["frequency"] == "event"
    assert metadata["coverage_kind"] == "VERIFIED_EVENT_ONLY"
    assert metadata["complete_membership_history"] is False
    assert metadata["historical_publication_time_verified"] is False
    assert metadata["historical_revision_history_verified"] is False
    assert metadata["source_attachment_sha256"] == "07e8c58d5f02cbaaf5e5b4a98f7c541208218d7a3de9b9627fbff37f31770a07"
    assert metadata["source_notice_url"].endswith("id=12470")
    assert metadata["source_calendar_url"].endswith("c_20210603_5481611.shtml")
    assert metadata["availability_time_field"] == "AvailableDate"
    assert "captured official sources" in metadata["available_at"]

    offline = Dataflows(base_dir=tmp_path, space=DataSpace(Path("market")), providers=ProviderConfig({}))
    restored = offline.fetch(request, prepared=prepared.reference)
    assert restored.ready, restored.error
    pd.testing.assert_frame_equal(restored.dataframe, frame)
    result.dataframe.loc[0, "Change"] = "REMOVE"
    again = offline.fetch(request, prepared=prepared.reference)
    pd.testing.assert_frame_equal(again.dataframe, restored.dataframe)
    assert flow.prepare((request,), policy=PreparePolicy.REUSE).reference == prepared.reference


@pytest.mark.parametrize("start,end", [
    ("2021-06-11", "2021-06-15"),
    ("2021-06-16", "2021-06-16"),
])
def test_unknown_event_windows_are_incomplete_not_certified_empty(tmp_path, start, end):
    prepared = _flow(tmp_path).prepare(
        (_request(start=start, end=end, required_cutoff=None),), policy=PreparePolicy.REFRESH,
    )
    assert not prepared.ready and prepared.reference is None
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE
    assert item.identity is None
    assert item.error.code == "INDEX_CHANGE_COVERAGE_UNVERIFIED"
    assert item.error.retryable is False
    assert "2021-06-15" in item.error.context["verified_event_sessions"]
    assert start not in item.error.context["verified_event_sessions"]


def test_other_index_cannot_consume_the_csi500_patch(tmp_path):
    prepared = _flow(tmp_path).prepare((_request(symbol="000300.SH"),), policy=PreparePolicy.REFRESH)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"


@pytest.mark.parametrize("arguments", [
    {"frequency": "daily"},
    {"frequency": "snapshot"},
    {"symbol": None},
    {"start": "2021-06-15T09:30:00"},
])
def test_event_request_rejects_daily_and_ambiguous_time_semantics(arguments):
    with pytest.raises(ValueError):
        _request(**arguments)


@pytest.mark.parametrize("defect", ["direction", "availability", "coverage", "source_hash", "missing_row"])
def test_corrupt_event_or_provenance_never_publishes_ready(tmp_path, monkeypatch, defect):
    original = index_constituent_changes.fetch_index_constituent_changes

    def corrupt(request):
        frame, metadata = original(request)
        if defect == "direction":
            frame.loc[0, "Change"] = "REMOVE"
        elif defect == "availability":
            frame["AvailableDate"] = pd.Timestamp("2021-05-28")
        elif defect == "coverage":
            metadata["complete_membership_history"] = True
        elif defect == "source_hash":
            metadata["source_attachment_sha256"] = "0" * 64
        else:
            frame = frame.iloc[:-1].reset_index(drop=True)
        return frame, metadata

    monkeypatch.setattr(index_constituent_changes, "fetch_index_constituent_changes", corrupt)
    prepared = _flow(tmp_path).prepare((_request(),), policy=PreparePolicy.REFRESH)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"
    assert item.identity is None


def test_transcription_hash_rejects_changed_catalog_before_publication(tmp_path, monkeypatch):
    patch = next(patch for patch in index_constituent_changes.PATCHES if patch.first_session == "2021-06-15")
    changed = replace(patch, added=(("000001.SZ", "changed"), *patch.added[1:]))
    monkeypatch.setattr(index_constituent_changes, "PATCHES", tuple(
        changed if item.patch_id == patch.patch_id else item for item in index_constituent_changes.PATCHES
    ))
    prepared = _flow(tmp_path).prepare((_request(),), policy=PreparePolicy.REFRESH)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert "pinned hash" in item.error.message


def test_multiple_verified_events_publish_together_without_certifying_the_intervening_dates(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail("verified event patches must remain offline")

    monkeypatch.setattr(requests.sessions.Session, "request", deny)
    cases = [
        ("2019-12-16", 50, "2019-12-02", None),
        ("2020-06-15", 50, "2020-06-01", None),
        ("2020-12-14", 50, "2020-11-27", None),
        ("2021-06-15", 50, "2021-05-28", "2021-06-11T15:00:00"),
        ("2021-12-13", 50, "2021-11-26", "2021-12-10T15:00:00"),
        ("2022-06-13", 50, "2022-05-27", "2022-06-10T15:00:00"),
        ("2022-12-12", 50, "2022-11-25", "2022-12-09T15:00:00"),
        ("2026-01-12", 1, "2026-01-06", "2026-01-09T15:00:00"),
        ("2026-06-15", 50, "2026-05-29", "2026-06-12T15:00:00"),
    ]
    requests_ = tuple(_request(start=day, end=day, required_cutoff=day) for day, *_ in cases)
    flow = _flow(tmp_path)
    prepared = flow.prepare(requests_, policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    offline = Dataflows(base_dir=tmp_path, space=DataSpace(Path("market")), providers=ProviderConfig({}))
    total = 0
    for request, (day, count, announcement, close) in zip(requests_, cases, strict=True):
        result = offline.fetch(request, prepared=prepared.reference)
        assert result.ready, result.error
        frame, metadata = result.dataframe, result.identity.metadata
        assert len(frame) == 2 * count
        total += len(frame)
        assert frame.groupby("Change").size().to_dict() == {"ADD": count, "REMOVE": count}
        assert frame.Date.eq(pd.Timestamp(day)).all()
        assert frame.AnnouncementDate.eq(pd.Timestamp(announcement)).all()
        if close is None:
            assert frame.EffectiveAfterClose.isna().all()
            assert metadata["effective_boundary_kind"] == "FIRST_SESSION_STATED"
            assert metadata["source_calendar_url"] is None
            assert metadata["source_calendar_sha256"] is None
        else:
            assert frame.EffectiveAfterClose.eq(pd.Timestamp(close)).all()
            assert metadata["effective_boundary_kind"] == "AFTER_CLOSE_STATED"
            if day in {"2021-12-13", "2022-06-13", "2022-12-12"}:
                assert metadata["source_calendar_url"].startswith("tushare://trade_cal?exchange=SSE&")
                assert len(metadata["source_calendar_sha256"]) == 64
        assert frame.AvailableDate.dt.year.eq(2026).all()
        assert metadata["replacement_count"] == count
        assert metadata["verified_event_sessions"] == [day]
        assert metadata["coverage_kind"] == "VERIFIED_EVENT_ONLY"
        assert metadata["complete_membership_history"] is False
        assert metadata["historical_publication_time_verified"] is False
    assert total == 802
    result = flow.prepare((_request(start="2019-12-16", end="2026-06-15", required_cutoff=None),),
                          policy=PreparePolicy.REUSE)
    assert not result.ready and result.reference is None
    assert result.items[0].status is DataStatus.INCOMPLETE


def test_duplicate_catalog_session_fails_instead_of_selecting_a_patch(tmp_path, monkeypatch):
    patch = next(p for p in index_constituent_changes.PATCHES if p.first_session == "2021-06-15")
    monkeypatch.setattr(index_constituent_changes, "PATCHES", (*index_constituent_changes.PATCHES, patch))
    prepared = _flow(tmp_path).prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED
    assert "multiple" in prepared.items[0].error.message
