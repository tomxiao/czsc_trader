"""SRT-33: the public price-unit contract, without providers or execution."""

from datetime import date
from copy import deepcopy
import pandas as pd
import pytest
from strategy_runtime import ExecutionPriceBasis, ExecutionPricing, RuntimeContractError


class MetadataProbe(dict):
    copies = 0

    def __deepcopy__(self, memo):
        type(self).copies += 1
        return MetadataProbe({key: deepcopy(value, memo) for key, value in self.items()})


def daily():
    return pd.DataFrame(
        {
            "dt": pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05"]),
            "open": [10.0, 5.0, 6.0],
            "high": [10.0, 5.0, 6.0],
            "low": [10.0, 5.0, 6.0],
            "close": [10.0, 5.0, 6.0],
            "vol": [1000.0, 2000.0, 2000.0],
            "amount": [10000.0, 10000.0, 12000.0],
        }
    )


def adjusted(raw, scale):
    result = pd.DataFrame(raw, copy=True)
    columns = ["open", "high", "low", "close"]
    result[columns] = result[columns].mul(pd.Series([scale, 2 * scale, 2 * scale]), axis=0)
    return result


def test_SRT_33_C01_factor_scale_invariance_and_hfq_units():
    raw = daily()
    raw.attrs = {"quality": MetadataProbe({"sessions": ["2025-12-31"]})}
    small, large = adjusted(raw, 0.3), adjusted(raw, 30.0)
    first = ExecutionPricing.from_daily(
        ExecutionPriceBasis.HFQ_RESEARCH, raw, small, date(2025, 12, 31)
    )
    second = ExecutionPricing.from_daily(
        ExecutionPriceBasis.HFQ_RESEARCH, raw, large, date(2025, 12, 31)
    )
    MetadataProbe.copies = 0
    result = first.apply(raw, raw_daily=raw, adjusted_daily=small)
    assert MetadataProbe.copies == 1
    pd.testing.assert_frame_equal(result, second.apply(raw, raw_daily=raw, adjusted_daily=large))
    assert result.close.tolist() == pytest.approx([10.0, 10.0, 12.0])
    assert result.vol.tolist() == pytest.approx([1000.0, 1000.0, 1000.0])
    assert result.amount.tolist() == raw.amount.tolist()
    assert ExecutionPricing.from_dict(first.to_dict()) == first
    assert first.to_dict()["quantity_unit"] == "RESEARCH_UNIT"
    intraday = raw.iloc[1:].copy()
    intraday["dt"] += pd.Timedelta(hours=10)
    assert first.apply(
        intraday, raw_daily=raw, adjusted_daily=small
    ).close.tolist() == pytest.approx([10.0, 12.0])
    result.iat[0, 4] = 99.0
    result.attrs["quality"]["sessions"].append("changed")
    assert raw.iat[0, 4] == 10.0
    assert raw.attrs["quality"]["sessions"] == ["2025-12-31"]


def test_SRT_33_C02_raw_copy_retains_values_and_isolates_metadata():
    raw = daily()
    raw.attrs = {"quality": MetadataProbe({"sessions": ["2025-12-31"]})}
    MetadataProbe.copies = 0
    result = ExecutionPricing().apply(raw, raw_daily=raw, adjusted_daily=raw)
    assert MetadataProbe.copies == 1
    pd.testing.assert_frame_equal(result, raw)
    result.iat[0, 4] = 99.0
    result.attrs["quality"]["sessions"].append("changed")
    assert raw.iat[0, 4] == 10.0 and raw.attrs["quality"]["sessions"] == ["2025-12-31"]


@pytest.mark.parametrize(
    "fault",
    [
        "nonpositive",
        "missing",
        "factor",
        "anchor",
    ],
    ids=["SRT-33-C03", "SRT-33-C04", "SRT-33-C05", "SRT-33-C06"],
)
def test_invalid_numeric_contract_before_metadata_copy(fault):
    raw = daily()
    other = adjusted(raw, 1.0)
    if fault == "nonpositive":
        raw.loc[0, "close"] = 0.0
    elif fault == "missing":
        other = other.iloc[:-1]
    elif fault == "factor":
        other.loc[1, "open"] *= 2
    raw.attrs = {"quality": MetadataProbe({"source": "raw"})}
    other.attrs = {"quality": MetadataProbe({"source": "adjusted"})}
    contract = ExecutionPricing(
        ExecutionPriceBasis.HFQ_RESEARCH, date(2025, 12, 31), 2.0 if fault == "anchor" else 1.0
    )
    MetadataProbe.copies = 0
    with pytest.raises(RuntimeContractError):
        contract.apply(raw, raw_daily=raw, adjusted_daily=other)
    assert MetadataProbe.copies == 0


def test_SRT_33_C07_serialized_units_must_match_basis():
    value = ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2025, 12, 31), 1.0).to_dict()
    value["quantity_unit"] = "SHARE"
    with pytest.raises(RuntimeContractError, match="quantity units"):
        ExecutionPricing.from_dict(value)


def test_SRT_33_C08_raw_contract_rejects_adjustment_anchor():
    with pytest.raises(RuntimeContractError, match="does not accept"):
        ExecutionPricing(ExecutionPriceBasis.UNADJUSTED, date(2025, 12, 31), 1.0)
