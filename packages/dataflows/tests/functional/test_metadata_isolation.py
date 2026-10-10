"""Pinned public reads retain isolated metadata without copying it during validation."""

from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from dataflows import DataCoverageRequirement, DataRequest, DataStatus, Dataset, PreparePolicy, canonical_frame_sha256


class MetadataProbe(dict):
    copies = 0

    def __deepcopy__(self, memo):
        type(self).copies += 1
        result = type(self)()
        memo[id(self)] = result
        result.update({key: deepcopy(value, memo) for key, value in self.items()})
        return result


def _source():
    frame = pd.DataFrame({"Date": pd.date_range("2026-09-14", periods=3), "OvernightRate": [1., 1.1, 1.2]})
    frame.attrs = {"quality": MetadataProbe({"sessions": ["2026-09-14", "2026-09-15", "2026-09-16"]})}
    return frame


def _request():
    return DataRequest(Dataset.SHIBOR_DAILY, None, "2026-09-14", "2026-09-16", None)


def test_fetch_copies_only_retained_metadata_after_complete_numeric_validation(flow_factory):
    original = _source()
    calls = []

    def provider(request):
        calls.append(request)
        values = pd.DataFrame(original, copy=False)
        frame = values.loc[values.Date.between(request.start, request.end)].copy()
        frame.attrs = {"quality": MetadataProbe({"sessions": list(original.attrs["quality"]["sessions"]),
                                               "source_start": request.start})}
        return frame, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    subset = replace(_request(), start="2026-09-15")
    prepared = flows.prepare((_request(), subset), policy=PreparePolicy.REFRESH)
    assert prepared.ready and len(calls) == 2
    MetadataProbe.copies = 0
    result = flows.fetch(subset, prepared=prepared.reference)
    assert result.ready and MetadataProbe.copies == 1
    assert result.identity.content_sha256 == canonical_frame_sha256(result.dataframe)
    assert result.dataframe.attrs["quality"]["source_start"] in {_request().start, subset.start}
    retained_metadata = deepcopy(result.dataframe.attrs)
    result.dataframe.attrs["quality"]["sessions"].append("local annotation")
    result.dataframe.iat[0, 1] = 99.
    MetadataProbe.copies = 0
    repeat = flows.fetch(subset, prepared=prepared.reference)
    assert repeat.ready and MetadataProbe.copies == 1
    assert repeat.dataframe.attrs == retained_metadata
    assert repeat.dataframe.iat[0, 1] == 1.1
    assert original.iat[1, 1] == 1.1 and len(calls) == 2


def test_failed_subset_coverage_does_not_copy_result_metadata(flow_factory):
    flows = flow_factory({Dataset.SHIBOR_DAILY: lambda request: (_source(), {"vendor": "fixture"})})
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert prepared.ready
    insufficient = replace(_request(), start="2026-09-15", coverage=DataCoverageRequirement(
        minimum_observations=2, minimum_sessions=2, observations_through="2026-09-15"))
    MetadataProbe.copies = 0
    result = flows.fetch(insufficient, prepared=prepared.reference)
    assert result.status is DataStatus.INCOMPLETE and result.error.code == "INCOMPLETE_DATA"
    assert MetadataProbe.copies == 0
    assert result.error.context["actual_observations"] == 1


def test_content_hash_does_not_copy_or_change_metadata():
    frame = _source()
    expected = canonical_frame_sha256(pd.DataFrame(frame, copy=False))
    MetadataProbe.copies = 0
    assert canonical_frame_sha256(frame) == expected
    assert MetadataProbe.copies == 0
    assert frame.attrs["quality"]["sessions"] == ["2026-09-14", "2026-09-15", "2026-09-16"]


@pytest.mark.parametrize("changed", [True, False])
def test_overlap_validation_still_rejects_inconsistent_numeric_sources(flow_factory, changed):
    def provider(request):
        numerical = pd.DataFrame(_source(), copy=False)
        frame = numerical.loc[numerical.Date.between(request.start, request.end)].copy()
        if changed and request.start == "2026-09-15":
            frame.iat[0, 1] = 99.
        frame.attrs = {"quality": MetadataProbe({"source": request.start})}
        return frame, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    prepared = flows.prepare((_request(), replace(_request(), start="2026-09-15")), policy=PreparePolicy.REFRESH)
    assert prepared.ready is not changed
    if changed:
        assert prepared.reference is None
        assert all(item.error.code == "INCONSISTENT_PREPARATION" for item in prepared.items)
