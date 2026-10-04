"""Verified reuse of immutable candidate-evaluation experiment evidence."""

from __future__ import annotations

import ast
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from strategy_evaluator import MetricObservation

from .research_tools.evaluation import METRIC_SEMANTICS_VERSION
from .experiment_archive import resolve_experiment_dir, validate_experiment_archive
from .identity import canonical_json_sha256


@dataclass(frozen=True)
class EvaluationIdentity:
    candidate_id: str
    candidate_hash: str
    execution_policy_hash: str
    data_identity: str
    development_cutoff: str
    window_id: str
    window_start: str
    window_end: str
    tier: str
    scenario_id: str
    fee_rate: float
    metric_semantics_version: str = METRIC_SEMANTICS_VERSION

    @property
    def key(self) -> str:
        payload = asdict(self)
        payload.pop("candidate_id")
        return canonical_json_sha256(payload)


@dataclass(frozen=True)
class ReuseLedgerRow:
    evaluation_key: str
    candidate_id: str
    window_id: str
    scenario_id: str
    measurement_tier: str
    status: str
    source_experiment: str = ""
    source_file: str = ""
    source_hash: str = ""


@dataclass(frozen=True)
class ReuseResult:
    observations: tuple[MetricObservation, ...]
    missing_keys: tuple[str, ...]
    ledger: tuple[ReuseLedgerRow, ...]
    diagnostics: tuple[str, ...]


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _optional_float(value: str) -> float | None:
    return None if value in {"", "None", "null"} else float(value)


def _observation(row: dict[str, str], candidate_id: str) -> MetricObservation:
    objectives = ast.literal_eval(row.get("objective_values", "{}"))
    value: dict[str, Any] = {
        **row,
        "candidate_id": candidate_id,
        "calmar": _optional_float(row["calmar"]),
        "profit_factor": _optional_float(row["profit_factor"]),
        "win_loss_ratio": _optional_float(row.get("win_loss_ratio", "")),
        "win_loss_ratio_status": row.get("win_loss_ratio_status", "UNAVAILABLE"),
        "turnover": _optional_float(row.get("turnover", "")),
        "cost_drag": _optional_float(row.get("cost_drag", "")),
        "objective_values": objectives,
    }
    return MetricObservation.from_dict(value)


def _scenario_fee(base_fee: float, scenario: str) -> float:
    if scenario == "standard":
        return base_fee
    if scenario.startswith("fee_x"):
        return base_fee * float(scenario.removeprefix("fee_x"))
    raise ValueError(f"unsupported source scenario: {scenario}")


def _source_rows(experiment: Path) -> tuple[dict[str, tuple[MetricObservation, str, str]], ...]:
    archive = validate_experiment_archive(experiment)
    if archive.get("status") != "COMPLETE":
        raise ValueError("source experiment is not COMPLETE")
    protocol = _read_object(experiment / "evaluation_protocol.json")
    manifest = _read_object(experiment / str(protocol["candidate_manifest"]))
    source_files = manifest.get("source_files")
    if not isinstance(source_files, dict):
        raise ValueError("source candidate manifest has no source_files identity")
    candidates = {
        str(item["candidate_id"]): item
        for item in manifest.get("candidates", [])
        if isinstance(item, dict) and "candidate_id" in item
    }
    windows = manifest.get("windows")
    if not isinstance(windows, dict):
        raise ValueError("source candidate manifest has no windows")
    files = archive.get("files")
    if not isinstance(files, dict):
        raise ValueError("source archive has no files")
    data_identity = canonical_json_sha256(source_files)
    cutoff = str(protocol["development_cutoff"])
    base_fee = float(manifest.get("fee_rate", 0.0005))
    # Absence of a stamp cannot turn old simple-backtest metrics into TXE evidence.
    semantics = str(manifest.get("metric_semantics_version", "UNDECLARED"))
    result_path = experiment / "artifacts" / "evaluation_result.json"
    if result_path.is_file() and "artifacts/evaluation_result.json" in files:
        completed = _read_object(result_path)
        semantics = str(completed.get("formal_evaluation_contract", {}).get(
            "metric_semantics_version", semantics,
        ))
    if semantics != METRIC_SEMANTICS_VERSION:
        raise ValueError("source metrics do not declare the current SRT/TXE semantics")
    output: list[dict[str, tuple[MetricObservation, str, str]]] = []
    for relative in ("artifacts/screening_metrics.csv", "artifacts/formal_metrics.csv"):
        path = experiment / relative
        if not path.is_file() or relative not in files:
            continue
        source_hash = str(files[relative]["sha256"])
        indexed: dict[str, tuple[MetricObservation, str, str]] = {}
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                candidate_id = str(row["candidate_id"])
                candidate = candidates.get(candidate_id)
                window = windows.get(str(row["window_id"]))
                if candidate is None or not isinstance(window, dict):
                    continue
                observation = _observation(row, candidate_id)
                identity = EvaluationIdentity(
                    candidate_id=candidate_id,
                    candidate_hash=str(candidate.get("strategy_hash", candidate.get("candidate_hash", ""))),
                    execution_policy_hash=str(candidate["execution_policy_hash"]),
                    data_identity=data_identity,
                    development_cutoff=cutoff,
                    window_id=observation.window_id,
                    window_start=str(window["start"]),
                    window_end=str(window["end"]),
                    tier=observation.measurement_tier,
                    scenario_id=observation.scenario_id,
                    fee_rate=_scenario_fee(base_fee, observation.scenario_id),
                    metric_semantics_version=semantics,
                )
                indexed.setdefault(identity.key, (observation, relative, source_hash))
        output.append(indexed)
    return tuple(output)


def load_reusable_observations(
    experiments_root: Path,
    source_ids: tuple[str, ...],
    requested: tuple[EvaluationIdentity, ...],
) -> ReuseResult:
    available: dict[str, tuple[MetricObservation, str, str, str]] = {}
    diagnostics: list[str] = []
    root = Path(experiments_root).resolve()
    for source_id in source_ids:
        try:
            experiment = resolve_experiment_dir(root, source_id)
            collections = _source_rows(experiment)
        except (OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as exc:
            diagnostics.append(f"{source_id}: {exc}")
            continue
        for indexed in collections:
            for key, (observation, source_file, source_hash) in indexed.items():
                available.setdefault(key, (observation, source_id, source_file, source_hash))

    observations: list[MetricObservation] = []
    missing: list[str] = []
    ledger: list[ReuseLedgerRow] = []
    for identity in requested:
        found = available.get(identity.key)
        if found is None:
            missing.append(identity.key)
            continue
        source, source_id, source_file, source_hash = found
        observation = _observation(
            {key: str(value) if value is not None else "" for key, value in source.to_dict().items()},
            identity.candidate_id,
        )
        observations.append(observation)
        ledger.append(ReuseLedgerRow(
            identity.key,
            identity.candidate_id,
            identity.window_id,
            identity.scenario_id,
            identity.tier,
            "REUSED",
            source_id,
            source_file,
            source_hash,
        ))
    return ReuseResult(tuple(observations), tuple(missing), tuple(ledger), tuple(diagnostics))
