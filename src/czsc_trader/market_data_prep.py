"""Fetch, validate, and safely publish flat A-share market data."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any

import pandas as pd
from dataflows import (DataRequest, Dataflows, Dataset, DataSpace, ProviderConfig, PreparePolicy)

from .identity import raw_file_sha256
from .temp_workspace import create_temporary_directory

FREQUENCIES = ("30m", "daily", "weekly")
VENDOR_COLUMNS = ("Date", "Open", "High", "Low", "Close", "Volume", "Amount")

def _normalize_symbol(symbol: str) -> tuple[str, str]:
    value = str(symbol).strip().upper()
    match = re.fullmatch(r"(\d{6})\.(SH|SZ)", value)
    if not match:
        raise ValueError("symbol must be a six-digit A-share code ending in SH or SZ")
    return value, match.group(1)


def _normalize_frame(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    missing = sorted(set(VENDOR_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"{name}: DFLS result is missing columns {missing}")
    normalized = frame.loc[:, VENDOR_COLUMNS].copy()
    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="raise")
    for column in VENDOR_COLUMNS[1:]:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise")
    return normalized.reset_index(drop=True)


def _ready_result(result, label: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not result.ready or result.identity is None:
        error = result.error
        detail = (
            f"{error.code}: {error.message}" if error is not None else result.status.value
        )
        raise ValueError(f"{label}: DFLS returned {result.status.value}: {detail}")
    return result.dataframe, dict(result.identity.metadata)


def _fetch_result(
    dataflows: Dataflows,
    *,
    dataset: Dataset,
    symbol: str,
    start: date,
    end: date,
    frequency: str,
    label: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    request = DataRequest(dataset, symbol, start.isoformat(), end.isoformat(), end.isoformat(), frequency)
    preparation = dataflows.prepare((request,), policy=PreparePolicy.REUSE)
    if not preparation.ready:
        raise ValueError(f"DFLS preparation failed: {preparation.items}")
    result = dataflows.fetch(request, prepared=preparation.reference)
    frame, metadata = _ready_result(result, label)
    metadata["prepared"] = {
        "space_id": str(preparation.reference.space_id),
        "preparation_id": str(preparation.reference.preparation_id),
        "manifest_sha256": preparation.reference.manifest_sha256,
    }
    return frame, metadata



def _csv_frame(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    source = _normalize_frame(frame, period).rename(
        columns={
            "Date": "datetime" if period == "30m" else "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Amount": "amount",
        }
    )
    time_column = "datetime" if period == "30m" else "date"
    source[time_column] = source[time_column].dt.strftime(
        "%Y-%m-%d %H:%M:%S" if period == "30m" else "%Y-%m-%d"
    )
    return source


def prepare_market_data(
    symbol: str,
    asset_type: str,
    start: date,
    end: date,
    data_dir: Path,
    *,
    dataflows: Dataflows | None = None,
    instrument_name: str | None = None,
    env_file: str | Path | None = None,
) -> dict[str, object]:
    """Fetch and publish one fully validated flat market-data generation."""
    normalized_symbol, code = _normalize_symbol(symbol)
    normalized_asset = str(asset_type).strip().lower()
    if normalized_asset not in {"stock", "etf"}:
        raise ValueError("asset_type must be stock or etf")
    if start > end:
        raise ValueError("start must not be after end")
    flows = dataflows if dataflows is not None else Dataflows(
        base_dir=Path(data_dir).resolve(), space=DataSpace(Path("assets")),
        providers=ProviderConfig(env_file=Path(env_file) if env_file is not None else None),
    )
    if instrument_name is None:
        from dataflows.tushare_common import fetch_instrument_name

        resolved_name = fetch_instrument_name(
            normalized_symbol, normalized_asset, env_file=env_file
        )
    else:
        resolved_name = instrument_name
    resolved_name = str(resolved_name).strip()
    if not resolved_name:
        raise ValueError("instrument name must not be empty")
    frames: dict[str, pd.DataFrame] = {}
    metadata: dict[str, dict[str, Any]] = {}
    adjusted_dataset = (
        Dataset.STOCK_OHLCV if normalized_asset == "stock" else Dataset.ETF_OHLCV
    )
    for period in FREQUENCIES:
        frame, item_metadata = _fetch_result(
            flows,
            dataset=adjusted_dataset,
            symbol=normalized_symbol,
            start=start,
            end=end,
            frequency=period,
            label=f"{normalized_symbol} {period}",
        )
        frames[period] = frame
        metadata[period] = item_metadata
    execution_dataset = (
        Dataset.STOCK_UNADJUSTED_DAILY
        if normalized_asset == "stock"
        else Dataset.ETF_UNADJUSTED_DAILY
    )
    execution_frame, execution_metadata = _fetch_result(
        flows,
        dataset=execution_dataset,
        symbol=normalized_symbol,
        start=start,
        end=end,
        frequency="daily",
        label=f"{normalized_symbol} execution daily",
    )
    execution_frame = _normalize_frame(execution_frame, "execution daily")
    last_session = pd.Timestamp(execution_frame["Date"].max()).date()
    calendar_end = (pd.Timestamp(last_session) + pd.Timedelta(days=20)).date()
    session_calendar, session_calendar_metadata = _fetch_result(
        flows,
        dataset=Dataset.TRADING_CALENDAR,
        symbol="SSE",
        start=start,
        end=calendar_end,
        frequency="daily",
        label="SSE trading calendar",
    )
    open_dates = pd.to_datetime(
        session_calendar.loc[session_calendar["IsOpen"].astype(int).eq(1), "Date"]
    )
    future = open_dates[open_dates.dt.date > last_session]
    if future.empty:
        raise ValueError("SSE trading calendar has no next session")
    next_session = future.iloc[0].date()
    calendar_metadata = session_calendar_metadata
    if next_session <= last_session:
        raise ValueError("next trading session must be after the latest complete close")
    if next_session <= end:
        raise ValueError(
            f"latest complete close {last_session} is behind requested end {end}"
        )
    adjusted_metadata = [
        item for item in metadata.values() if item.get("adjustment") is not None
    ]
    if adjusted_metadata and len(adjusted_metadata) != len(metadata):
        raise ValueError("all frequencies must use the same adjustment contract")
    adjustment_records = {
        (
            item.get("adjustment"),
            item.get("adjustment_factor_source"),
            item.get("adjustment_factor_sha256"),
        )
        for item in adjusted_metadata
    }
    adjustment: dict[str, str] | None = None
    if adjustment_records:
        if len(adjustment_records) != 1:
            raise ValueError("frequencies use inconsistent adjustment factors")
        mode, factor_source, factor_sha256 = adjustment_records.pop()
        if mode != "hfq" or not factor_source or not factor_sha256:
            raise ValueError("market data must declare a complete hfq adjustment contract")
        adjustment = {
            "mode": mode,
            "factor_source": factor_source,
            "factor_sha256": factor_sha256,
        }
    normalized_daily = _normalize_frame(frames["daily"], "daily")
    observed_end = pd.Timestamp(normalized_daily["Date"].max()).date()
    if observed_end != last_session:
        raise ValueError("adjusted and execution daily cutoffs differ")
    validation = {
        "status": "PASS",
        "contract": "tdr.market-publication.v1",
        "source": "DFLS",
    }

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    staging = create_temporary_directory(
        data_dir, "market-data", prefix=f"{code.lower()}-"
    )
    published: list[Path] = []
    backups: dict[Path, Path] = {}
    try:
        file_records: dict[str, dict[str, object]] = {}
        for period in FREQUENCIES:
            output = _csv_frame(frames[period], period)
            time_column = "datetime" if period == "30m" else "date"
            years = pd.to_datetime(output[time_column]).dt.year
            for year in sorted(years.unique()):
                yearly = output.loc[years == year].reset_index(drop=True)
                filename = f"{code}_{period}_{int(year)}.csv"
                path = staging / filename
                yearly.to_csv(
                    path,
                    index=False,
                    encoding="utf-8-sig",
                    lineterminator="\n",
                )
                timestamps = pd.to_datetime(yearly[time_column])
                file_records[filename] = {
                    "frequency": period,
                    "year": int(year),
                    "rows": int(len(yearly)),
                    "first": timestamps.min().isoformat(),
                    "last": timestamps.max().isoformat(),
                    "sha256": raw_file_sha256(path),
                }
        execution_records: dict[str, dict[str, object]] = {}
        execution_output = _csv_frame(execution_frame, "daily")
        execution_years = pd.to_datetime(execution_output["date"]).dt.year
        for year in sorted(execution_years.unique()):
            yearly = execution_output.loc[execution_years == year].reset_index(drop=True)
            filename = f"{code}_execution_daily_{int(year)}.csv"
            path = staging / filename
            yearly.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
            timestamps = pd.to_datetime(yearly["date"])
            execution_records[filename] = {
                "frequency": "daily",
                "year": int(year),
                "rows": int(len(yearly)),
                "first": timestamps.min().isoformat(),
                "last": timestamps.max().isoformat(),
                "sha256": raw_file_sha256(path),
            }
        generated_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema_version": 2 if adjustment is not None else 1,
            "symbol": normalized_symbol,
            "name": resolved_name,
            "code": code,
            "asset_type": normalized_asset,
            "vendor": "tushare",
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "generated_at_utc": generated_at,
            "files": file_records,
            "fetch_metadata": metadata,
        }
        if adjustment is not None:
            manifest["adjustment"] = adjustment
        execution_manifest = {
            "schema_version": 2,
            "symbol": normalized_symbol,
            "name": resolved_name,
            "code": code,
            "asset_type": normalized_asset,
            "vendor": execution_metadata["vendor"],
            "adjustment": "none",
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "next_trading_session": next_session.isoformat(),
            "calendar": calendar_metadata,
            "session_calendar": session_calendar_metadata,
            "generated_at_utc": generated_at,
            "files": execution_records,
            "fetch_metadata": execution_metadata,
        }
        (staging / f"{code}_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        (staging / f"{code}_validation.json").write_text(
            json.dumps({**validation, "generated_at_utc": generated_at}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8", newline="\n",
        )
        (staging / f"{code}_execution_manifest.json").write_text(
            json.dumps(execution_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        candidates = [
            *[staging / filename for filename in file_records],
            *[staging / filename for filename in execution_records],
            staging / f"{code}_manifest.json",
            staging / f"{code}_validation.json",
            staging / f"{code}_execution_manifest.json",
        ]
        backup_root = staging / "backups"
        backup_root.mkdir()
        for source in candidates:
            destination = data_dir / source.name
            if destination.exists():
                backup = backup_root / source.name
                destination.replace(backup)
                backups[destination] = backup
            source.replace(destination)
            published.append(destination)
    except Exception:
        for destination in reversed(published):
            if destination.exists():
                destination.unlink()
        for destination, backup in backups.items():
            if backup.exists():
                backup.replace(destination)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "symbol": normalized_symbol,
        "asset_type": normalized_asset,
        "validation_status": "PASS",
        "data_cutoff": last_session.isoformat(),
        "manifest": str((data_dir / f"{code}_manifest.json").resolve()),
        "execution_price_manifest": str(
            (data_dir / f"{code}_execution_manifest.json").resolve()
        ),
        "files": sorted(file_records),
        "execution_price_files": sorted(execution_records),
    }
