"""DFLS-11: temporal alignment uses actual availability, without a data space."""
import pandas as pd
import pytest
from dataflows import DataTemporalContract, DataTemporalRequirement, TemporalAlignment, align_temporal_frame


def contract():
    return DataTemporalContract("Date","AvailableDate","SOURCE_CALENDAR","published before market open","EXACT")


def source():
    return pd.DataFrame({"Date":["2026-09-01","2026-09-03"],
                         "AvailableDate":["2026-09-02","2026-09-04"],"Value":[1.,2.]})


def test_DFLS_11_C01_strict_prior_excludes_equal_availability():
    result = align_temporal_frame(source(),["2026-09-02","2026-09-03","2026-09-04"],
        contract=contract(), requirement=DataTemporalRequirement(
            TemporalAlignment.STRICT_PRIOR,decision_time="SSE open",warmup_sessions=1))
    assert result.unmatched_prefix_rows == 1
    assert result.dataframe.Value.tolist()[1:] == [1.,1.]


def test_DFLS_11_C02_latest_available_includes_equal_availability():
    result = align_temporal_frame(source(),["2026-09-02","2026-09-03","2026-09-04"],
        contract=contract(),requirement=DataTemporalRequirement(
            TemporalAlignment.LATEST_AVAILABLE,decision_time="SSE close"))
    assert result.unmatched_prefix_rows == 0
    assert result.dataframe.Value.tolist() == [1.,1.,2.]


def test_DFLS_11_C03_earlier_source_date_does_not_override_late_publication():
    frame = source()
    frame["Date"] = pd.to_datetime(["2026-08-01","2026-08-02"])
    result = align_temporal_frame(frame,["2026-09-03"],contract=contract(),
        requirement=DataTemporalRequirement(TemporalAlignment.LATEST_AVAILABLE,decision_time="SSE close"))
    assert result.dataframe.Value.tolist() == [1.]
    assert result.dataframe.SourceTime.tolist() == [pd.Timestamp("2026-08-01")]


def test_DFLS_11_C04_stale_value_fails_instead_of_filling():
    with pytest.raises(ValueError,match="max_staleness_days"):
        align_temporal_frame(source(),["2026-09-02","2026-09-10"],contract=contract(),
            requirement=DataTemporalRequirement(TemporalAlignment.LATEST_AVAILABLE,
                decision_time="SSE close",max_staleness_days=2))


def test_DFLS_11_C05_undeclared_warmup_fails():
    with pytest.raises(ValueError,match="warmup_sessions"):
        align_temporal_frame(source(),["2026-09-01","2026-09-02"],contract=contract(),
            requirement=DataTemporalRequirement(TemporalAlignment.LATEST_AVAILABLE,decision_time="SSE close"))
