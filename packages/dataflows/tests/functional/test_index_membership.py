"""Public daily membership reconstruction keeps source and event boundaries."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from dataflows import Dataflows, DataRequest, DataSpace, DataStatus, Dataset, PreparePolicy, ProviderConfig
from dataflows._index_change_patch import _IndexChangePatch
from dataflows.errors import DataContractError, IncompleteDataError
from dataflows.index_membership import fetch_index_constituents_daily, validate_index_membership


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
        self.closed_days = set()

    def index_weight(self, **kwargs):
        self.weight_calls.append(kwargs)
        assert 'start_date' not in kwargs and 'end_date' not in kwargs
        target = pd.Timestamp(kwargs["trade_date"])
        rows = [{"index_code": "000905.SH", "con_code": symbol,
                 "trade_date": pd.Timestamp(day).strftime("%Y%m%d"), "weight": 0.2}
                for day, members in self.snapshots.items() if pd.Timestamp(day) == target
                for symbol in members]
        return pd.DataFrame(rows, columns=["index_code", "con_code", "trade_date", "weight"])[
            kwargs["fields"].split(",")]

    def trade_cal(self, **kwargs):
        self.calendar_calls.append(kwargs)
        days = pd.date_range(pd.Timestamp(kwargs["start_date"]), pd.Timestamp(kwargs["end_date"]))
        rows = [{"exchange": "SSE", "cal_date": day.strftime("%Y%m%d"),
                 "is_open": int(day.weekday() < 5 and day.strftime('%Y%m%d') not in self.closed_days),
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
    # Keep the session before the first event, all five middle sessions, and the
    # second event. Only the full-month integration case needs the other dates.
    return DataRequest(**{"dataset": Dataset.INDEX_CONSTITUENTS_DAILY, "symbol": "000905.SH",
                          "start": "2020-01-10", "end": "2020-01-20", "required_cutoff": None,
                          "frequency": "daily", **kwargs})


@pytest.fixture
def membership_root(tmp_path, empty_space_factory):
    # Space creation is owned by test_data_space; this suite validates membership.
    empty_space_factory("market")
    return tmp_path


def _flow(membership_root, *, offline=False):
    return Dataflows(base_dir=membership_root, space=DataSpace(Path("market")),
                     providers=ProviderConfig({}) if offline else ProviderConfig())


def _prepare(membership_root, request=None):
    flow = _flow(membership_root)
    request = _request() if request is None else request
    prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    return flow, request, prepared


def _source_membership(request=None):
    request = _request() if request is None else request
    frame, metadata = fetch_index_constituents_daily(request)
    validate_index_membership(frame, request, metadata)
    return frame, metadata


@pytest.fixture(scope="module")
def validated_membership_facts():
    """Build each real source baseline once; mutations own independent copies."""
    baselines = {}

    def copy_facts(key, request):
        if key not in baselines:
            baselines[key] = _source_membership(request)
        frame, metadata = baselines[key]
        return frame.copy(deep=True), deepcopy(metadata)

    return copy_facts


def test_DFLS_27_C01_actual_effective_session_switches_and_offline_fetch_keeps_evidence(membership_root, monkeypatch, sources):
    pro = sources(events=[_event()])
    daily = _request(start="2020-01-01", end="2020-01-31")
    events = _request(dataset=Dataset.INDEX_CONSTITUENT_EVENTS, frequency="event",
                      start="2020-01-01", end="2020-01-31")
    flow = _flow(membership_root)
    prepared = flow.prepare((daily, events), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(daily, prepared=prepared.reference)
    assert result.ready, result.error
    frame = result.dataframe
    assert frame.Date.nunique() == 23
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
    assert [call['trade_date'] for call in pro.weight_calls] == ['20191231', '20200131']
    assert [query['trade_date'] for query in metadata['snapshot_queries']] == ['20191231', '20200131']
    assert all(query['index_code'] == '000905.SH' for query in metadata['snapshot_queries'])

    def deny(*args, **kwargs):
        pytest.fail("prepared membership fetch must not acquire sources")

    monkeypatch.setattr(pro, "index_weight", deny)
    monkeypatch.setattr(pro, "trade_cal", deny)
    # Previously published monthly-range provenance remains readable offline.
    from dataflows.index_membership import validate_index_membership
    legacy_metadata = deepcopy(dict(metadata))
    legacy_metadata.pop('snapshot_query_contract')
    for query in legacy_metadata['snapshot_queries']:
        query.pop('index_code')
        query.pop('trade_date')
    validate_index_membership(frame, daily, legacy_metadata)
    restored = _flow(membership_root, offline=True).fetch(daily, prepared=prepared.reference)
    assert restored.ready, restored.error
    pd.testing.assert_frame_equal(restored.dataframe, frame)




@pytest.mark.parametrize('defect', [
    'missing_date',
    'wrong_index',
], ids=['DFLS-28-C01', 'DFLS-28-C02'])
def test_new_daily_snapshot_metadata_requires_exact_query_identity(sources, validated_membership_facts, defect):
    from dataflows.index_membership import validate_index_membership
    sources(events=[_event()])
    request = _request()
    frame, metadata = validated_membership_facts("single-event", request)
    query = metadata['snapshot_queries'][0]
    if defect == 'wrong_date':
        query['trade_date'] = '20191230'
    elif defect == 'missing_date':
        query.pop('trade_date')
    elif defect == 'wrong_index':
        query['index_code'] = '000300.SH'
    else:
        query.pop('trade_date')
        query.pop('index_code')
    with pytest.raises(DataContractError):
        validate_index_membership(frame, request, metadata)


def test_DFLS_27_C06_daily_membership_neither_requires_nor_hashes_weights(monkeypatch, sources):
    from dataflows import index_membership

    pro = sources(events=[_event()])
    original = pro.index_weight
    raw_sources = []

    def snapshots(**kwargs):
        assert kwargs["fields"] == "index_code,con_code,trade_date"
        raw = original(**kwargs)
        raw_sources.append(raw.copy())
        # Missing and malformed unrequested weights are equally outside the
        # membership contract. Exercise both source shapes in one reconstruction.
        if len(raw_sources) == 2:
            raw["weight"] = "invalid"
        return raw

    monkeypatch.setattr(pro, "index_weight", snapshots)
    request = _request(end="2020-01-13")
    frame, metadata = index_membership.fetch_index_constituents_daily(request)
    index_membership.validate_index_membership(frame, request, metadata)
    assert set(frame.columns) == {"Date", "ConstituentSymbol", "AvailableDate", "SourceSnapshotDate"}
    assert frame.Date.nunique() == 2
    assert frame.groupby("Date").size().eq(500).all()
    assert [query["sha256"] for query in metadata["snapshot_queries"]] == [
        index_membership._frame_hash(raw) for raw in raw_sources]








def test_DFLS_27_C02_two_events_in_one_month_require_a_middle_membership_anchor(membership_root, sources):
    events = [_event(), _event("2020-01-20", 2, "2020-01-16")]
    sources(events=events, snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)})
    _, _, prepared = _prepare(membership_root)
    item, = prepared.items
    assert item.status is DataStatus.INCOMPLETE and prepared.reference is None
    assert item.error.context["missing_session_start"] == "2020-01-13"
    assert item.error.context["missing_session_end"] == "2020-01-17"
    assert set(item.error.context["notice_ids"]) == {"1", "2"}


@pytest.mark.parametrize("direction", [
    "forward",
    "reverse",
], ids=['DFLS-27-C03', 'DFLS-27-C04'])
def test_explicit_patch_fills_only_the_missing_middle_segment(membership_root, sources, direction):
    first, second = _event(), _event("2020-01-20", 2, "2020-01-16")
    patch = _patch(first, _A, _B) if direction == "forward" else _patch(second, _B, _C)
    sources(events=[first, second], snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)},
            patches=[patch])
    flow, request, prepared = _prepare(membership_root)
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


def test_DFLS_27_C05_same_segment_constituent_change_without_event_is_incomplete(sources):
    sources()
    with pytest.raises(IncompleteDataError, match="without an identified effective event"):
        _source_membership()


















@pytest.mark.parametrize("defect", [
    "invented_patch",
], ids=['DFLS-28-C04'])
def test_provider_segment_evidence_validator_rejects_fabrication(sources, validated_membership_facts, defect):
    from dataflows import index_membership

    first, second = _event(), _event("2020-01-20", 2, "2020-01-16")
    first_patch, second_patch = _patch(first, _A, _B), _patch(second, _B, _C)
    sources(events=[first, second], snapshots={"2019-12-31": _members(_A), "2020-01-31": _members(_C)},
            patches=[first_patch, second_patch])
    request = _request()
    frame, metadata = validated_membership_facts("middle-patch", request)
    middle = metadata["reconstruction_segments"][1]
    if defect == "snapshot_hash":
        middle["source_snapshot_sha256"] = "f" * 64
    elif defect == "invented_patch":
        middle["patch_ids"] = ["invented-patch"]
    elif defect == "wrong_event_patch":
        middle["patch_ids"] = [second_patch.patch_id]
        middle["patch_records_sha256"] = [second_patch.records_sha256]
    else:
        metadata["patched_session_count"] += 1
    with pytest.raises(DataContractError):
        index_membership.validate_index_membership(frame, request, metadata)


def test_DFLS_28_C05_daily_facade_rechecks_backdated_provider_evidence(membership_root, monkeypatch, sources):
    from dataflows import index_membership
    sources(events=[_event()])
    original = index_membership.fetch_index_constituents_daily

    def corrupt(request, **kwargs):
        frame, metadata = original(request, **kwargs)
        frame["AvailableDate"] = pd.Timestamp("2020-01-01")
        for segment in metadata["reconstruction_segments"]:
            segment["available_date"] = "2020-01-01T00:00:00"
        return frame, metadata

    monkeypatch.setattr(index_membership, "fetch_index_constituents_daily", corrupt)
    _, _, prepared = _prepare(membership_root)
    item, = prepared.items
    assert item.status is DataStatus.FAILED and prepared.reference is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"
