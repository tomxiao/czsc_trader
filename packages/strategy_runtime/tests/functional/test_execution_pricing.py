from datetime import date

import pandas as pd
import pytest

from strategy_runtime import ExecutionPriceBasis, ExecutionPricing, RuntimeContractError


def _daily():
    return pd.DataFrame({"dt": pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05"]),
                         "open": [10., 5., 6.], "high": [10., 5., 6.],
                         "low": [10., 5., 6.], "close": [10., 5., 6.],
                         "vol": [1000., 2000., 2000.], "amount": [10000., 10000., 12000.]})


@pytest.mark.parametrize("factor_scale", [.3, 30.])
def test_hfq_research_units_preserve_returns_and_ignore_vendor_factor_scale(factor_scale):
    raw = _daily()
    adjusted = raw.copy()
    factors = pd.Series([factor_scale, 2 * factor_scale, 2 * factor_scale])
    for field in ("open", "high", "low", "close"):
        adjusted[field] = raw[field] * factors
    pricing = ExecutionPricing.from_daily(ExecutionPriceBasis.HFQ_RESEARCH,
                                         raw, adjusted, date(2025, 12, 31))
    quotes = pricing.apply(raw, raw_daily=raw, adjusted_daily=adjusted)
    assert quotes.close.tolist() == pytest.approx([10., 10., 12.])
    assert quotes.vol.tolist() == pytest.approx([1000., 1000., 1000.])
    assert quotes.amount.tolist() == raw.amount.tolist()
    assert ExecutionPricing.from_dict(pricing.to_dict()) == pricing
    assert pricing.to_dict()["quantity_unit"] == "RESEARCH_UNIT"
    intraday = raw.iloc[[1, 2]].copy()
    intraday["dt"] += pd.Timedelta(hours=10)
    assert pricing.apply(intraday, raw_daily=raw, adjusted_daily=adjusted).close.tolist() == pytest.approx([10., 12.])
    assert ExecutionPricing().apply(raw, raw_daily=raw, adjusted_daily=adjusted).equals(raw)


@pytest.mark.parametrize("fault", ["missing_session", "different_ohlc_factor", "wrong_anchor"])
def test_hfq_research_pricing_rejects_inconsistent_admitted_market_data(fault):
    raw = _daily()
    adjusted = raw.copy()
    pricing = ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2025, 12, 31), 1.)
    if fault == "missing_session":
        adjusted = adjusted.iloc[:-1]
    elif fault == "different_ohlc_factor":
        adjusted.loc[1, "open"] *= 2
    else:
        pricing = ExecutionPricing(ExecutionPriceBasis.HFQ_RESEARCH, date(2025, 12, 31), 2.)
    with pytest.raises(RuntimeContractError):
        pricing.apply(raw, raw_daily=raw, adjusted_daily=adjusted)
