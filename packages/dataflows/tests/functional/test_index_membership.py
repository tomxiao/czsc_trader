"""Public daily membership reconstruction keeps source and event boundaries."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from dataflows import Dataflows, DataRequest, DataSpace, DataStatus, Dataset, PreparePolicy, ProviderConfig
from dataflows._index_change_patch import _IndexChangePatch


_STABLE = [f"{number:06d}.SZ" for number in range(1, 500)]
_A, _B, _C = "600001.SH", "600002.SH", "600003.SH"
_OBSERVED = "2026-10-15T00:00:00+00:00"


def _members(last):
    return [*_STABLE, last]


def _event(first="2020-01-13", notice=1, announcement="2020-01-06"):
    return {"first_session": first, "announcement_date": announcement,
            "effective_after_close": (pd.Timestamp(first) - pd.Timedelta(days=3)).isoformat(),
            "notice_id": notice, "title": "Synthetic verified adjustment",
            "notice_url": f"https://www.csindex.com.cn/#/about/newsDetail?id={notice}",
            "notice_sha256": "a" * 64, "observed_at_utc": _OBSERVED}


def _patch(event, removed, added):
    changes = {"added": ((added, "added"),), "removed": ((removed, "removed"),)}
    digest = sha256(json.dumps(changes, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return _IndexChangePatch(
        patch_id=f"synthetic-{event['notice_id']}", version=1, symbol="000905.SH",
        notice_id=event["notice_id"], notice_url=event["notice_url"], notice_sha256="a" * 64,
        attachment_url="https://oss-ch.csindex.com.cn/synthetic.xlsx", attachment_sha256="b" * 64,
        calendar_url=None, calendar_sha256=None, observed_at_utc="2026-10-15T02:00:00+00:00",
        announcement_date=event["announcement_date"], effective_after_close=event["effective_after_close"],
        first_session=event["first_session"], added=changes["added"], removed=changes["removed"],
        records_sha256=digest, replacement_count=1,
    )


class _Pro:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.weight_calls = []
        self.calendar_calls = []
        self.drop_calendar_day = False

    def index_weight(self, **kwargs):
        self.weight_calls.append(kwargs)
        first, last = pd.Timestamp(kwargs["start_date"]), pd.Timestamp(kwargs["end_date"])
        rows = [{"index_code": "000905.SH", "con_code": symbol,
                 "trade_date": pd.Timestamp(day).strftime("%Y%m%d"), "weight": 0.2}
                for day, members in self.snapshots.items() if first <= pd.Timestamp(day) <= last
                for symbol in members]
        return pd.DataFrame(rows, columns=["index_code", "con_code", "trade_date", "weight"])[
            kwargs["fields"].split(",")]

    def trade_cal(self, **kwargs):
        self.calendar_calls.append(kwargs)
        days = pd.date_range(pd.Timestamp(kwargs["start_date"]), pd.Timestamp(kwargs["end_date"]))
        rows = [{"exchange": "SSE", "cal_date": day.strftime("%Y%m%d"),
                 "is_open": int(day.weekday() < 5),
                 "pretrade_date": (day - pd.offsets.BDay()).strftime("%Y%m%d")}
                for day in days]
        frame = pd.DataFrame(rows)
        return frame.iloc[1:].reset_index(drop=True) if self.drop_calendar_day else frame


@pytest.fixture
def sources(monkeypatch):
    from dataflows import _csi500_effective_dates, index_membership

    def install(*, events=(), snapshots=None, patches=(), complete=True, scope_review=None):
        catalog = {"coverage_start": "2019-12-01", "coverage_end": "2020-03-31",
                   "coverage_complete": complete, "unresolved_notices": [] if complete else ["unverified"],
                   "source_scope_review": {"complete": True} if scope_review is None else scope_review,
                   "events": list(events)}
        monkeypatch.setattr(_csi500_effective_dates, "CATALOG", catalog)
        monkeypatch.setattr(_csi500_effective_dates, "CATALOG_SHA256", index_membership._json_hash(catalog))
        monkeypatch.setattr(index_membership, "PATCHES", tuple(patches))
        monkeypatch.setattr(index_membership, "_now", lambda: _OBSERVED)
        pro = _Pro({"2019-12-31": _members(_A), "2020-01-31": _members(_B)}
                   if snapshots is None else snapshots)
        monkeypatch.setattr(index_membership, "get_tushare_pro", lambda _: pro)
        return pro

    return install


def _request(**kwargs):
    return DataRequest(**{"dataset": Dataset.INDEX_CONSTITUENTS_DAILY, "symbol": "000905.SH",
                          "start": "2020-01-01", "end": "2020-01-31", "required_cutoff": None,
                          "frequency": "daily", **kwargs})


def _flow(tmp_path, *, offline=False):
    return Dataflows(base_dir=tmp_path, space=DataSpace(Path("market")),
                     providers=ProviderConfig({}) if offline else ProviderConfig())


def _prepare(tmp_path, request=None):
    flow = _flow(tmp_path)
    request = _request() if request is None else request
    prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    return flow, request, prepared


def test_actual_effective_session_switches_and_offline_fetch_keeps_evidence(tmp_path, monkeypatch, sources):
    pro = sources(events=[_event()])
    daily = _request()
    events = _request(dataset=Dataset.INDEX_CONSTITUENT_EVENTS, frequency="event")
    flow = _flow(tmp_path)
    prepared = flow.prepare((daily, events), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(daily, prepared=prepared.reference)
    assert result.ready, result.error
    frame = result.dataframe
    assert frame.groupby("Date").size().eq(500).all()
    assert not frame.Date.dt.weekday.ge(5).any()
    assert _A in set(frame.loc[frame.Date.eq("2020-01-06"), "ConstituentSymbol"])
    assert _A in set(frame.loc[frame.Date.eq("2020-01-10"), "ConstituentSymbol"])
    assert _B in set(frame.loc[frame.Date.eq("2020-01-13"), "ConstituentSymbol"])
    assert _A not in set(frame.loc[frame.Date.ge("2020-01-13"), "ConstituentSymbol"])
    assert frame.AvailableDate.eq(pd.Timestamp("2026-10-15T08:00:00")).all()
    assert "Weight" not in frame
    metadata = result.identity.metadata
    assert result.identity.source == "dfls"
    assert metadata["patched_session_count"] == 0
    assert metadata["historical_publication_time_verified"] is False
    assert {item["source"] for item in metadata["reconstruction_segments"]} == {"TUSHARE_SNAPSHOT"}
    event_result = flow.fetch(events, prepared=prepared.reference)
    assert event_result.ready, event_result.error
    assert event_result.dataframe.Date.tolist() == [pd.Timestamp("2020-01-13")]
    assert len(pro.weight_calls) == 2 and len(pro.calendar_calls) == 1

    def deny(*args, **kwargs):
        pytest.fail("prepared membership fetch must not acquire sources")

    monkeypatch.setattr(pro, "index_weight", deny)
    monkeypatch.setattr(pro, "trade_cal", deny)
    restored = _flow(tmp_path, offline=True).fetch(daily, prepared=prepared.reference)
    assert restored.ready, restored.error
    pd.testing.assert_frame_equal(restored.dataframe, frame)


@pytest.mark.parametrize("weight", ["missing", None, "invalid", float("inf")])
def test_daily_membership_neither_requires_nor_hashes_weights(tmp_path, monkeypatch, sources, weight):
    from dataflows import index_membership

    pro = sources(events=[_event()])
    original = pro.index_weight
    raw_sources = []

    def snapshots(**kwargs):
        assert kwargs["fields"] == "index_code,con_code,trade_date"
        raw = original(**kwargs)
        raw_sources.append(raw.copy())
        if weight != "missing":
            # Some clients may return unrequested columns; these are not membership evidence.
            raw["weight"] = weight
        return raw

    monkeypatch.setattr(pro, "index_weight", snapshots)
    flow, request, prepared = _prepare(tmp_path)
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert set(result.dataframe.columns) == {"Date", "ConstituentSymbol", "AvailableDate", "SourceSnapshotDate"}
    assert result.dataframe.groupby("Date").size().eq(500).all()
    assert [query["sha256"] for query in result.identity.metadata["snapshot_queries"]] == [
        index_membership._frame_hash(raw) for raw in raw_sources]


@pytest.mark.parametrize("dataset,frequency", [
    (Dataset.INDEX_CONSTITUENTS_DAILY, "daily"), (Dataset.INDEX_CONSTITUENT_EVENTS, "event"),
])
def test_unreviewed_announcement_scope_is_incomplete_before_vendor_queries(tmp_path, sources, dataset, frequency):
    pending = [13334, 13716]
    pro = sources(events=[_event()], scope_review={"complete": False, "pending_notice_ids": pending})
    _, _, prepared = _prepare(tmp_path, _request(dataset=dataset, frequency=frequency))
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE and prepared.reference is None
    assert item.error.context["pending_notice_ids"] == pending
    assert not pro.weight_calls and not pro.calendar_calls


@pytest.mark.parametrize("dataset,frequency", [
    (Dataset.INDEX_CONSTITUENTS_DAILY, "daily"), (Dataset.INDEX_CONSTITUENT_EVENTS, "event"),
])
def test_scope_review_time_bounds_published_availability(tmp_path, sources, dataset, frequency):
    sources(events=[_event()], scope_review={"complete": True, "observed_at_utc": "2026-10-15T03:00:00+00:00"})
    flow, request, prepared = _prepare(tmp_path, _request(dataset=dataset, frequency=frequency))
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert result.dataframe.AvailableDate.eq(pd.Timestamp("2026-10-15T11:00:00")).all()


def test_missing_month_with_no_event_uses_unchanged_segment_without_patch(tmp_path, monkeypatch, sources):
    from dataflows import index_membership

    sources(snapshots={"2019-12-31": _members(_A), "2020-02-28": _members(_A)})
    # Later same-segment reconciliation must contribute to AvailableDate.
    observations = iter([_OBSERVED, "2026-10-15T01:00:00+00:00",
                         "2026-10-15T03:00:00+00:00", _OBSERVED])
    monkeypatch.setattr(index_membership, "_now", lambda: next(observations))
    flow, request, prepared = _prepare(tmp_path, _request(end="2020-02-28"))
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert set(result.dataframe.ConstituentSymbol) == set(_members(_A))
    assert result.dataframe.AvailableDate.eq(pd.Timestamp("2026-10-15T11:00:00")).all()
    assert result.identity.metadata["missing_snapshot_months"] == ["2020-01"]
    assert result.identity.metadata["patched_session_count"] == 0
    assert len(result.identity.metadata["reconstruction_segments"]) == 1


def test_two_events_in_one_month_require_a_middle_membership_anchor(tmp_path, sources):
    events = [_event(), _event("2020-01-20", 2, "2020-01-16")]
    sources(events=events, snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)})
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE and prepared.reference is None
    assert item.error.context["missing_session_start"] == "2020-01-13"
    assert item.error.context["missing_session_end"] == "2020-01-17"
    assert set(item.error.context["notice_ids"]) == {"1", "2"}


@pytest.mark.parametrize("direction", ["forward", "reverse"])
def test_explicit_patch_fills_only_the_missing_middle_segment(tmp_path, sources, direction):
    first, second = _event(), _event("2020-01-20", 2, "2020-01-16")
    patch = _patch(first, _A, _B) if direction == "forward" else _patch(second, _B, _C)
    sources(events=[first, second], snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)},
            patches=[patch])
    flow, request, prepared = _prepare(tmp_path)
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    frame = result.dataframe
    assert _B in set(frame.loc[frame.Date.eq("2020-01-13"), "ConstituentSymbol"])
    assert _C in set(frame.loc[frame.Date.eq("2020-01-20"), "ConstituentSymbol"])
    metadata = result.identity.metadata
    assert metadata["patched_session_count"] == 5
    segments = metadata["reconstruction_segments"]
    assert [item["source"] for item in segments] == ["TUSHARE_SNAPSHOT", "OFFICIAL_CHANGE_PATCH", "TUSHARE_SNAPSHOT"]
    assert segments[1]["patch_ids"] == [patch.patch_id]
    middle = frame.loc[frame.Date.between("2020-01-13", "2020-01-17")]
    assert middle.AvailableDate.eq(pd.Timestamp("2026-10-15T10:00:00")).all()
    assert segments[0]["patch_ids"] == segments[2]["patch_ids"] == []


def test_same_segment_constituent_change_without_event_is_incomplete(tmp_path, sources):
    sources()
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE and prepared.reference is None
    assert "without an identified effective event" in item.error.message


def test_missing_calendar_date_is_incomplete(tmp_path, sources):
    pro = sources(events=[_event()])
    pro.drop_calendar_day = True
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE and prepared.reference is None


@pytest.mark.parametrize("members", [_members(_A)[:-1], [*_STABLE, "bad-code"]])
def test_invalid_snapshot_never_publishes_ready(tmp_path, sources, members):
    sources(events=[_event()], snapshots={"2019-12-31": members, "2020-01-31": _members(_B)})
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"


def test_patch_contradicting_a_source_anchor_is_incomplete(tmp_path, sources):
    first, second = _event(), _event("2020-01-20", 2, "2020-01-16")
    patches = [_patch(first, _A, _B), _patch(second, _B, "600004.SH")]
    sources(events=[first, second], snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)},
            patches=patches)
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE and prepared.reference is None


@pytest.mark.parametrize("arguments,complete", [({"start": "2019-11-01"}, True), ({}, False)])
def test_uncertified_catalog_range_is_incomplete_before_vendor_queries(tmp_path, sources, arguments, complete):
    pro = sources(events=[_event()], complete=complete)
    _, _, prepared = _prepare(tmp_path, _request(**arguments))
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE and prepared.reference is None
    assert not pro.weight_calls and not pro.calendar_calls


def test_catalog_hash_tampering_never_publishes_ready(tmp_path, monkeypatch, sources):
    from dataflows import _csi500_effective_dates

    pro = sources(events=[_event()])
    monkeypatch.setattr(_csi500_effective_dates, "CATALOG_SHA256", "f" * 64)
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert not pro.weight_calls


def test_non_session_effective_date_is_rejected_instead_of_switching_on_monday(tmp_path, sources):
    pro = sources(events=[_event("2020-01-11")])
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"
    assert not pro.weight_calls


@pytest.mark.parametrize("arguments", [
    {"frequency": "event"}, {"symbol": None}, {"start": "2020-01-01T09:30:00"}, {"parameters": {}},
])
def test_daily_request_uses_strong_parameters(arguments):
    with pytest.raises((ValueError, TypeError)):
        _request(**arguments)


def test_patch_records_hash_tampering_is_a_contract_failure(tmp_path, sources):
    first, second = _event(), _event("2020-01-20", 2, "2020-01-16")
    patch = replace(_patch(first, _A, _B), records_sha256="f" * 64)
    sources(events=[first, second], snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)},
            patches=[patch])
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None


@pytest.mark.parametrize("defect", ["availability", "snapshot_hash", "invented_patch", "wrong_event_patch", "patch_count"])
def test_provider_cannot_publish_backdated_or_fabricated_segment_evidence(tmp_path, monkeypatch, sources, defect):
    from dataflows import index_membership

    first, second = _event(), _event("2020-01-20", 2, "2020-01-16")
    first_patch, second_patch = _patch(first, _A, _B), _patch(second, _B, _C)
    sources(events=[first, second], snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)},
            patches=[first_patch, second_patch])
    original = index_membership.fetch_index_constituents_daily

    def corrupt(request, **kwargs):
        frame, metadata = original(request, **kwargs)
        middle = metadata["reconstruction_segments"][1]
        if defect == "availability":
            frame["AvailableDate"] = pd.Timestamp("2020-01-01")
            for segment in metadata["reconstruction_segments"]:
                segment["available_date"] = "2020-01-01T00:00:00"
        elif defect == "snapshot_hash":
            middle["source_snapshot_sha256"] = "f" * 64
        elif defect == "invented_patch":
            middle["patch_ids"] = ["invented-patch"]
        elif defect == "wrong_event_patch":
            middle["patch_ids"] = [second_patch.patch_id]
            middle["patch_records_sha256"] = [second_patch.records_sha256]
        else:
            metadata["patched_session_count"] += 1
        return frame, metadata

    monkeypatch.setattr(index_membership, "fetch_index_constituents_daily", corrupt)
    _, _, prepared = _prepare(tmp_path)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"


def test_publication_availability_includes_catalog_and_only_actually_used_patches(tmp_path, sources):
    event = _event()
    event["observed_at_utc"] = "2026-10-15T04:00:00+00:00"
    # A valid supplement is unused because both event segments have snapshots.
    unused = replace(_patch(event, _A, _B), observed_at_utc="2026-10-15T05:00:00+00:00")
    sources(events=[event], patches=[unused])
    flow, request, prepared = _prepare(tmp_path)
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert result.dataframe.AvailableDate.eq(pd.Timestamp("2026-10-15T12:00:00")).all()
    assert result.identity.metadata["official_patch_sources"] == []
