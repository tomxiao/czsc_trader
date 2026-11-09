"""Official-event supplements stay explicit, bounded, and reproducible offline."""

from pathlib import Path

import pytest

from dataflows import (
    Dataflows, DataRequest, DataSpace, Dataset, ProviderConfig,
)
from dataflows import index_constituent_changes
from dataflows.errors import DataContractError


def _request(**kwargs):
    return DataRequest(**{
        "dataset": Dataset.INDEX_CONSTITUENT_CHANGES, "symbol": "000905.SH",
        "start": "2021-06-15", "end": "2021-06-15", "required_cutoff": "2021-06-15",
        "frequency": "event", **kwargs,
    })


@pytest.fixture
def event_root(tmp_path, empty_space_factory):
    empty_space_factory("market")
    return tmp_path


def _flow(event_root):
    return Dataflows(base_dir=event_root, space=DataSpace(Path("market")), providers=ProviderConfig())










@pytest.mark.parametrize("defect", [
    "source_hash",
], ids=['DFLS-28-C03'])
def test_corrupt_event_or_provenance_rejected_by_validator(defect):
    request = _request()
    frame, metadata = index_constituent_changes.fetch_index_constituent_changes(request)
    if defect == "direction":
        frame.loc[0, "Change"] = "REMOVE"
    elif defect == "coverage":
        metadata["complete_membership_history"] = True
    elif defect == "source_hash":
        metadata["source_attachment_sha256"] = "0" * 64
    else:
        frame = frame.iloc[:-1].reset_index(drop=True)
    with pytest.raises(DataContractError) as raised:
        index_constituent_changes.validate_index_constituent_changes(frame, request, metadata)
    assert raised.value.code == "DATA_CONTRACT_MISMATCH"
