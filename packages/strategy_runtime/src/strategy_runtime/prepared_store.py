"""Private on-disk format for data prepared by one StrategyInstance."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import pandas as pd
from dataflows import DataIdentity, DataRequest, DataResult, DataStatus, canonical_frame_sha256

from .contracts import StrategyIdentity, TradableWindow
from .errors import RuntimeContractError
from .models import canonical_sha256
from .preparation import PreparedInputs, prepared_inputs_identity


_MANIFEST = "prepared-data.json"
_WORKSPACE_MANIFEST = "strategy-space.json"
_PREPARATIONS = "preparations"
_SAFE = re.compile(r"[A-Za-z0-9_.-]+")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_value(value.item())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise RuntimeContractError(
        f"prepared-data metadata is not JSON compatible: {type(value)}"
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_identity(
    strategy: StrategyIdentity,
    tradable_window: TradableWindow,
) -> dict[str, object]:
    return {
        "reference_id": strategy.reference_id,
        "release_hash": strategy.release_hash,
        "runtime_sha256": strategy.runtime_sha256,
        "symbol": strategy.symbol,
        "tradable_window": {
            "start": tradable_window.start.isoformat(),
            "end": tradable_window.end.isoformat(),
        },
    }


def _workspace_identity(strategy: StrategyIdentity) -> dict[str, object]:
    return {
        "reference_id": strategy.reference_id,
        "release_hash": strategy.release_hash,
        "runtime_sha256": strategy.runtime_sha256,
        "symbol": strategy.symbol,
    }


def _preparation_directory(directory: Path, tradable_window: TradableWindow) -> Path:
    name = f"{tradable_window.start:%Y%m%d}_{tradable_window.end:%Y%m%d}"
    return Path(directory).resolve() / _PREPARATIONS / name


def _load_workspace(root: Path, strategy: StrategyIdentity) -> bool:
    path = root / _WORKSPACE_MANIFEST
    if not path.is_file():
        if (root / _MANIFEST).exists():
            raise RuntimeContractError("legacy prepared-data space is unsupported")
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeContractError(f"cannot read strategy data space: {exc}") from exc
    expected = _workspace_identity(strategy)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or any(manifest.get(key) != value for key, value in expected.items())
    ):
        raise RuntimeContractError("data directory belongs to another strategy")
    manifest_hash = manifest.pop("manifest_sha256", None)
    if manifest_hash != canonical_sha256(manifest):
        raise RuntimeContractError("strategy data-space manifest was modified")
    return True


def _ensure_workspace(root: Path, strategy: StrategyIdentity) -> None:
    if _load_workspace(root, strategy):
        return
    manifest = {"schema_version": 1, **_workspace_identity(strategy)}
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    path = root / _WORKSPACE_MANIFEST
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except FileExistsError:
        _load_workspace(root, strategy)


def load_prepared_inputs(
    directory: Path,
    *,
    strategy: StrategyIdentity,
    tradable_window: TradableWindow,
) -> PreparedInputs | None:
    root = Path(directory).resolve()
    if not _load_workspace(root, strategy):
        return None
    prepared_root = _preparation_directory(root, tradable_window)
    manifest_path = prepared_root / _MANIFEST
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeContractError(f"cannot read prepared data: {exc}") from exc
    expected = _manifest_identity(strategy, tradable_window)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 2
        or any(manifest.get(key) != value for key, value in expected.items())
    ):
        raise RuntimeContractError(
            "data directory belongs to another strategy instance"
        )
    manifest_hash = manifest.pop("manifest_sha256", None)
    if manifest_hash != canonical_sha256(manifest):
        raise RuntimeContractError("prepared-data manifest was modified")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise RuntimeContractError("prepared data has no inputs")
    requests: dict[str, DataRequest] = {}
    results: dict[str, DataResult] = {}
    for name, raw in sorted(inputs.items()):
        if not isinstance(name, str) or _SAFE.fullmatch(name) is None:
            raise RuntimeContractError("prepared input name is unsafe")
        if not isinstance(raw, dict):
            raise RuntimeContractError(f"prepared input metadata is invalid: {name}")
        filename = raw.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RuntimeContractError(f"prepared input filename is unsafe: {name}")
        path = (prepared_root / filename).resolve()
        if path.parent != prepared_root or not path.is_file():
            raise RuntimeContractError(f"prepared input file is unavailable: {name}")
        if _file_sha256(path) != raw.get("file_sha256"):
            raise RuntimeContractError(f"prepared input file was modified: {name}")
        frame = pd.read_csv(path)
        if canonical_frame_sha256(frame) != raw.get("content_sha256"):
            raise RuntimeContractError(f"prepared input content differs: {name}")
        request = raw.get("request")
        identity = raw.get("identity")
        if not isinstance(request, dict) or not isinstance(identity, dict):
            raise RuntimeContractError(f"prepared input contract is invalid: {name}")
        if identity.get("content_sha256") != raw.get("content_sha256"):
            raise RuntimeContractError(
                f"prepared input identity differs from stored content: {name}"
            )
        requests[name] = DataRequest(**request)
        results[name] = DataResult(
            DataStatus.READY,
            frame,
            DataIdentity(**identity),
        )
    try:
        available_through = pd.Timestamp(manifest["available_through"]).date()
        calendar_dates = tuple(
            pd.Timestamp(item).date() for item in manifest["calendar_dates"]
        )
        calculation_dates = tuple(
            pd.Timestamp(item).date() for item in manifest["calculation_dates"]
        )
        signal_dates = {
            pd.Timestamp(key).date(): pd.Timestamp(value).date()
            for key, value in manifest["signal_dates"].items()
        }
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeContractError("prepared data dates are invalid") from exc
    actual_identity = prepared_inputs_identity(
        strategy=strategy,
        tradable_window=tradable_window,
        available_through=available_through,
        signal_dates=signal_dates,
        results=results,
    )
    if actual_identity != manifest.get("data_identity"):
        raise RuntimeContractError("prepared data identity differs")
    return PreparedInputs(
        strategy,
        tradable_window,
        available_through,
        actual_identity,
        requests,
        results,
        calendar_dates,
        signal_dates,
        calculation_dates,
    )


def save_prepared_inputs(
    prepared: PreparedInputs, directory: Path
) -> PreparedInputs:
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _ensure_workspace(root, prepared.strategy)
    prepared_root = _preparation_directory(root, prepared.tradable_window)
    prepared_root.parent.mkdir(exist_ok=True)
    if prepared_root.exists():
        raise RuntimeContractError("prepared data already exists but could not be reused")
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    staging = temporary_root / f"prepare-{uuid4().hex}"
    staging.mkdir()
    inputs: dict[str, object] = {}
    stored_results: dict[str, DataResult] = {}
    try:
        for name in sorted(prepared.results):
            if _SAFE.fullmatch(name) is None:
                raise RuntimeContractError(f"prepared input name is unsafe: {name}")
            result = prepared.results[name]
            request = prepared.requests[name]
            if result.status is not DataStatus.READY or result.identity is None:
                raise RuntimeContractError(f"cannot store incomplete prepared input: {name}")
            filename = f"prepared-{name}-{result.identity.content_sha256[:16]}.csv.gz"
            staged = staging / filename
            result.dataframe.to_csv(
                staged,
                index=False,
                encoding="utf-8",
                lineterminator="\n",
                compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
            )
            stored = pd.read_csv(staged)
            stored_sha256 = canonical_frame_sha256(stored)
            stored_identity = DataIdentity(
                dataset=result.identity.dataset,
                source=result.identity.source,
                symbol=result.identity.symbol,
                data_start=result.identity.data_start,
                data_cutoff=result.identity.data_cutoff,
                content_sha256=stored_sha256,
                metadata=result.identity.metadata,
            )
            stored_results[name] = DataResult(
                DataStatus.READY,
                stored,
                stored_identity,
                warnings=result.warnings,
            )
            inputs[name] = {
                "file": filename,
                "file_sha256": _file_sha256(staged),
                "content_sha256": stored_sha256,
                "request": {
                    "dataset": str(request.dataset),
                    "symbol": request.symbol,
                    "start": request.start,
                    "end": request.end,
                    "required_cutoff": request.required_cutoff,
                    "frequency": request.frequency,
                    "options": _json_value(request.options),
                },
                "identity": {
                    "dataset": result.identity.dataset,
                    "source": result.identity.source,
                    "symbol": result.identity.symbol,
                    "data_start": result.identity.data_start,
                    "data_cutoff": result.identity.data_cutoff,
                    "content_sha256": stored_sha256,
                    "metadata": _json_value(result.identity.metadata),
                },
            }
        stored_data_identity = prepared_inputs_identity(
            strategy=prepared.strategy,
            tradable_window=prepared.tradable_window,
            available_through=prepared.available_through,
            signal_dates=prepared.signal_dates,
            results=stored_results,
        )
        manifest = {
            "schema_version": 2,
            **_manifest_identity(prepared.strategy, prepared.tradable_window),
            "available_through": prepared.available_through.isoformat(),
            "data_identity": stored_data_identity,
            "calendar_dates": [item.isoformat() for item in prepared.calendar_dates],
            "signal_dates": {
                key.isoformat(): value.isoformat()
                for key, value in prepared.signal_dates.items()
            },
            "calculation_dates": [
                item.isoformat() for item in prepared.calculation_dates
            ],
            "inputs": inputs,
        }
        manifest["manifest_sha256"] = canonical_sha256(manifest)
        manifest_path = staging / _MANIFEST
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
        staging.replace(prepared_root)
    finally:
        if staging.exists():
            for path in staging.glob("*"):
                path.unlink(missing_ok=True)
            staging.rmdir()
        try:
            temporary_root.rmdir()
        except OSError:
            pass
    return PreparedInputs(
        prepared.strategy,
        prepared.tradable_window,
        prepared.available_through,
        stored_data_identity,
        prepared.requests,
        stored_results,
        prepared.calendar_dates,
        prepared.signal_dates,
        prepared.calculation_dates,
    )
