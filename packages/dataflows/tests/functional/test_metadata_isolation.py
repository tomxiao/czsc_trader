"""Pinned public reads retain isolated metadata without copying it during validation."""

from copy import deepcopy

import pandas as pd

from dataflows import DataRequest, Dataset, canonical_frame_sha256


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






def test_DFLS_03_C01_content_hash_does_not_copy_or_change_metadata():
    frame = _source()
    expected = canonical_frame_sha256(pd.DataFrame(frame, copy=False))
    MetadataProbe.copies = 0
    assert canonical_frame_sha256(frame) == expected
    assert MetadataProbe.copies == 0
    assert frame.attrs["quality"]["sessions"] == ["2026-09-14", "2026-09-15", "2026-09-16"]
