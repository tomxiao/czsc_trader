"""Compare all authorized S013 centers using authenticated public account facts.

Annual mandate gates are independently computed from continuous accounts. The
seven ranking metrics are checked numerically without borrowing another
candidate's perturbations, even when baseline economic behavior is identical.
"""

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import math
from multiprocessing import get_context

import numpy as np

from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.delivery import PerformanceRequirement
from strategy_evaluator import (
    AssessmentDerivationKind,
    CandidateAssessmentRequest,
    CandidateComparisonRequest,
    ComparisonPolicy,
    DiagnosticStatus,
    FamilyReturnEvidence,
    PerturbationLink,
    QuantileMethod,
    ResearchMetric,
    ResearchTargets,
    SelfCheckProtocol,
    assess_candidates,
    compare_candidates,
)

from common import PROTOCOLS, RUNS, centers, facts, read, source, write


EXPECTED_CENTERS = 79
EXPECTED_PERTURBATIONS = 8
NUMERICAL_TOLERANCE = 1e-12


def full_id(candidate_id):
    return candidate_id if candidate_id.startswith("S013-") else f"S013-{candidate_id}"


def coordinate(evidence):
    return evidence.candidate, evidence.window_id, evidence.scenario_id


def annual_stats(equity, sessions, initial_cash):
    """Use the previous year closing equity as the following year anchor."""
    assert len(equity) == len(sessions) == 1636
    assert sessions[0] == "2020-01-02" and sessions[-1] == "2026-09-30"
    assert tuple(sorted(set(sessions))) == sessions
    values = np.asarray(equity, dtype=float)
    assert np.isfinite(values).all() and (values > 0).all()
    year_labels = np.array([session[:4] for session in sessions])
    result = {}
    anchor = float(initial_cash)
    for year in sorted(set(year_labels)):
        segment = values[year_labels == year]
        wealth = np.r_[anchor, segment]
        result[str(year)] = {
            "max_drawdown_magnitude": float(
                np.max(1.0 - wealth / np.maximum.accumulate(wealth))
            ),
            "return": float(segment[-1] / anchor - 1.0),
            "sessions": len(segment),
            "opening_equity": anchor,
            "closing_equity": float(segment[-1]),
        }
        anchor = float(segment[-1])
    return result


def metrics(evidence):
    wealth = np.r_[evidence.initial_cash, [row.equity for row in evidence.account]]
    return (
        float((wealth[-1] / wealth[0]) ** (252 / len(evidence.account)) - 1.0),
        float(np.max(1.0 - wealth / np.maximum.accumulate(wealth))),
    )


def annual(evidence):
    sessions = tuple(row.session for row in evidence.account)
    assert len(evidence.benchmark_equity) == len(evidence.account)
    own = annual_stats([row.equity for row in evidence.account], sessions, evidence.initial_cash)
    benchmark = annual_stats(evidence.benchmark_equity, sessions, evidence.initial_cash)
    cagr = metrics(evidence)[0]
    benchmark_cagr = float(
        (evidence.benchmark_equity[-1] / evidence.initial_cash)
        ** (252 / len(evidence.account)) - 1.0
    )
    assert evidence.frequency_window_days == 60
    frequency = 60 * len(evidence.closed_cycles) / len(evidence.account)
    negative = [year for year in benchmark if benchmark[year]["return"] < 0]
    margins = {
        year: benchmark[year]["max_drawdown_magnitude"] - own[year]["max_drawdown_magnitude"]
        for year in benchmark
    }
    gates = {
        "return": cagr >= 1.5 * benchmark_cagr,
        "annual_drawdown": all(margin > 0 for margin in margins.values()),
        "frequency": frequency >= 4,
        "negative_buyhold_year_profit": all(own[year]["return"] > 0 for year in negative),
    }
    return {
        "candidate_id": evidence.candidate.candidate_id,
        "content_sha256": evidence.candidate.content_sha256,
        "scenario_id": evidence.scenario_id,
        "one_way_cost": evidence.scenario_context.one_way_cost,
        "net_cagr": cagr,
        "buyhold_cagr": benchmark_cagr,
        "frequency60": frequency,
        "closed_trades": len(evidence.closed_cycles),
        "annual": own,
        "buyhold_annual": benchmark,
        "negative_buyhold_years": negative,
        "annual_dd_margins": margins,
        "gates": gates,
        "qualified": all(gates.values()),
        "evaluation_id": evidence.evaluation_id,
    }


def reconcile(evidence, tolerance):
    fills = defaultdict(list)
    flows = defaultdict(float)
    quantities = defaultdict(int)
    last_session = {}
    for fill in evidence.fills:
        fills[fill.session].append(fill)
    cash, quantity = evidence.opening_cash, evidence.opening_quantity
    maximum_error = 0.0
    for point in evidence.account:
        for fill in fills[point.session]:
            direction = 1 if fill.side.value == "BUY" else -1
            flow = -direction * fill.quantity * fill.price - fill.fees
            cash += flow
            quantity += direction * fill.quantity
            flows[fill.cycle_id] += flow
            quantities[fill.cycle_id] += direction * fill.quantity
            last_session[fill.cycle_id] = point.session
        assert quantity == point.quantity, (evidence.evaluation_id, point.session)
        maximum_error = max(
            maximum_error,
            abs(cash - point.cash),
            abs(point.equity - point.cash - point.quantity * point.close),
        )
    closed = {cycle.cycle_id: cycle for cycle in evidence.closed_cycles}
    assert len(closed) == len(evidence.closed_cycles)
    for key, cycle in closed.items():
        assert key in flows and quantities[key] == 0
        assert last_session[key] == cycle.exit_session
    assert all(qty >= 0 for qty in quantities.values())
    assert all(qty > 0 or key in closed for key, qty in quantities.items())
    assert evidence.opening_quantity == 0, "S013 full accounts start without holdings"
    closed_pnl = sum(flows[key] for key in closed)
    open_pnl = sum(
        flows[key] + quantities[key] * evidence.account[-1].close
        for key in flows if key not in closed
    )
    opening_adjustment = evidence.opening_cash - evidence.initial_cash
    wealth_error = abs(
        closed_pnl + open_pnl + opening_adjustment
        - (evidence.account[-1].equity - evidence.initial_cash)
    )
    maximum_error = max(maximum_error, wealth_error)
    assert maximum_error <= tolerance, (evidence.evaluation_id, maximum_error)
    positive = sorted((flows[key] for key in closed if flows[key] > 0), reverse=True)
    concentration = (
        sum(positive[:math.ceil(0.1 * len(positive))]) / sum(positive)
        if positive else None
    )
    return {
        "candidate_id": evidence.candidate.candidate_id,
        "scenario_id": evidence.scenario_id,
        "evaluation_id": evidence.evaluation_id,
        "max_daily_reconciliation_error": maximum_error,
        "closed_pnl": closed_pnl,
        "open_pnl": open_pnl,
        "profit_concentration": concentration,
    }


def independent_checks(request, panel, source_checks, expected_centers=EXPECTED_CENTERS):
    protocol = request.protocol
    assert protocol.quantile_method is QuantileMethod.LINEAR
    index = {coordinate(evidence): evidence for evidence in request.evidence}
    assert len(index) == len(request.evidence)
    checks = []
    all_accounts = [reconcile(evidence, protocol.reconciliation_tolerance) for evidence in request.evidence]
    account_index = {row["evaluation_id"]: row for row in all_accounts}
    for row in panel.rows:
        base = index[row.candidate, protocol.baseline_window, protocol.standard_scenario]
        links = [link for link in request.perturbations if link.parent == row.candidate]
        assert len(links) == EXPECTED_PERTURBATIONS
        assert len({link.weight for link in links}) == 1
        neighbors = [index[link.child, protocol.baseline_window, protocol.standard_scenario] for link in links]
        center_cagr, center_dd = metrics(base)
        neighbor_metrics = [metrics(evidence) for evidence in neighbors]
        stress = index[row.candidate, protocol.baseline_window, protocol.stress_scenario]
        assert account_index[base.evaluation_id]["profit_concentration"] is not None
        values = {
            ResearchMetric.NET_ANNUAL_RETURN: center_cagr,
            ResearchMetric.DRAWDOWN_MAGNITUDE: center_dd,
            ResearchMetric.PARAMETER_RETURN_DEGRADATION: max(
                0.0, center_cagr - float(np.quantile([item[0] for item in neighbor_metrics], 0.1, method="linear"))
            ),
            ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION: max(
                0.0, float(np.quantile([item[1] for item in neighbor_metrics], 0.9, method="linear")) - center_dd
            ),
            ResearchMetric.STRESS_ANNUAL_LOSS: center_cagr - metrics(stress)[0],
            ResearchMetric.PROFIT_CONCENTRATION: account_index[base.evaluation_id]["profit_concentration"],
        }
        own = np.r_[base.initial_cash, [point.equity for point in base.account]]
        benchmark = np.r_[base.initial_cash, base.benchmark_equity]
        size, step = protocol.rolling_window_days, protocol.rolling_step_days
        excess = np.array([
            own[start + size] / own[start] - benchmark[start + size] / benchmark[start]
            for start in range(0, len(own) - size, step)
        ])
        assert len(excess) >= protocol.minimum_rolling_windows
        values[ResearchMetric.ROLLING_EXCESS_Q10] = float(np.quantile(excess, 0.1, method="linear"))
        diagnostics = {diagnostic.metric: diagnostic for diagnostic in row.diagnostics}
        errors = {}
        for metric, expected in values.items():
            diagnostic = diagnostics[metric]
            assert diagnostic.status is DiagnosticStatus.AVAILABLE, diagnostic.to_dict()
            error = abs(diagnostic.value - expected)
            assert error < NUMERICAL_TOLERANCE, (row.candidate, metric, expected, diagnostic.to_dict())
            errors[metric.value] = error
        assert not row.coverage_gaps, (row.candidate, row.coverage_gaps)
        gate_result = annual(base)
        assert gate_result["qualified"], gate_result
        checks.append({
            "candidate_id": row.candidate.candidate_id,
            "content_sha256": row.candidate.content_sha256,
            "seven_metrics": "PASS",
            "metric_absolute_errors": errors,
            "annual_four_gates": gate_result["gates"],
            "rolling_windows": len(excess),
            "parameter_accounts": len(neighbors),
            "max_daily_reconciliation_error": account_index[base.evaluation_id]["max_daily_reconciliation_error"],
        })
    assert len(checks) == expected_centers
    return {
        "status": "PASS",
        "checks": checks,
        "all_account_reconciliation": all_accounts,
        "parameter_source_identity_checks": source_checks,
        "all_center_standard_gates": "PASS",
        "authenticated_published_evidence": len(request.evidence),
        "source_accounts": len(request.centers),
        "parameter_accounts": len(request.perturbations),
        "stress_accounts": sum(
            evidence.candidate in request.centers and evidence.scenario_id != protocol.standard_scenario
            for evidence in request.evidence
        ),
        "numerical_metric_tolerance": NUMERICAL_TOLERANCE,
        "bootstrap": "Public SE paired stationary-block resampling, CAGR excess interval; descriptive developer-pool diagnostic only.",
        "source_boundary": "Every published parameter case keeps its own center source hash. Baseline behavior grouping does not substitute perturbation evidence.",
    }


def main():
    plan = read(PROTOCOLS / "plan.json")
    protocol = SelfCheckProtocol.from_dict(plan["protocol"])
    entries = tuple(centers())
    assert len(entries) == EXPECTED_CENTERS
    payload = read(RUNS / "rows.json")
    rows = payload["rows"]
    assert all(row["status"] == "SUCCEEDED" for row in rows), rows
    references = (
        tuple(entry.evaluations[0].evidence for entry in entries)
        + tuple(EvidenceRef.from_dict(row["reference"]) for row in rows)
    )
    assert all(ref.experiment.strategy_id == "S013" for ref in references)
    # This pool starts only after all account evaluations have completed. Facts
    # remain authenticated by the public validator in common.facts; map preserves
    # reference order, so no center or perturbation can borrow another result.
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context("spawn")) as pool:
        authenticated = tuple(pool.map(facts, references))
    baseline_facts = authenticated[:len(entries)]
    execution_facts = authenticated[len(entries):]
    baseline = []
    for entry, actual in zip(entries, baseline_facts, strict=True):
        identity = entry.identity
        expected_id = full_id(identity.key.candidate_id)
        candidates = [
            evidence for evidence in actual
            if evidence.candidate.candidate_id == expected_id
            and evidence.candidate.content_sha256 == identity.content_sha256
            and evidence.window_id == protocol.baseline_window
            and evidence.scenario_id == protocol.standard_scenario
        ]
        assert len(candidates) == 1, expected_id
        baseline.append(candidates[0])
    central = tuple(evidence.candidate for evidence in baseline)
    assert len(set(central)) == EXPECTED_CENTERS
    assert all(evidence.scenario_context.one_way_cost == 0.001 for evidence in baseline)

    parameter_cases = {
        full_id(case["candidate_id"]): case for case in plan["cases"] if case["kind"] == "PARAMETERS"
    }
    evidence = list(baseline)
    links = []
    source_checks = []
    for row, actual in zip(rows, execution_facts, strict=True):
        assert row["status"] == "SUCCEEDED", row
        assert actual and all(item.window_id == protocol.baseline_window for item in actual)
        if row["kind"] == "PARAMETERS":
            assert len(actual) == 1
            item = actual[0]
            case = parameter_cases[item.candidate.candidate_id]
            assert item.scenario_id == protocol.standard_scenario
            assert item.parent in central
            assert item.derivation_kind is AssessmentDerivationKind.PARAMETERS
            assert item.derivation_sha256 is not None
            assert item.parent.candidate_id == full_id(case["parent"]["key"]["candidate_id"])
            assert item.parent.content_sha256 == case["parent"]["content_sha256"]
            assert case["parent_source_sha256"] == case["child_source_sha256"]
            if "child_content_sha256" in case:
                assert item.candidate.content_sha256 == case["child_content_sha256"]
            links.append(PerturbationLink(item.parent, item.candidate, 1.0, item.derivation_sha256))
            source_checks.append({
                "parent": item.parent.to_dict(),
                "child": item.candidate.to_dict(),
                "parent_source_sha256": case["parent_source_sha256"],
                "child_source_sha256": case["child_source_sha256"],
                "derivation_sha256": item.derivation_sha256,
                "status": "PASS",
            })
        else:
            assert row["kind"] == "STRESS", row
            assert all(item.candidate in central for item in actual)
            assert all(item.scenario_id != protocol.standard_scenario for item in actual)
            assert all(item.scenario_context.measurement_tier == "STRESS" for item in actual)
        evidence.extend(actual)
    assert len(links) == EXPECTED_CENTERS * EXPECTED_PERTURBATIONS
    assert {link.child.candidate_id for link in links} == set(parameter_cases)
    assert len({coordinate(item) for item in evidence}) == len(evidence)

    sessions = tuple(point.session for point in baseline[0].account)
    assert all(tuple(point.session for point in item.account) == sessions for item in baseline)
    matrix = np.array([[point.equity for point in item.account] for item in baseline]).T
    previous = np.vstack([np.array([item.initial_cash for item in baseline]), matrix[:-1]])
    returns = matrix / previous - 1.0
    selected_id = full_id(plan["family_selected"])
    selected = next(candidate for candidate in central if candidate.candidate_id == selected_id)
    family = FamilyReturnEvidence(
        central,
        sessions,
        tuple(tuple(float(value) for value in row) for row in returns),
        selected,
        plan["family_raw_trial_count"],
        tuple(plan["limitations"]),
    )
    request = CandidateAssessmentRequest(
        central, protocol, tuple(links), tuple(evidence), family_returns=family
    )
    panel = assess_candidates(request)
    mandate = source("MANDATE", 5).payload
    targets = tuple(
        target for item in mandate.items if isinstance(item.requirement, PerformanceRequirement)
        for target in item.requirement.targets
    )
    compare_request = CandidateComparisonRequest(
        central, ResearchTargets(targets, 60), panel,
        ComparisonPolicy.from_dict(plan["comparison_policy"]),
    )
    comparison = compare_candidates(compare_request)
    verification = independent_checks(request, panel, source_checks)

    all_four = {}
    neighborhoods = {}
    for center in central:
        actual_links = [link for link in links if link.parent == center]
        child_set = {link.child for link in actual_links}
        records = [annual(item) for item in evidence if item.candidate in child_set]
        assert len(records) == EXPECTED_PERTURBATIONS
        neighborhoods[center.candidate_id] = {
            "count": len(records),
            "qualified": sum(record["qualified"] for record in records),
            "gate_pass_counts": {
                gate: sum(record["gates"][gate] for record in records)
                for gate in records[0]["gates"]
            },
            "records": records,
        }
        slots = {
            item.scenario_id: annual(item) for item in evidence if item.candidate == center
        }
        assert slots[protocol.standard_scenario]["qualified"], slots
        all_four[center.candidate_id] = slots
    write(RUNS / "assessment_request.json", request.to_dict())
    write(RUNS / "assessment.json", panel.to_dict())
    write(RUNS / "comparison_request.json", compare_request.to_dict())
    write(RUNS / "comparison.json", comparison.to_dict())
    write(RUNS / "annual_four_gates.json", {
        "standard_and_stress": all_four,
        "standard_four_gate_qualified": len(all_four),
        "interpretation": "Original standard four gates determine qualification; stress and perturbation gate outcomes remain diagnostics only.",
    })
    write(RUNS / "neighborhood_four_gates.json", neighborhoods)
    write(RUNS / "independent_verification.json", verification)
    write(RUNS / "sensitivity.json", {
        "variants": [
            {"name": variant.name, "ranking": [row.to_dict() for row in variant.rows]}
            for variant in comparison.sensitivities
        ],
        "behavior_groups": [group.to_dict() for group in comparison.behavior_groups],
    })
    print({
        "centers": len(panel.rows),
        "metrics": "COMPLETE",
        "annual_gates": "PASS",
        "parameter_accounts": len(links),
        "ranking": [
            {"candidate": row.candidate.candidate_id, "layer": row.pareto_layer,
             "rank": row.rank_in_layer, "status": row.status.value}
            for row in comparison.rows
        ],
        "family_diagnostics": [item.to_dict() for item in panel.family_diagnostics],
    }, flush=True)


if __name__ == "__main__":
    main()
