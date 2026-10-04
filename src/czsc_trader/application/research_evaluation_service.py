"""Researcher-facing evaluation entry for the explicit Harness contract."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Mapping

import pandas as pd
from strategy_runtime import StrategyCandidate

from czsc_trader.research_tools import (
    EvaluationBenchmark,
    EvaluationCost,
    EvaluationRequest,
    EvaluationResult,
    EvaluationWindow,
    evaluate_strategy,
)
from czsc_trader.temp_workspace import create_temporary_directory, replace_directory

from .context import RepositoryContext
from .errors import ValidationError
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


def _safe_child(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "\\" in value or ":" in value:
        raise ValueError(f"{field} contains an unsafe path")
    target = (root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field} escapes the experiment") from exc
    return target


def _request_path(context: RepositoryContext, input_path: Path) -> tuple[Path, Path]:
    path = input_path.resolve() if input_path.is_absolute() else (context.root / input_path).resolve()
    if not path.is_file():
        raise ValueError(f"evaluation request is unavailable: {path}")
    relative = path.relative_to(context.experiments_root.resolve())
    if len(relative.parts) != 3 or path.name != "evaluation_request.json":
        raise ValueError(
            "evaluation request must be experiments/<strategy>/<experiment>/evaluation_request.json"
        )
    return path, path.parent


def _evaluation_request(
    context: RepositoryContext,
    path: Path,
    experiment: Path,
) -> EvaluationRequest:
    raw = _read_object(path)
    _exact(
        raw,
        {
            "schema_version", "experiment_id", "strategy", "market", "windows",
            "capital", "costs", "benchmark", "execution",
        },
        "evaluation request",
    )
    if raw["schema_version"] != 2 or raw["experiment_id"] != experiment.name:
        raise ValueError("evaluation request schema or experiment identity is invalid")

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
    if strategy_raw["strategy_id"] != experiment.parent.name:
        raise ValueError("evaluation strategy identity differs from the experiment directory")
    runtime_root = _safe_child(experiment, strategy_raw["runtime_root"], "runtime_root")
    binding_path = _safe_child(
        experiment, strategy_raw["runtime_binding"], "runtime_binding"
    )
    binding = _read_object(binding_path)
    candidate = StrategyCandidate(
        str(strategy_raw["strategy_id"]),
        str(strategy_raw["candidate_id"]),
        strategy_raw["strategy_payload"],
        runtime_root,
    )

    market = raw["market"]
    if not isinstance(market, dict):
        raise ValueError("evaluation market must be an object")
    _exact(market, {"symbol", "asset_type", "data_cutoff"}, "evaluation market")
    cutoff = date.fromisoformat(str(market["data_cutoff"]))

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
                str(item["window_id"]),
                date.fromisoformat(str(item["start"])),
                date.fromisoformat(str(item["end"])),
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
                str(item["scenario_id"]),
                float(item["one_way_cost"]),
                str(item["measurement_tier"]),
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

    return EvaluationRequest(
        repository_root=context.root,
        experiment_id=experiment.name,
        strategy=candidate,
        runtime_binding=binding,
        symbol=str(market["symbol"]),
        asset_type=str(market["asset_type"]),
        windows=tuple(windows),
        data_cutoff=cutoff,
        initial_cash=float(capital["initial_cash"]),
        costs=tuple(costs),
        benchmark=benchmark,
        workers=int(execution["workers"]),
        frequency_window_days=int(execution["frequency_window_days"]),
        execution_mode=str(execution["mode"]),
    )


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


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


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
    experiment: Path,
    result: EvaluationResult,
) -> tuple[Path, dict[str, object]]:
    destination = experiment / "artifacts" / "evaluation"
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
        for name, expected in files.items():
            target = _safe_child(destination, name, "evaluation artifact")
            if not target.is_file() or _file_hash(target) != expected:
                raise ValueError(f"evaluation artifact hash differs: {name}")
        return destination, existing

    staging = create_temporary_directory(
        experiment,
        "research-evaluation",
        prefix=f"{experiment.name.lower()}-",
        repository_root=context.root,
    )
    try:
        run_documents = _run_documents(result)
        files: dict[str, str] = {}
        for run in result.runs:
            relative = PurePosixPath(run.window_id) / run.scenario_id
            run_dir = staging / Path(*relative.parts)
            tables = {
                "signals.csv": run.signals.decisions,
                "decisions.csv": run.execution.decisions,
                "orders.csv": run.execution.orders,
                "fills.csv": run.execution.fills,
                "account_daily.csv": run.execution.account_daily,
                "trades.csv": run.execution.trades,
            }
            if run.buyhold is None:
                raise ValueError("research evaluation has no BuyHold evidence")
            tables.update(
                {
                    "buyhold_account_daily.csv": run.buyhold.account_daily,
                    "buyhold_orders.csv": run.buyhold.orders,
                }
            )
            for name, frame in tables.items():
                target = run_dir / name
                _write_frame(target, frame)
                key = (relative / name).as_posix()
                files[key] = _file_hash(target)
            observation_path = run_dir / "observation.json"
            _write_json(observation_path, run.observation.to_dict())
            files[(relative / observation_path.name).as_posix()] = _file_hash(observation_path)
            benchmark_path = run_dir / "buyhold_metrics.json"
            _write_json(benchmark_path, run.buyhold.metrics)
            files[(relative / benchmark_path.name).as_posix()] = _file_hash(benchmark_path)
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
) -> CommandResult:
    """Execute and atomically publish one complete research evaluation request."""

    try:
        path, experiment = _request_path(context, input_path)
        request = _evaluation_request(context, path, experiment)
        result = evaluate_strategy(request)
        output, document = _publish_result(context, experiment, result)
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
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
