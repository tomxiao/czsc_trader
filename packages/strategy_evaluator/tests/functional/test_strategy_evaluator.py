from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from strategy_evaluator import (
    AuditIdentity,
    AuditStatus,
    CandidateDescriptor,
    CandidateProfile,
    ChampionAuditRequest,
    EvaluationProtocol,
    ExecutionEvidence,
    ExecutionOrder,
    FactorEvent,
    MetricObservation,
    MetricStatus,
    ParameterPoint,
    RankingResult,
    ReturnMatrixEvidence,
    RiskLabel,
    StressScenarioResult,
    TrialRecord,
    ValidationError,
    audit_provisional_champion,
    hash_audit_data,
    hash_candidate_pool,
    hash_execution_evidence,
    hash_return_matrix,
    rank_candidates,
    required_stress_scenarios,
    screen_candidates,
    stationary_bootstrap_performance,
    validate_protocol,
)


PROTOCOL = {
    "schema_version": 1,
    "standard_version": "opc-v3",
    "experiment_id": "0904_TEST",
    "research_objective": "改善震荡区间表现",
    "development_cutoff": "2026-09-02",
    "incumbent_id": "S001-v1",
    "incumbent_hash": "a" * 64,
    "decision_windows": ["full", "2026_ytd"],
    "target_windows": ["full"],
    "execution_policy_hash": "b" * 64,
    "tightened_margins": {"net_cagr_retention": 0.95},
    "shortlist_limit": 12,
    "target_requirements": [
        {
            "metric": "range_return",
            "direction": "maximize",
            "minimum_improvement": 0.01,
        }
    ],
    "candidate_manifest": "candidate_manifest.json",
}


@pytest.mark.parametrize("standard", ["opc-v1", "opc-v2", "opc-v4"])
def test_retired_or_unknown_standard_is_rejected(standard):
    from strategy_evaluator import resolve_margins

    protocol = EvaluationProtocol.from_dict({**PROTOCOL, "standard_version": standard})
    with pytest.raises(ValidationError, match="unsupported standard"):
        resolve_margins(protocol)


def test_legacy_pressure_labels_cannot_satisfy_current_stress_contract():
    from strategy_evaluator import audit_stress_results

    results = tuple(StressScenarioResult(name, "a" * 64, ()) for name in (
        "fee_x2", "slippage_15bp", "slippage_30bp", "slippage_50bp",
    ))
    assert audit_stress_results("champion", "incumbent", "a" * 64, (), results).status is AuditStatus.INSUFFICIENT


def _observation(candidate_id: str, window: str, **changes) -> MetricObservation:
    base = MetricObservation(
        candidate_id,
        window,
        "standard",
        "FORMAL",
        0.10,
        0.5,
        -0.10,
        1.0,
        MetricStatus.VALID,
        2.0,
        MetricStatus.VALID,
        20,
        2.0,
        0.01,
        (("range_return", -0.10),),
    )
    return replace(base, **changes)


def _ranking() -> RankingResult:
    profile = CandidateProfile(
        "R1102",
        True,
        True,
        (
            ("net_cagr", 1.0),
            ("max_drawdown", 1.0),
            ("calmar", 1.0),
            ("profit_factor", 1.0),
        ),
        1,
        1.0,
    )
    return RankingResult("S001-v1", (profile,), "R1102", ("R1102",))


def _complete_audit_request(
    *, champion_edge: float = 0.0002, execution_invalid: bool = False
) -> ChampionAuditRequest:
    dates = tuple(f"2025-{month:02d}-{day:02d}" for month in range(1, 6) for day in range(1, 7))
    base = np.tile([0.001, -0.0008, 0.0004], 10)
    search_ids = tuple(["R1102", "R0539", *[f"R{index:04d}" for index in range(10)]])
    search_values = np.column_stack(
        [
            base + champion_edge,
            base + 0.0001,
            *[base + index * 0.00001 for index in range(10)],
        ]
    )
    search = ReturnMatrixEvidence(
        dates,
        search_ids,
        tuple(tuple(map(float, row)) for row in search_values),
        "",
    )
    search = replace(search, content_hash=hash_return_matrix(search))
    comparison_values = np.column_stack([base + champion_edge, base, base + 0.0001])
    comparison = ReturnMatrixEvidence(
        dates,
        ("R1102", "S001-v1", "R0539"),
        tuple(tuple(map(float, row)) for row in comparison_values),
        "",
    )
    comparison = replace(comparison, content_hash=hash_return_matrix(comparison))
    candidates = tuple(
        CandidateDescriptor(
            candidate_id,
            f"{index + 1:064x}",
            "c" * 64,
            candidate_id == "S001-v1",
            f"behavior-{candidate_id}",
        )
        for index, candidate_id in enumerate(("S001-v1", *search_ids))
    )
    profiles = tuple(
        CandidateProfile(
            candidate_id,
            True,
            True,
            (
                ("net_cagr", 0.5),
                ("max_drawdown", 0.5),
                ("calmar", 0.5),
                ("profit_factor", 0.5),
            ),
            1,
        )
        for candidate_id in search_ids
    )
    parameters = tuple(
        ParameterPoint(
            candidate_id,
            f"behavior-{candidate_id}",
            (("fast", 0.5 + index / 100), ("slow", 0.5 - index / 100)),
            True,
            1,
            (
                ("net_cagr", 0.5),
                ("max_drawdown", 0.5),
                ("calmar", 0.5),
                ("profit_factor", 0.5),
            ),
            candidate_id == "S001-v1",
        )
        for index, candidate_id in enumerate(("R1102", "S001-v1", *search_ids[1:]))
    )
    trials = tuple(
        TrialRecord(
            f"t{index}",
            item.candidate_id,
            item.candidate_hash,
            item.behavior_hash,
            "COMPLETED",
        )
        for index, item in enumerate(candidates)
    )
    execution = ExecutionEvidence(
        dates,
        tuple([0.0, 1.0, *([1.0] * 28)]),
        tuple([0.0, 0.2, *([0.1] * 28)]),
        (FactorEvent("entry", dates[1], "Entry", 0.0, 1.0, 0.2),),
        (
            ExecutionOrder(
                dates[1],
                "2025-01-04" if execution_invalid else "2025-01-03",
                "Buy",
                10.0,
                10.0,
                0.05,
                "entry",
            ),
        ),
        "",
    )
    execution = replace(execution, content_hash=hash_execution_evidence(execution))

    def observation(candidate_id: str, scenario: str = "standard"):
        edge = champion_edge if candidate_id == "R1102" else 0.0
        return MetricObservation(
            candidate_id,
            "full",
            scenario,
            "FORMAL" if scenario == "standard" else "STRESS",
            0.1 + edge * 100,
            0.5,
            -0.2 + edge * 10,
            0.5 + edge * 50,
            MetricStatus.VALID,
            2.0 + edge * 100,
            MetricStatus.VALID,
            20,
        )

    formal = (observation("S001-v1"), observation("R1102"))
    stress = tuple(
        StressScenarioResult(
            scenario.scenario_id,
            "c" * 64,
            (
                observation("S001-v1", scenario.scenario_id),
                observation("R1102", scenario.scenario_id),
            ),
        )
        for scenario in required_stress_scenarios()
    )
    identity = AuditIdentity(
        "0904_TEST",
        hash_candidate_pool(candidates),
        "2026-09-02",
        hash_audit_data(search, comparison),
        "c" * 64,
        "opc-v3",
        "champion-audit-v1",
        20260904,
    )
    return ChampionAuditRequest(
        identity,
        "R1102",
        "S001-v1",
        ("R0539",),
        search,
        comparison,
        parameters,
        execution,
        formal,
        (formal[1],),
        candidates,
        trials,
        profiles,
        stress,
        100,
        (21, 10, 42),
    )


def test_ft_se01_candidate_funnel_selects_the_robust_pareto_champion() -> None:
    protocol = EvaluationProtocol.from_dict(PROTOCOL)
    candidates = (
        CandidateDescriptor("S001-v1", "a" * 64, "b" * 64, True, "incumbent"),
        CandidateDescriptor("winner", "c" * 64, "b" * 64, False, "winner"),
        CandidateDescriptor("z-duplicate", "d" * 64, "b" * 64, False, "winner"),
        CandidateDescriptor("inferior", "e" * 64, "b" * 64, False, "inferior"),
    )
    observations = []
    for candidate_id in ("S001-v1", "winner", "z-duplicate", "inferior"):
        for window in ("full", "2026_ytd"):
            changes = {}
            if candidate_id == "winner":
                changes = {
                    "net_cagr": 0.12,
                    "max_drawdown": -0.09,
                    "calmar": 1.3,
                    "profit_factor": 2.2,
                    "objective_values": (("range_return", -0.05),),
                }
            elif candidate_id == "z-duplicate":
                changes = {
                    "net_cagr": 0.12,
                    "max_drawdown": -0.09,
                    "calmar": 1.3,
                    "profit_factor": 2.2,
                    "objective_values": (("range_return", -0.05),),
                }
            elif candidate_id == "inferior":
                changes = {"net_cagr": -0.20, "calmar": -0.5}
            observations.append(_observation(candidate_id, window, **changes))
    observations_tuple = tuple(observations)
    trials = tuple(
        TrialRecord(
            f"trial-{candidate.candidate_id}",
            candidate.candidate_id,
            candidate.candidate_hash,
            candidate.behavior_hash,
            "COMPLETED",
        )
        for candidate in candidates
    )
    validate_protocol(protocol, candidates, observations_tuple, trials)
    shortlist = screen_candidates(protocol, candidates, observations_tuple)
    ranking = rank_candidates(protocol, shortlist, observations_tuple, candidates)

    assert shortlist.candidate_ids == ("winner",)
    assert set(shortlist.rejected_ids) == {"z-duplicate", "inferior"}
    assert ranking.champion_id == "winner"
    assert ranking.tied_champion_ids == ("winner",)
    assert ranking.profiles[0].pareto_layer == 1


def test_ft_se02_champion_audit_combines_statistical_and_engineering_evidence() -> None:
    request = _complete_audit_request()
    audit = audit_provisional_champion(request)

    assert audit.status is AuditStatus.PASS
    assert audit.risk_label in {
        RiskLabel.FAVORABLE,
        RiskLabel.MIXED,
        RiskLabel.WEAK,
    }
    assert audit.search_bias is not None
    assert audit.search_bias.pbo is not None
    assert audit.dsr is not None
    assert len(audit.bootstrap) == 6
    assert audit.neighborhood is not None
    finding_statuses = {finding.audit_id: finding.status for finding in audit.findings}
    assert (
        finding_statuses.items()
        >= {
            "execution": AuditStatus.PASS,
            "reproducibility": AuditStatus.PASS,
            "trial_ledger": AuditStatus.PASS,
            "stress": AuditStatus.PASS,
        }.items()
    )
    assert audit.stress.status is AuditStatus.PASS

    absolute = stationary_bootstrap_performance(
        np.asarray(request.search_returns.returns, dtype=float)[:, 0],
        candidate_id=request.champion_id,
        repetitions=100,
        mean_block_length=10,
        seed=20260910,
    )
    assert absolute.candidate_id == request.champion_id
    assert absolute.repetitions == 100
    assert absolute.cagr.lower_90 <= absolute.cagr.upper_90
    assert absolute.max_drawdown.lower_95 <= absolute.max_drawdown.upper_95
    assert 0.0 <= absolute.calmar.probability_above_zero <= 1.0

    invalid = audit_provisional_champion(_complete_audit_request(execution_invalid=True))
    assert invalid.status is AuditStatus.FAIL


def test_ft_se03_governance_validation_and_report_are_complete() -> None:
    protocol = EvaluationProtocol.from_dict(PROTOCOL)
    observation = _observation("S001-v1", "full")
    assert EvaluationProtocol.from_dict(protocol.to_dict()) == protocol
    assert MetricObservation.from_dict(observation.to_dict()) == observation
    with pytest.raises(FrozenInstanceError):
        protocol.experiment_id = "changed"
    with pytest.raises(ValidationError, match="unknown fields"):
        EvaluationProtocol.from_dict({**PROTOCOL, "unexpected": True})

    candidates = (
        CandidateDescriptor("S001-v1", "a" * 64, "b" * 64, True, "h1"),
        CandidateDescriptor("candidate", "c" * 64, "b" * 64, False, "h2"),
    )
    observations = tuple(
        _observation(candidate_id, window)
        for candidate_id in ("S001-v1", "candidate")
        for window in ("full", "2026_ytd")
    )
    trials = (
        TrialRecord("t0", "S001-v1", "a" * 64, "h1", "COMPLETED"),
        TrialRecord("t1", "candidate", "c" * 64, "h2", "COMPLETED"),
    )
    validate_protocol(protocol, candidates, observations, trials)
    loosened = deepcopy(PROTOCOL)
    loosened["tightened_margins"] = {"net_cagr_retention": 0.80}
    with pytest.raises(ValidationError, match="cannot loosen"):
        validate_protocol(EvaluationProtocol.from_dict(loosened), candidates, observations, trials)
    with pytest.raises(ValidationError, match="exactly one incumbent"):
        validate_protocol(
            protocol,
            tuple(replace(item, is_incumbent=False) for item in candidates),
            observations,
            trials,
        )
    with pytest.raises(ValidationError, match="duplicate observation"):
        validate_protocol(protocol, candidates, observations + (observations[0],), trials)

    audit = audit_provisional_champion(_complete_audit_request(champion_edge=-0.0002))
    assert audit.status is AuditStatus.PASS
    assert audit.risk_label in {RiskLabel.FAVORABLE, RiskLabel.MIXED, RiskLabel.WEAK}
