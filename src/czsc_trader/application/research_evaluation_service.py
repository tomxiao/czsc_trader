"""Researcher-facing evaluation entry for the explicit Harness contract."""

from __future__ import annotations

from datetime import date
from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, BinaryIO, Iterator, Mapping

import pandas as pd
from strategy_runtime import StrategyCandidate
from strategy_manager import CandidateKey, StrategyManagerError

from czsc_trader.research_tools import (
    EvaluationBenchmark,
    EvaluationCost,
    EvaluationRequest,
    EvaluationResult,
    EvaluationWindow,
    EvaluationFiles,
    evaluate_strategy,
)
from czsc_trader.temp_workspace import create_temporary_directory, replace_directory

from .context import RepositoryContext
from .delivery_service import _resolve
from .errors import ValidationError
from .research_paths import repository_path
from .results import CommandResult


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _exact(value: Mapping[str, object], expected: set[str], name: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown or missing:
        raise ValueError(f"{name} fields differ: missing={missing}, unknown={unknown}")


def _json_number(value: object, name: str, *, integer: bool = False) -> int | float:
    accepted = (int,) if integer else (int, float)
    if type(value) not in accepted:
        raise TypeError(f"{name} must be a JSON {'integer' if integer else 'number'}")
    return value if integer else float(value)


def _json_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a JSON string")
    return value


def _safe_child(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "\\" in value or ":" in value:
        raise ValueError(f"{field} contains an unsafe path")
    return _resolve(root, relative.as_posix())


def _evaluation_request(
    context: RepositoryContext,
    path: Path,
    input_root: Path,
) -> tuple[EvaluationRequest, Path]:
    raw = _read_object(path)
    _exact(
        raw,
        {
            "schema_version", "experiment_id", "strategy", "market", "windows",
            "capital", "costs", "benchmark", "execution",
        },
        "evaluation request",
    )
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 2:
        raise ValueError("evaluation request schema is invalid")

    strategy_raw = raw["strategy"]
    if not isinstance(strategy_raw, dict):
        raise ValueError("evaluation strategy must be an object")
    _exact(
        strategy_raw,
        {
            "strategy_id", "candidate_id", "strategy_payload", "runtime_root",
            "runtime_binding",
        },
        "evaluation strategy",
    )
    CandidateKey(strategy_raw["strategy_id"], strategy_raw["candidate_id"])
    runtime_root = _safe_child(input_root, strategy_raw["runtime_root"], "runtime_root")
    binding_path = _safe_child(
        input_root, strategy_raw["runtime_binding"], "runtime_binding"
    )
    binding = _read_object(binding_path)
    candidate = StrategyCandidate(
        _json_string(strategy_raw["strategy_id"], "strategy_id"),
        _json_string(strategy_raw["candidate_id"], "candidate_id"),
        strategy_raw["strategy_payload"],
        runtime_root,
    )

    market = raw["market"]
    if not isinstance(market, dict):
        raise ValueError("evaluation market must be an object")
    _exact(market, {"symbol", "asset_type", "data_cutoff"}, "evaluation market")
    cutoff = date.fromisoformat(_json_string(market["data_cutoff"], "data_cutoff"))

    raw_windows = raw["windows"]
    if not isinstance(raw_windows, list) or not raw_windows:
        raise ValueError("evaluation windows must be a non-empty list")
    windows = []
    for item in raw_windows:
        if not isinstance(item, dict):
            raise ValueError("evaluation window must be an object")
        _exact(item, {"window_id", "start", "end"}, "evaluation window")
        windows.append(
            EvaluationWindow(
                _json_string(item["window_id"], "window_id"),
                date.fromisoformat(_json_string(item["start"], "start")),
                date.fromisoformat(_json_string(item["end"], "end")),
            )
        )

    capital = raw["capital"]
    if not isinstance(capital, dict):
        raise ValueError("evaluation capital must be an object")
    _exact(capital, {"initial_cash"}, "evaluation capital")

    raw_costs = raw["costs"]
    if not isinstance(raw_costs, list) or not raw_costs:
        raise ValueError("evaluation costs must be a non-empty list")
    costs = []
    for item in raw_costs:
        if not isinstance(item, dict):
            raise ValueError("evaluation cost must be an object")
        _exact(
            item,
            {"scenario_id", "one_way_cost", "measurement_tier"},
            "evaluation cost",
        )
        costs.append(
            EvaluationCost(
                _json_string(item["scenario_id"], "scenario_id"),
                _json_number(item["one_way_cost"], "one_way_cost"),
                _json_string(item["measurement_tier"], "measurement_tier"),
            )
        )

    benchmark_raw = raw["benchmark"]
    if not isinstance(benchmark_raw, dict):
        raise ValueError("evaluation benchmark must be an object")
    benchmark = EvaluationBenchmark.from_dict(benchmark_raw)

    execution = raw["execution"]
    if not isinstance(execution, dict):
        raise ValueError("evaluation execution must be an object")
    _exact(
        execution,
        {"mode", "workers", "frequency_window_days"},
        "evaluation execution",
    )

    request = EvaluationRequest(
        repository_root=context.root,
        experiment_id=_json_string(raw["experiment_id"], "experiment_id"),
        strategy=candidate,
        runtime_binding=binding,
        symbol=_json_string(market["symbol"], "symbol"),
        asset_type=_json_string(market["asset_type"], "asset_type"),
        windows=tuple(windows),
        data_cutoff=cutoff,
        initial_cash=_json_number(capital["initial_cash"], "initial_cash"),
        costs=tuple(costs),
        benchmark=benchmark,
        workers=_json_number(execution["workers"], "workers", integer=True),
        frequency_window_days=_json_number(execution["frequency_window_days"], "frequency_window_days", integer=True),
        execution_mode=_json_string(execution["mode"], "mode"),
    )
    return request, binding_path


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _evaluation_artifacts(result: EvaluationResult) -> Iterator[tuple[str, pd.DataFrame | dict]]:
    """The complete output set, shared by publication and repeat verification."""
    for run in result.runs:
        if run.buyhold is None:
            raise ValueError("research evaluation has no BuyHold evidence")
        relative = PurePosixPath(run.window_id) / run.scenario_id
        tables = {
            "signals.csv": run.signals.decisions,
            "decisions.csv": run.execution.decisions,
            "orders.csv": run.execution.orders,
            "fills.csv": run.execution.fills,
            "account_daily.csv": run.execution.account_daily,
            "trades.csv": run.execution.trades,
            "buyhold_account_daily.csv": run.buyhold.account_daily,
            "buyhold_orders.csv": run.buyhold.orders,
        }
        for name, frame in tables.items():
            yield (relative / name).as_posix(), frame
        for name, value in (
            ("observation.json", run.observation.to_dict()),
            ("buyhold_metrics.json", run.buyhold.metrics),
        ):
            yield (relative / name).as_posix(), value


class _HashingTextWriter:
    """Hash bounded serializer chunks, optionally writing the same UTF-8 bytes."""

    def __init__(self, stream: BinaryIO | None):
        self.stream = stream
        self.digest = sha256()

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        self.digest.update(encoded)
        if self.stream is not None:
            self.stream.write(encoded)
        return len(value)


def _artifact_hashes(result: EvaluationResult, destination: Path | None = None) -> dict[str, str]:
    hashes = {}
    for name, value in _evaluation_artifacts(result):
        if destination is None:
            output = nullcontext(None)
        else:
            path = _safe_child(destination, name, "evaluation artifact")
            path.parent.mkdir(parents=True, exist_ok=True)
            output = path.open("wb")
        with output as stream:
            writer = _HashingTextWriter(stream)
            if isinstance(value, pd.DataFrame):
                value.to_csv(writer, index=False, lineterminator="\n", chunksize=10_000)
            else:
                json.dump(value, writer, ensure_ascii=False, indent=2, default=str)
                writer.write("\n")
            hashes[name] = writer.digest.hexdigest()
    return hashes


def _run_documents(result: EvaluationResult) -> list[dict[str, object]]:
    if any(run.identity is None for run in result.runs):
        raise ValueError("published evaluation runs require verified identities")
    return [
        {
            "candidate_id": run.candidate_id,
            "identity": run.identity.to_dict(),
            "evaluation_id": run.identity.evaluation_id,
            "window_id": run.window_id,
            "scenario_id": run.scenario_id,
            "signal_data_identity": run.signals.data_identity,
            "directory": (PurePosixPath(run.window_id) / run.scenario_id).as_posix(),
        }
        for run in result.runs
    ]


def _publish_result(
    context: RepositoryContext,
    destination: Path,
    result: EvaluationResult,
) -> tuple[Path, dict[str, object]]:
    result_path = destination / "evaluation_result.json"
    if destination.exists():
        if not result_path.is_file():
            raise ValueError("evaluation artifact directory is incomplete")
        existing = _read_object(result_path)
        _exact(
            existing,
            {
                "schema_version", "status", "request_hash", "result_hash",
                "strategy_identity", "runtime_binding_hash", "data_identity",
                "execution_mode", "runs", "files",
            },
            "evaluation result",
        )
        expected_identity = {
            "schema_version": 2,
            "status": "PASS",
            "request_hash": result.request_hash,
            "result_hash": result.result_hash,
            "strategy_identity": result.strategy_identity,
            "runtime_binding_hash": result.runtime_binding_hash,
            "data_identity": result.data_identity,
            "execution_mode": result.execution_mode,
        }
        if any(existing.get(key) != value for key, value in expected_identity.items()):
            raise ValueError("evaluation result identity differs from the repeated execution")
        if existing.get("runs") != _run_documents(result):
            raise ValueError("evaluation run manifest differs from the repeated execution")
        files = existing.get("files")
        if not isinstance(files, dict):
            raise ValueError("evaluation artifact manifest is missing")
        expected_files = _artifact_hashes(result)
        if set(files) != set(expected_files):
            raise ValueError("evaluation artifact manifest has an incomplete or unexpected file set")
        if files != expected_files:
            raise ValueError("evaluation artifact hash differs from the repeated execution")
        actual_files = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*") if path.is_file()
        }
        if actual_files != set(expected_files) | {"evaluation_result.json"}:
            raise ValueError("evaluation artifact directory has an incomplete or unexpected file set")
        for name, expected in files.items():
            target = _safe_child(destination, name, "evaluation artifact")
            if not target.is_file() or _file_hash(target) != expected:
                raise ValueError(f"evaluation artifact hash differs: {name}")
        return destination, existing

    staging = create_temporary_directory(
        destination,
        "research-evaluation",
        prefix="evaluation-",
        repository_root=context.root,
    )
    try:
        run_documents = _run_documents(result)
        files = _artifact_hashes(result, staging)
        document = {
            "schema_version": 2,
            "status": "PASS",
            "request_hash": result.request_hash,
            "result_hash": result.result_hash,
            "strategy_identity": result.strategy_identity,
            "runtime_binding_hash": result.runtime_binding_hash,
            "data_identity": result.data_identity,
            "execution_mode": result.execution_mode,
            "runs": run_documents,
            "files": dict(sorted(files.items())),
        }
        _write_json(staging / "evaluation_result.json", document)
        destination.parent.mkdir(parents=True, exist_ok=True)
        replace_directory(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination, document


def evaluate_research_request(
    context: RepositoryContext,
    input_path: Path,
    *,
    files: EvaluationFiles,
) -> CommandResult:
    """Execute and atomically publish one complete research evaluation request."""

    try:
        if type(files) is not EvaluationFiles:
            raise TypeError("file evaluation requires EvaluationFiles")
        path = repository_path(context, input_path)
        input_root = _resolve(context.root, files.input_root)
        destination = _resolve(context.root, files.output_path)
        if not path.is_file() or not input_root.is_dir():
            raise ValueError("evaluation request or input root is unavailable")
        request, binding = _evaluation_request(context, path, input_root)
        if any(p.is_relative_to(destination) for p in (path, request.strategy.source_root, binding)):
            raise ValueError("evaluation output overlaps its input files")
        if destination.is_relative_to(request.strategy.source_root):
            raise ValueError("evaluation output overlaps its runtime source")
        result = evaluate_strategy(request)
        output, document = _publish_result(context, destination, result)
    except (StrategyManagerError, KeyError, TypeError, ValueError, OSError) as exc:
        raise ValidationError(
            "research_evaluation_failed",
            str(exc),
            context={"command": "research.evaluate", "input": str(input_path)},
        ) from exc
    return CommandResult(
        "PASS",
        "research.evaluate",
        {
            "request_hash": document["request_hash"],
            "result_hash": document["result_hash"],
            "strategy_identity": document["strategy_identity"],
            "runtime_binding_hash": document["runtime_binding_hash"],
            "data_identity": document["data_identity"],
            "execution_mode": document["execution_mode"],
            "run_count": len(document["runs"]),
        },
        {"directory": output.relative_to(context.root).as_posix()},
    )
