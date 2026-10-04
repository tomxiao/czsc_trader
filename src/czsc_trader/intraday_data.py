"""Validated high-frequency research data kept beside the core research pool."""

from __future__ import annotations

from dataclasses import dataclass
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


INTRADAY_RESEARCH_FREQUENCIES = ("15m", "5m", "1m")
VENDOR_COLUMNS = ("Date", "Open", "High", "Low", "Close", "Volume", "Amount")


@dataclass(frozen=True)
class IntradayResearchData:
    symbol: str
    frames: dict[str, pd.DataFrame]
    manifest: dict[str, object]
    hashes: dict[str, str]


def _symbol_parts(symbol: str) -> tuple[str, str]:
    normalized = str(symbol).strip().upper()
    match = re.fullmatch(r"(\d{6})\.(SH|SZ)", normalized)
    if not match:
        raise ValueError("symbol must be a six-digit A-share code ending in SH or SZ")
    return normalized, match.group(1)


def _normalize_frame(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    missing = sorted(set(VENDOR_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"{period}: DFLS result is missing columns {missing}")
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
    symbol: str,
    start: date,
    end: date,
    period: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    request = DataRequest(Dataset.ETF_OHLCV, symbol, start.isoformat(), end.isoformat(), end.isoformat(), period)
    preparation = dataflows.prepare((request,), policy=PreparePolicy.REUSE)
    if not preparation.ready:
        raise ValueError(f"DFLS preparation failed: {preparation.items}")
    result = dataflows.fetch(request, prepared=preparation.reference)
    frame, metadata = _ready_result(result, f"{symbol} {period}")
    metadata["prepared"] = {
        "space_id": str(preparation.reference.space_id),
        "preparation_id": str(preparation.reference.preparation_id),
        "manifest_sha256": preparation.reference.manifest_sha256,
    }
    return frame, metadata



def _csv_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.rename(
        columns={
            "Date": "datetime",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Amount": "amount",
        }
    ).copy()
    result["datetime"] = pd.to_datetime(result["datetime"]).dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return result


def prepare_intraday_research_data(
    symbol: str,
    start: date,
    end: date,
    data_dir: Path,
    *,
    dataflows: Dataflows | None = None,
    env_file: str | Path | None = None,
) -> dict[str, object]:
    """Fetch, reconcile and atomically publish 15m/5m/1m ETF research bars."""

    normalized_symbol, code = _symbol_parts(symbol)
    if start > end:
        raise ValueError("start must not be after end")
    flows = dataflows if dataflows is not None else Dataflows(
        base_dir=Path(data_dir).resolve(), space=DataSpace(Path("assets")),
        providers=ProviderConfig(env_file=Path(env_file) if env_file is not None else None),
    )
    _daily_raw, daily_metadata = _fetch_result(
        flows, normalized_symbol, start, end, "daily"
    )
    frames: dict[str, pd.DataFrame] = {}
    metadata: dict[str, dict[str, object]] = {}
    factor_hashes = {str(daily_metadata.get("adjustment_factor_sha256", ""))}
    for period in INTRADAY_RESEARCH_FREQUENCIES:
        raw, item_metadata = _fetch_result(
            flows, normalized_symbol, start, end, period
        )
        frame = _normalize_frame(raw, period)
        frames[period] = frame
        metadata[period] = item_metadata
        factor_hashes.add(str(item_metadata.get("adjustment_factor_sha256", "")))

    validation: dict[str, object] = {}
    for period, frame in frames.items():
        validation[period] = {
            "status": "PASS",
            "contract": "tdr.intraday-publication.v1",
            "source": "DFLS",
            "bar_count": int(len(frame)),
        }
    if "" in factor_hashes or len(factor_hashes) != 1:
        raise ValueError("daily and minute frequencies use different adjustment factors")

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    staging = create_temporary_directory(
        data_dir, "intraday-data", prefix=f"{code.lower()}-"
    )
    try:
        file_records: dict[str, dict[str, object]] = {}
        for period, frame in frames.items():
            output = _csv_frame(frame)
            years = pd.to_datetime(output["datetime"]).dt.year
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
                timestamps = pd.to_datetime(yearly["datetime"])
                file_records[filename] = {
                    "frequency": period,
                    "year": int(year),
                    "rows": int(len(yearly)),
                    "first": timestamps.min().isoformat(),
                    "last": timestamps.max().isoformat(),
                    "sha256": raw_file_sha256(path),
                }
        manifest = {
            "schema_version": 1,
            "symbol": normalized_symbol,
            "asset_type": "etf",
            "vendor": "tushare",
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "frequencies": list(INTRADAY_RESEARCH_FREQUENCIES),
            "adjustment": {
                "mode": "hfq",
                "factor_source": "fund_adj",
                "factor_sha256": factor_hashes.pop(),
            },
            "validation": validation,
            "fetch_metadata": metadata,
            "files": file_records,
        }
        manifest_path = staging / f"{code}_intraday_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        published_names = sorted(file_records) + [manifest_path.name]
        for filename in published_names:
            source = staging / filename
            destination = data_dir / filename
            shutil.copyfile(source, destination)
        return {
            "status": "PASS",
            "manifest": str(data_dir / manifest_path.name),
            "files": len(file_records),
            "validation": validation,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def load_intraday_research_data(data_dir: Path, symbol: str) -> IntradayResearchData:
    """Load and hash-check a published high-frequency research generation."""

    normalized_symbol, code = _symbol_parts(symbol)
    data_dir = Path(data_dir)
    manifest_path = data_dir / f"{code}_intraday_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("symbol") != normalized_symbol:
        raise ValueError("intraday manifest symbol does not match request")
    records = manifest.get("files")
    if not isinstance(records, dict) or not records:
        raise ValueError("intraday manifest files must be a non-empty object")
    grouped: dict[str, list[pd.DataFrame]] = {
        item: [] for item in INTRADAY_RESEARCH_FREQUENCIES
    }
    hashes: dict[str, str] = {}
    for filename, record in records.items():
        if not isinstance(record, dict):
            raise ValueError(f"{filename}: invalid record")
        match = re.fullmatch(rf"{code}_(15m|5m|1m)_(\d{{4}})\.csv", str(filename))
        if not match or record.get("frequency") != match.group(1):
            raise ValueError(f"{filename}: invalid intraday filename or frequency")
        path = data_dir / str(filename)
        digest = raw_file_sha256(path)
        if digest != str(record.get("sha256", "")).lower():
            raise ValueError(f"{filename}: SHA-256 differs from manifest")
        frame = pd.read_csv(path, encoding="utf-8-sig")
        frame = frame.rename(
            columns={
                "datetime": "Date",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
                "amount": "Amount",
            }
        )
        grouped[match.group(1)].append(_normalize_frame(frame, match.group(1)))
        hashes[str(filename)] = digest
    frames: dict[str, pd.DataFrame] = {}
    for period, pieces in grouped.items():
        if not pieces:
            raise ValueError(f"intraday manifest missing {period}")
        frame = pd.concat(pieces, ignore_index=True).sort_values("Date").reset_index(drop=True)
        frames[period] = frame
    return IntradayResearchData(normalized_symbol, frames, manifest, hashes)
