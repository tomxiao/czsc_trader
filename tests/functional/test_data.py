from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding

from czsc_trader import market_data_prep
from czsc_trader.data import load_execution_prices
from functional_support import vendor_frame
from dataclasses import asdict
from czsc_trader.application import (
    RepositoryContext,
    PrepareDataCommand,
    prepare_data,
    validate_data,
)


def test_ft_t01_data_prepare_validate_and_tamper_detection(
    minimal_repo: Path, capsys, monkeypatch
) -> None:
    day = "2026-09-01"
    intraday = vendor_frame(
        [
            (f"{day} {value}:00", 1.704)
            for value in (
                "10:00",
                "10:30",
                "11:00",
                "11:30",
                "13:30",
                "14:00",
                "14:30",
                "15:00",
            )
        ]
    )
    intraday["Volume"] = 125.0
    intraday["Amount"] = 213.0
    adjusted = {
        "30m": intraday,
        "daily": vendor_frame([(day, 1.704)]),
        "weekly": vendor_frame([(day, 1.704)]),
    }
    original = market_data_prep.prepare_market_data

    def offline_prepare(symbol, asset, start, end, output_dir, *, env_file=None):
        del env_file

        def market(request):
            return adjusted[request.frequency], {
                "vendor": "functional-test",
                "vendor_symbol": symbol,
                "asset_type": asset,
                "period": request.frequency,
                "adjustment": "hfq",
                "adjustment_factor_source": "fixed",
                "adjustment_factor_sha256": "factor-hash",
            }

        def execution(request):
            return vendor_frame([(day, 1.688)]), {
                "vendor": "functional-test",
                "vendor_symbol": symbol,
                "asset_type": asset,
                "period": "daily",
                "adjustment": "none",
            }

        def calendar(request):
            days = pd.date_range(request.start, request.end)
            return pd.DataFrame({"Date": days, "IsOpen": (days.dayofweek < 5).astype(int)}), {
                "vendor": "functional-test",
                "exchange": "SSE",
                "primary_key": ["Date"],
            }

        return original(
            symbol,
            asset,
            start,
            end,
            output_dir,
            dataflows=Dataflows(
                base_dir=output_dir, space=DataSpace(Path("assets")),
                providers=ProviderConfig(bindings={
                    Dataset.ETF_OHLCV: ProviderBinding("fixture", "v1", market),
                    Dataset.ETF_UNADJUSTED_DAILY: ProviderBinding("fixture", "v1", execution),
                    Dataset.TRADING_CALENDAR: ProviderBinding("fixture", "v1", calendar),
                }),
            ),
            instrument_name="科创50ETF",
        )

    monkeypatch.setattr(market_data_prep, "prepare_market_data", offline_prepare)
    context = RepositoryContext.discover(minimal_repo)
    prepared = asdict(
        prepare_data(
            context,
            PrepareDataCommand(
                "588080.SH",
                "etf",
                date.fromisoformat(day),
                date.fromisoformat(day),
            ),
        )
    )
    validated = asdict(validate_data(context, "588080.SH"))

    execution_manifest = minimal_repo / "data" / "raw" / "588080_execution_manifest.json"
    assert Path(prepared["result"]["execution_price_manifest"]) == execution_manifest
    assert prepared["result"]["data_cutoff"] == day
    execution_metadata = pd.read_json(execution_manifest, typ="series")
    assert execution_metadata["next_trading_session"] == "2026-09-02"
    assert validated["result"]["frequencies"] == ["30m", "daily", "weekly"]
    with pytest.raises(ValueError, match="INCOMPLETE"):
        offline_prepare(
            "588080.SH",
            "etf",
            date(2026, 9, 1),
            date(2026, 9, 2),
            minimal_repo / "state" / "stale-data",
        )
    execution_csv = minimal_repo / "data" / "raw" / "588080_execution_daily_2026.csv"
    execution_csv.write_bytes(execution_csv.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256 differs"):
        load_execution_prices(minimal_repo / "data" / "raw", "588080.SH", "etf")
