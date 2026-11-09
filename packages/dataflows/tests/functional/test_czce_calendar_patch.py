"""Official-calendar repair through the public publication boundary."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from dataflows import DataRequest, Dataflows, DataSpace, Dataset, PreparePolicy, ProviderBinding, ProviderConfig
from dataflows._czce_calendar_patch import PATCH_ID, PATCH_SOURCE_HASHES, apply_czce_calendar_patch
from dataflows.errors import DataContractError, DataRepairError
from dataflows.facade import _validate_provider_output


@pytest.fixture
def calendar_root(tmp_path, empty_space_factory):
    # Initialization/concurrency are covered by test_data_space.
    empty_space_factory("calendar")
    return tmp_path


def _frame():
    return pd.DataFrame({
        "Date": pd.to_datetime(["2022-12-30", "2023-01-01", "2023-01-02", "2023-01-03"]),
        "IsOpen": [1, 0, 0, 1],
        "PreviousTradingDate": pd.to_datetime(["2022-12-29", "2022-12-30", "2022-12-30", "2022-12-30"]),
    })


def _publish(root, frame, *, exchange="CZCE", start="2022-12-30", end="2023-01-03"):
    def provider(request):
        selected = frame.loc[frame.Date.between(request.start, request.end)].copy()
        return apply_czce_calendar_patch(selected, exchange=request.symbol,
                                        start_date=request.start, end_date=request.end)
    request = DataRequest(Dataset.TRADING_CALENDAR, exchange, start, end, end)
    flow = Dataflows(base_dir=root, space=DataSpace(Path("calendar")), providers=ProviderConfig(bindings={
        Dataset.TRADING_CALENDAR: ProviderBinding("czce-calendar-patch-test", "1", provider),
    }))
    prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    return prepared, flow.fetch(request, prepared=prepared.reference) if prepared.ready else None


def test_DFLS_39_C01_certified_day_publishes_with_pinned_lineage(calendar_root):
    original = _frame()
    prepared, result = _publish(calendar_root, original)
    assert prepared.ready, prepared.items
    assert result.ready and len(result.dataframe) == 5
    row = result.dataframe.loc[result.dataframe.Date.eq("2022-12-31")].iloc[0]
    assert row.IsOpen == 0 and row.PreviousTradingDate == pd.Timestamp("2022-12-30")
    repair = result.identity.metadata["calendar_repairs"][0]
    assert repair["patch_id"] == PATCH_ID and repair["original_row"] is None
    assert repair["raw_content_sha256"] != repair["repaired_content_sha256"]
    assert repair["evidence_basis"] == "OFFICIAL_RULE_AND_GOVERNMENT_HOLIDAY"
    assert tuple(x["sha256"] for x in repair["official_sources"]) == PATCH_SOURCE_HASHES
    assert len(original) == 4


def test_DFLS_39_C02_existing_correct_day_is_idempotent():
    frame = pd.concat([_frame(), pd.DataFrame({"Date": [pd.Timestamp("2022-12-31")],
                                             "IsOpen": [0], "PreviousTradingDate": [pd.Timestamp("2022-12-30")]})]).sort_values("Date").reset_index(drop=True)
    result, metadata = apply_czce_calendar_patch(frame,exchange="CZCE",start_date="2022-12-30",end_date="2023-01-03")
    pd.testing.assert_frame_equal(result,frame)
    assert not metadata.get("calendar_repairs")


@pytest.mark.parametrize("case", [
    "open_conflict",
    "previous_conflict",
    "duplicate",
    "no_previous",
    "other_hole",
    "wrong_exchange",
], ids=['DFLS-39-C03', 'DFLS-39-C04', 'DFLS-39-C05', 'DFLS-39-C06', 'DFLS-39-C07', 'DFLS-39-C08'])
def test_patch_rejects_conflicts_and_does_not_infer_other_dates(case):
    frame = _frame()
    if case in {"open_conflict", "previous_conflict", "duplicate"}:
        extra = pd.DataFrame({"Date": [pd.Timestamp("2022-12-31")],
                              "IsOpen": [1 if case == "open_conflict" else 0],
                              "PreviousTradingDate": [pd.Timestamp("2022-12-29" if case == "previous_conflict" else "2022-12-30")]})
        frame = pd.concat([frame, extra, extra] if case == "duplicate" else [frame, extra])
    elif case == "no_previous":
        frame = frame.loc[frame.Date.ne("2022-12-30")]
    elif case == "other_hole":
        frame = frame.loc[frame.Date.ne("2023-01-01")]
    exchange = "SSE" if case == "wrong_exchange" else "CZCE"
    request = DataRequest(Dataset.TRADING_CALENDAR,exchange,"2022-12-30","2023-01-03","2023-01-03")
    if case in {"other_hole","wrong_exchange"}:
        # The repair must leave unregistered gaps for the real calendar validator.
        result, metadata = apply_czce_calendar_patch(frame,exchange=exchange,start_date=request.start,end_date=request.end)
        with pytest.raises(DataContractError,match="every requested calendar date"):
            _validate_provider_output(result,request,metadata)
    else:
        with pytest.raises(DataRepairError):
            apply_czce_calendar_patch(frame,exchange=exchange,start_date=request.start,end_date=request.end)




def test_DFLS_39_C09_official_evidence_bytes_match_pinned_hashes():
    directory = Path(__file__).parents[2] / "patch_evidence" / "czce_20221231"
    manifest = json.loads((directory / "source_manifest.json").read_text(encoding="utf-8"))
    assert manifest["patch_id"] == PATCH_ID
    assert tuple(s["sha256"] for s in manifest["sources"]) == PATCH_SOURCE_HASHES
    for source in manifest["sources"]:
        assert hashlib.sha256((directory / source["file"]).read_bytes()).hexdigest() == source["sha256"]
