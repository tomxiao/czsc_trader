from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.tushare_strategy_data import (
    fetch_cn_cpi_monthly,
    fetch_cn_money_monthly,
    fetch_cn_ppi_monthly,
    fetch_domestic_index_daily,
    fetch_fxcm_daily,
    fetch_sge_gold_daily,
    fetch_us_real_yield_daily,
    fetch_usdcnh_daily,
)


class FakeGoldPro:
    def __init__(self) -> None:
        self.real_yield_calls: list[dict[str, str]] = []

    def us_trycr(self, **kwargs):
        self.real_yield_calls.append(kwargs)
        return pd.DataFrame(
            {
                "date": [kwargs["start_date"]],
                "y5": [1.0],
                "y7": [1.1],
                "y10": [1.2],
                "y20": [1.3],
                "y30": [1.4],
            }
        )

    def fx_daily(self, **kwargs):
        return pd.DataFrame(
            {
                "trade_date": [kwargs["start_date"]],
                "bid_open": [7.10],
                "bid_high": [7.12],
                "bid_low": [7.09],
                "bid_close": [7.11],
                "ask_open": [7.11],
                "ask_high": [7.13],
                "ask_low": [7.10],
                "ask_close": [7.12],
                "tick_qty": [100],
            }
        )

    def sge_daily(self, **kwargs):
        return pd.DataFrame(
            {
                "trade_date": [kwargs["start_date"]],
                "open": [600.0],
                "high": [610.0],
                "low": [595.0],
                "close": [605.0],
                "price_avg": [603.0],
                "change": [5.0],
                "pct_change": [0.8333],
                "vol": [1000.0],
                "amount": [603000.0],
            }
        )

    def index_daily(self, **kwargs):
        return pd.DataFrame(
            {
                "trade_date": [kwargs["start_date"]],
                "open": [3000.0],
                "high": [3030.0],
                "low": [2990.0],
                "close": [3020.0],
                "pre_close": [3000.0],
                "change": [20.0],
                "pct_chg": [0.6667],
                "vol": [10_000.0],
                "amount": [20_000.0],
            }
        )

    def cn_cpi(self, **kwargs):
        return pd.DataFrame(
            {
                "month": [kwargs["start_m"]],
                "nt_val": [101.0],
                "nt_yoy": [1.0],
                "nt_mom": [0.2],
                "nt_accu": [0.8],
            }
        )

    def cn_ppi(self, **kwargs):
        return pd.DataFrame(
            {
                "month": [kwargs["start_m"]],
                "ppi_yoy": [-1.0],
                "ppi_mom": [0.1],
                "ppi_accu": [-1.2],
            }
        )

    def cn_m(self, **kwargs):
        return pd.DataFrame(
            {
                "month": [kwargs["start_m"]],
                "m0": [1.0],
                "m0_yoy": [2.0],
                "m0_mom": [0.1],
                "m1": [3.0],
                "m1_yoy": [4.0],
                "m1_mom": [0.2],
                "m2": [5.0],
                "m2_yoy": [6.0],
                "m2_mom": [0.3],
            }
        )


def test_gold_research_inputs_are_canonical_and_causal() -> None:
    pro = FakeGoldPro()
    real_yield, real_meta = fetch_us_real_yield_daily("2026-09-15", "2026-09-15", pro=pro)
    fx, fx_meta = fetch_usdcnh_daily("2026-09-15", "2026-09-15", pro=pro)
    gold, gold_meta = fetch_sge_gold_daily("Au99.99", "2026-09-15", "2026-09-15", pro=pro)
    index, index_meta = fetch_domestic_index_daily("000001.SH", "2026-09-15", "2026-09-15", pro=pro)

    assert real_yield.loc[0, "RealYield10YPercent"] == pytest.approx(1.2)
    assert "prior China trading day" in real_meta["availability_rule"]
    assert fx.loc[0, "BidClose"] == pytest.approx(7.11)
    assert fx_meta["vendor_timezone"] == "GMT"
    assert gold.loc[0, "PercentChange"] == pytest.approx(0.008333)
    assert "prior trading day" in gold_meta["availability_rule"]
    assert index.loc[0, "PercentChange"] == pytest.approx(0.006667)
    assert index_meta["availability_rule"] == "current session after market close"


def test_generic_fxcm_daily_preserves_symbol_and_strict_causality() -> None:
    frame, metadata = fetch_fxcm_daily("XAUUSD.FXCM", "2026-09-15", "2026-09-15", pro=FakeGoldPro())

    assert frame.loc[0, "BidClose"] == pytest.approx(7.11)
    assert metadata["vendor_symbol"] == "XAUUSD.FXCM"
    assert metadata["maximum_start_lag_days"] == 10
    assert metadata["availability_rule"] == (
        "GMT source date must be strictly earlier than China decision session"
    )


def test_monthly_inputs_use_reference_month_end_and_conservative_availability() -> None:
    pro = FakeGoldPro()
    cpi, cpi_meta = fetch_cn_cpi_monthly("2026-09-01", "2026-09-30", pro=pro)
    ppi, ppi_meta = fetch_cn_ppi_monthly("2026-09-01", "2026-09-30", pro=pro)
    money, money_meta = fetch_cn_money_monthly("2026-09-01", "2026-09-30", pro=pro)

    assert cpi.loc[0, "Date"] == pd.Timestamp("2026-09-30")
    assert cpi.loc[0, "AvailableDate"] == pd.Timestamp("2026-11-01")
    assert cpi.loc[0, "NationalYoYPercent"] == pytest.approx(1.0)
    assert ppi.loc[0, "ProducerYoYPercent"] == pytest.approx(-1.0)
    assert money.loc[0, "M2YoYPercent"] == pytest.approx(6.0)
    for metadata in (cpi_meta, ppi_meta, money_meta):
        assert metadata["frequency"] == "monthly"
        assert metadata["availability_rule"].endswith("M+2")
        assert metadata["availability_time_field"] == "AvailableDate"


def test_long_vendor_histories_are_split_by_calendar_year() -> None:
    pro = FakeGoldPro()
    frame, _ = fetch_us_real_yield_daily("2025-12-31", "2026-01-01", pro=pro)

    assert len(frame) == 2
    assert [call["start_date"] for call in pro.real_yield_calls] == [
        "20251231",
        "20260101",
    ]


def test_facade_rejects_crossed_usdcnh_close_quotes() -> None:
    frame = pd.DataFrame(
        {
            "Date": ["2026-09-15"],
            "BidOpen": [7.1],
            "BidHigh": [7.2],
            "BidLow": [7.0],
            "BidClose": [7.2],
            "AskOpen": [7.1],
            "AskHigh": [7.2],
            "AskLow": [7.0],
            "AskClose": [7.1],
            "TickQuantity": [1],
        }
    )
    result = Dataflows(
        {Dataset.USDCNH_DAILY.value: lambda ignored: (frame, {"vendor": "test"})}
    ).fetch(
        DataRequest(
            Dataset.USDCNH_DAILY,
            None,
            "2026-09-15",
            "2026-09-15",
            "2026-09-15",
        )
    )

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"


@pytest.mark.parametrize(
    ("low", "expected_status"),
    [(245.40, DataStatus.READY), (245.50, DataStatus.FAILED)],
)
def test_sge_daily_allows_only_one_tick_vendor_rounding(low, expected_status) -> None:
    frame = pd.DataFrame(
        {
            "Date": ["2014-10-22"],
            "Open": [249.99],
            "High": [249.99],
            "Low": [low],
            "Close": [245.39],
            "Volume": [21307.8],
            "Amount": [5246170684.2],
        }
    )
    result = Dataflows(
        {Dataset.SGE_GOLD_DAILY.value: lambda ignored: (frame, {"vendor": "test"})}
    ).fetch(
        DataRequest(
            Dataset.SGE_GOLD_DAILY,
            "Au99.99",
            "2014-10-22",
            "2014-10-22",
            "2014-10-22",
        )
    )

    assert result.status is expected_status
