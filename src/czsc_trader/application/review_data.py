"""TDR-owned, offline review snapshots built through SRT and DFLS contracts."""

from __future__ import annotations

from dataclasses import replace, asdict
from uuid import UUID
from dataflows import DataRequest, NoParameters, PreparedDataRef
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from strategy_runtime import (
    canonical_sha256, StrategyInputBinding,
)

from czsc_trader.backtesting.execution_data import BacktestExecutionData
from czsc_trader.backtesting import _dataflows
from czsc_trader.backtesting.srt_bridge import (
    build_srt_signal_replay,
    execution_intraday_frequencies,
)
from czsc_trader.temp_workspace import create_temporary_directory, replace_directory


MANIFEST = "review_dataset.json"
TABLES = (
    "adjusted_daily",
    "execution_daily",
    "execution_intraday",
    "execution_five_minute",
)


def _hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256(stream.read()).hexdigest()


def _child(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if Path(name).is_absolute() or path.parent != root.resolve():
        raise ValueError(f"review snapshot requires a direct child filename: {name}")
    return path


def _snapshot_file(root: Path, name: str) -> Path:
    relative = Path(name)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"review snapshot contains an unsafe path: {name}")
    return path


def verify_review_dataset(directory: Path, expected_hash: str | None = None) -> dict:
    raw = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    digest = raw.pop("snapshot_hash")
    if raw.get("schema_version") != 3 or canonical_sha256(raw) != digest:
        raise ValueError("review dataset manifest hash mismatch")
    if expected_hash is not None and expected_hash != digest:
        raise ValueError("review dataset differs from the sealed snapshot")
    if not raw.get("files") or set(raw.get("tables", {})) != set(TABLES):
        raise ValueError("review dataset manifest is incomplete")
    for name, expected in raw["files"].items():
        if _hash_file(_snapshot_file(directory, name)) != expected:
            raise ValueError(f"review dataset file hash mismatch: {name}")
    for item in raw["tables"].values():
        if item is not None and item["file"] not in raw["files"]:
            raise ValueError("review dataset table is not hash-bound")
    return {**raw, "snapshot_hash": digest}


def load_review_dataset(
    directory: Path, expected_hash: str | None = None
) -> BacktestExecutionData:
    manifest = verify_review_dataset(directory, expected_hash)
    frames = {}
    for name, item in manifest["tables"].items():
        if item is None:
            frames[name] = None
            continue
        frame = pd.read_csv(
            _child(directory, item["file"]), float_precision="round_trip",
            dtype={key: value for key, value in item["dtypes"].items() if key not in item["dates"]},
        )
        for column in item["dates"]:
            frame[column] = pd.to_datetime(frame[column], errors="raise")
        frames[name] = frame
    sessions = pd.DatetimeIndex(
        pd.to_datetime(manifest["evaluation_sessions"], errors="raise"), name="dt"
    )
    return BacktestExecutionData(
        root=directory,
        symbol=manifest["symbol"],
        asset_type=manifest["asset_type"],
        adjusted_daily=frames["adjusted_daily"],
        execution_daily=frames["execution_daily"],
        execution_intraday=frames["execution_intraday"],
        execution_five_minute=frames["execution_five_minute"],
        fingerprint=manifest["execution_data_identity"],
        cutoff=date.fromisoformat(manifest["cutoff"]),
        evaluation_sessions=sessions,
        requests={name: DataRequest(**{**item, "parameters": NoParameters()})
                  for name, item in manifest["execution_requests"].items()},
        prepared=PreparedDataRef(UUID(manifest["prepared"]["space_id"]),
                                 UUID(manifest["prepared"]["preparation_id"]),
                                 manifest["prepared"]["manifest_sha256"]),
        input_identities=manifest["input_identities"],
        strategy_bindings={key: StrategyInputBinding.from_mapping(value)
                           for key, value in manifest["strategy_bindings"].items()},
    )


def publish_review_dataset(
    context,
    manifest: dict,
    protocol,
    directory: Path,
    *,
    candidate_runtime_roots: dict[str, Path] | None = None,
) -> dict:
    """Publish once; incomplete staging never becomes a usable review dataset."""
    from czsc_trader.research_tools.evaluation import (
        _CandidateEvaluationContext, _snapshot, _prepare_evaluation_workspace,
    )
    dataflows = _dataflows.create_backtest_dataflows(context.root)

    recipe_hash = canonical_sha256({"manifest": manifest, "protocol": protocol.to_dict()})
    if directory.exists():
        raise ValueError(
            "unsealed review dataset already exists; remove it before recomputing"
        )
    periods = tuple((name, (pd.Timestamp(window["start"]), pd.Timestamp(window["end"])))
                    for name, window in manifest["windows"].items())
    run = _CandidateEvaluationContext(
        context, manifest["symbol"], manifest.get("asset_type", "etf"), periods,
        family_id=manifest["strategy_id"],
        candidate_runtime_roots=candidate_runtime_roots,
    )
    snapshots = [_snapshot(run, item) for item in manifest["candidates"]]
    strategies = [item[1] for item in snapshots]
    if not strategies or len({s.release_id for s in strategies}) != len(strategies):
        raise ValueError("review requires non-empty, unique runtime identities")
    execution_data = _prepare_evaluation_workspace(
        run, protocol, intraday_frequencies=tuple(sorted({frequency for s in strategies
            for frequency in execution_intraday_frequencies(s)})),
    ).execution_data
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Retain failed staging for diagnosis; only the final atomic rename publishes READY.
    staging = create_temporary_directory(context.root, "review-data", repository_root=context.root)
    frames = {
        key: getattr(execution_data, key) for key in TABLES
    }
    tables = {}
    for name, frame in frames.items():
        if frame is None:
            tables[name] = None
            continue
        filename = f"{name}.csv.gz"
        frame.to_csv(
            staging / filename, index=False, encoding="utf-8", lineterminator="\n",
            compression={"method": "gzip", "mtime": 0},
        )
        tables[name] = {"file": filename,
                        "dtypes": {col: str(dtype) for col, dtype in frame.dtypes.items()},
                        "dates": [col for col in frame if pd.api.types.is_datetime64_any_dtype(frame[col])]}
    sealed_execution = replace(execution_data, root=staging)
    runtimes = {}
    bindings = {}
    for snapshot, definition in snapshots:
        for _, (start, end) in periods:
            strategy, _ = build_srt_signal_replay(
                snapshot=snapshot,
                execution_data=sealed_execution,
                start=start,
                end=end,
                repository_root=context.root,
                dataflows=dataflows,
            )
            bindings[f"{snapshot.identity.reference}|{start.date()}|{end.date()}"] = strategy.input_binding.to_dict()
        runtimes[definition.release_id] = definition.runtime_sha256
    content = {
        "schema_version": 3, "recipe_hash": recipe_hash,
        "execution_requests": {name: asdict(request) for name, request in execution_data.requests.items()},
        "prepared": {"space_id": str(execution_data.prepared.space_id),
                     "preparation_id": str(execution_data.prepared.preparation_id),
                     "manifest_sha256": execution_data.prepared.manifest_sha256},
        "input_identities": execution_data.input_identities,
        "strategy_bindings": bindings,
        "symbol": run.symbol,
        "asset_type": run.asset_type,
        "cutoff": execution_data.cutoff.isoformat(),
        "execution_data_identity": execution_data.fingerprint,
        "evaluation_sessions": [
            item.date().isoformat() for item in execution_data.evaluation_sessions
        ],
        "runtimes": runtimes,
        "tables": tables,
        "files": {
            path.relative_to(staging).as_posix(): _hash_file(path)
            for path in sorted(item for item in staging.rglob("*") if item.is_file())
        },
    }
    content["snapshot_hash"] = canonical_sha256(content)
    (staging / MANIFEST).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    load_review_dataset(staging, content["snapshot_hash"])
    replace_directory(staging, directory)
    return content
