"""Produce immutable SRT/TXE facts for the SE-owned provisional-champion audit."""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any

import pandas as pd
from strategy_runtime import canonical_sha256
from strategy_evaluator import (
    AuditIdentity,
    CandidateDescriptor,
    CandidateProfile,
    ChampionAuditRequest,
    ParameterPoint,
    ReturnMatrixEvidence,
    StressScenarioResult,
    TrialRecord,
    hash_audit_data,
    hash_candidate_pool,
    hash_execution_evidence,
    hash_return_matrix,
)
from .evaluation import (
    _CandidateEvaluationContext,
    _execute_candidate_replay,
    _prepare_candidate_replays,
)
from czsc_trader.backtesting.audit_adapter import build_replay_evidence
from czsc_trader.backtesting.metrics import calculate_metrics


def _daily_returns(equity: pd.Series, init_cash: float) -> pd.Series:
    previous = equity.shift(1)
    previous.iloc[0] = init_cash
    return equity.div(previous).sub(1.0)


def _return_evidence(run_context, results, candidate_ids) -> ReturnMatrixEvidence:
    columns = [
        _daily_returns(results[key][1].equity, run_context.init_cash).rename(key)
        for key in candidate_ids
    ]
    if not columns or any(not item.index.equals(columns[0].index) for item in columns):
        raise ValueError("candidate return calendars differ")
    frame = pd.concat(columns, axis=1)
    if frame.empty or frame.isna().any().any():
        raise ValueError("candidate return matrix is empty or misaligned")
    evidence = ReturnMatrixEvidence(
        tuple(timestamp.date().isoformat() for timestamp in pd.DatetimeIndex(frame.index)),
        candidate_ids,
        tuple(tuple(map(float, row)) for row in frame.to_numpy()),
        "",
    )
    return replace(evidence, content_hash=hash_return_matrix(evidence))


def _coordinates(value, prefix=""):
    """Numeric SRT parameter leaves; no strategy-family parser."""
    if isinstance(value, dict):
        return tuple(
            pair
            for key in sorted(value)
            for pair in _coordinates(value[key], f"{prefix}.{key}" if prefix else str(key))
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            pair
            for index, child in enumerate(value)
            for pair in _coordinates(child, f"{prefix}[{index}]")
        )
    if type(value) in (int, float):
        if not isfinite(value):
            raise ValueError(f"nonfinite parameter: {prefix}")
        return ((prefix, float(value)),)
    return ()


def _parameter_structure(value):
    """Keep categorical choices while removing numeric coordinate values."""
    if isinstance(value, dict):
        return {key: _parameter_structure(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_parameter_structure(child) for child in value]
    if type(value) in (int, float):
        return {"numeric_coordinate": True}
    return value


def _neighborhood_identity(payload):
    return canonical_sha256(
        {
            "runtime": payload.get("runtime"),
            "structure": _parameter_structure(payload.get("parameters")),
        }
    )


def _parameter_points(
    payloads: tuple[dict[str, object], ...],
    candidate_ids: tuple[str, ...],
    profiles: tuple[CandidateProfile, ...],
    incumbent_id: str,
    champion_id: str,
) -> tuple[ParameterPoint, ...]:
    by_id = {str(item["candidate_id"]): item for item in payloads}
    profile_by_id = {item.candidate_id: item for item in profiles}
    points: list[ParameterPoint] = []
    champion_structure = _neighborhood_identity(by_id[champion_id]["strategy_payload"])
    for candidate_id in candidate_ids:
        payload = by_id[candidate_id]
        strategy_payload = payload.get("strategy_payload")
        if (
            candidate_id != incumbent_id
            and _neighborhood_identity(strategy_payload) != champion_structure
        ):
            # Other prototypes remain in the search matrix, but are not parameter neighbors.
            continue
        parameters = (
            strategy_payload.get("parameters") if isinstance(strategy_payload, dict) else None
        )
        coordinates = () if candidate_id == incumbent_id else _coordinates(parameters)
        if candidate_id != incumbent_id and not coordinates:
            raise ValueError(f"candidate {candidate_id} has no numeric SRT parameter coordinates")
        profile = profile_by_id.get(candidate_id)
        if candidate_id == incumbent_id:
            eligible, layer = True, 0
            worst_scores = tuple(
                (name, 0.0)
                for name in (
                    "net_cagr",
                    "max_drawdown",
                    "calmar",
                    "profit_factor",
                )
            )
        elif profile is None:
            eligible, layer, worst_scores = False, None, ()
        else:
            eligible, layer, worst_scores = (
                profile.eligible,
                profile.pareto_layer,
                profile.worst_scores,
            )
        points.append(
            ParameterPoint(
                candidate_id,
                str(payload.get("behavior_hash", "")),
                coordinates,
                eligible,
                layer,
                worst_scores,
                candidate_id == incumbent_id,
            )
        )
    return tuple(points)


def _build_champion_audit_request(
    *,
    run_context: _CandidateEvaluationContext,
    protocol,
    manifest: dict[str, Any],
    payloads: tuple[dict[str, object], ...],
    candidates: tuple[CandidateDescriptor, ...],
    trials: tuple[TrialRecord, ...],
    ranking,
    screening_profiles: tuple[CandidateProfile, ...],
    formal,
    repeated,
    stress,
    search_candidate_ids: tuple[str, ...],
) -> ChampionAuditRequest:
    champion_id = ranking.champion_id
    if champion_id is None:
        raise ValueError("champion audit requires a provisional champion")
    peers = tuple(
        item.candidate_id
        for item in ranking.profiles
        if item.pareto_layer == 1 and item.candidate_id != champion_id
    )
    all_required = tuple(dict.fromkeys((protocol.incumbent_id, *search_candidate_ids)))
    comparison_ids = tuple(dict.fromkeys((champion_id, protocol.incumbent_id, *peers)))
    all_required = tuple(dict.fromkeys((*all_required, *comparison_ids)))
    workspace, prepared = _prepare_candidate_replays(run_context, protocol, payloads, all_required)
    if "full" not in workspace.periods:
        raise ValueError("OPC-v3 audit requires a full period")
    results = {
        key: _execute_candidate_replay(
            run_context, workspace, prepared[key]["full"], run_context.fee_rate
        )
        for key in all_required
    }
    search_returns = _return_evidence(run_context, results, search_candidate_ids)
    comparison_returns = _return_evidence(run_context, results, comparison_ids)
    signals, ledger = results[champion_id]
    execution = build_replay_evidence(
        signals,
        workspace.execution_data,
        ledger,
        run_context.init_cash,
        calculate_metrics(ledger, run_context.init_cash),
    )
    execution = replace(execution, content_hash=hash_execution_evidence(execution))
    parameters = _parameter_points(
        payloads,
        all_required,
        screening_profiles,
        protocol.incumbent_id,
        champion_id,
    )
    stress_results = tuple(
        StressScenarioResult(
            scenario,
            protocol.execution_policy_hash,
            tuple(item for item in stress if item.scenario_id == scenario),
        )
        for scenario in dict.fromkeys(item.scenario_id for item in stress)
    )
    audit_protocol = manifest.get("audit_protocol", {})
    if not isinstance(audit_protocol, dict):
        raise ValueError("audit_protocol must be an object")
    identity = AuditIdentity(
        protocol.experiment_id,
        hash_candidate_pool(candidates),
        protocol.development_cutoff,
        hash_audit_data(search_returns, comparison_returns),
        protocol.execution_policy_hash,
        protocol.standard_version,
        str(audit_protocol.get("version", "champion-audit-v1")),
        int(audit_protocol.get("seed", 20260903)),
    )
    return ChampionAuditRequest(
        identity,
        champion_id,
        protocol.incumbent_id,
        peers,
        search_returns,
        comparison_returns,
        parameters,
        execution,
        tuple(item for item in formal if item.candidate_id in {champion_id, protocol.incumbent_id}),
        tuple(repeated),
        candidates,
        trials,
        screening_profiles,
        stress_results,
        int(audit_protocol.get("bootstrap_repetitions", 10_000)),
        tuple(int(value) for value in audit_protocol.get("mean_block_lengths", (21, 10, 42))),
    )
