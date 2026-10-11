"""EX062 public five-item selfcheck plus independent economics; no scheduling/I/O."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import numpy as np
from strategy_evaluator import (
    AssessmentEvidence, AssessmentPanel, CandidateAssessmentRequest, FillSide,
    FamilyReturnEvidence, IncompleteEvaluation, IncompleteEvaluationStatus,
    ParameterPerturbationDesign, PerturbationLink, QuantileMethod, ResearchMetric,
    SelfCheckProtocol, assess_candidates,
)
from czsc_trader.research_tools import build_assessment_evidence
from czsc_trader.research_tools.evaluation import EvaluationRequest, EvaluationResult

STANDARD_SCENARIO = 'baseline'
STRESS_SCENARIO = 'stress_20bp_per_side'
STANDARD_COST = 0.001
STRESS_COST = 0.002
TOLERANCE = 1e-6


@dataclass(frozen=True)
class NativeEvaluation:
    request: EvaluationRequest
    result: EvaluationResult


@dataclass(frozen=True)
class SelfcheckResult:
    request: CandidateAssessmentRequest
    panel: AssessmentPanel
    economics: dict
    limitations: tuple[str, ...]


def protocol(design: ParameterPerturbationDesign) -> SelfCheckProtocol:
    """Keep approved independent-factor scope; never change declared geometry."""
    if design.protocol.point_count != 32 or design.protocol.radius != 0.05 or design.protocol.seed != 13:
        raise ValueError('EX062 requires original declared 32 points, total normalized radius .05, seed13')
    return SelfCheckProtocol(
        version='S013-EX062-five-independent-checks-v1', baseline_window='full',
        standard_scenario=STANDARD_SCENARIO, stress_scenario=STRESS_SCENARIO,
        rolling_window_days=126, rolling_step_days=21, quantile_method=QuantileMethod.LINEAR,
        minimum_perturbations=32, minimum_rolling_windows=20,
        bootstrap_repetitions=2000, bootstrap_block_length=20, seed=13,
        reconciliation_tolerance=TOLERANCE, pbo_blocks=10,
        parameter_protocol=design.protocol,
    )


def economics(evidence: AssessmentEvidence) -> dict:
    """Reconcile actual fills, mark-to-market and year boundaries independently."""
    if evidence.opening_quantity != 0 or evidence.opening_cash != evidence.initial_cash:
        raise ValueError('S013 full-account audit requires cash-only initial state')
    grouped = defaultdict(list)
    for fill in evidence.fills:
        grouped[fill.session].append(fill)
    cash, quantity = evidence.opening_cash, evidence.opening_quantity
    cycle_quantity, cycle_cash, cycle_last = defaultdict(int), defaultdict(float), {}
    equity, sessions, max_cash_error, max_mark_error = [], [], 0.0, 0.0
    for row in evidence.account:
        for fill in grouped[row.session]:
            expected_fee = fill.quantity * fill.price * evidence.scenario_context.one_way_cost
            if abs(expected_fee - fill.fees) > TOLERANCE:
                raise ValueError('actual fill fee differs from declared one-way cost')
            sign = 1 if fill.side is FillSide.BUY else -1
            flow = -sign * fill.quantity * fill.price - fill.fees
            cash += flow
            quantity += sign * fill.quantity
            if quantity < 0:
                raise ValueError('sell exceeds owned shares')
            cycle_quantity[fill.cycle_id] += sign * fill.quantity
            cycle_cash[fill.cycle_id] += flow
            cycle_last[fill.cycle_id] = fill.session
        max_cash_error = max(max_cash_error, abs(cash - row.cash))
        max_mark_error = max(max_mark_error, abs(cash + quantity * row.close - row.equity))
        if quantity != row.quantity or max_cash_error > TOLERANCE or max_mark_error > TOLERANCE:
            raise ValueError('account cash/quantity/equity reconciliation failed')
        equity.append(row.equity)
        sessions.append(row.session)
    closed = {c.cycle_id: c for c in evidence.closed_cycles}
    derived_closed = {key for key, q in cycle_quantity.items() if q == 0}
    if set(closed) != derived_closed or any(cycle_quantity[key] < 0 for key in cycle_quantity):
        raise ValueError('actual closed cycles differ from zero terminal cycle positions')
    if any(cycle_last[key] != cycle.exit_session for key, cycle in closed.items()):
        raise ValueError('closed-cycle exit date differs from actual last fill')
    terminal = equity[-1]
    total_pnl = sum(cycle_cash.values()) + sum(cycle_quantity.values()) * evidence.account[-1].close
    if abs(total_pnl - (terminal - evidence.initial_cash)) > TOLERANCE:
        raise ValueError('all closed/open cycles do not reconcile terminal profit')
    wealth = np.r_[evidence.initial_cash, equity]
    full_dd = float(np.max(1 - wealth / np.maximum.accumulate(wealth)))
    cagr = float((terminal / evidence.initial_cash) ** (252 / len(equity)) - 1)
    annual = {}
    start_equity = evidence.initial_cash
    for year in sorted({day[:4] for day in sessions}):
        indices = [i for i, day in enumerate(sessions) if day.startswith(year)]
        path = np.r_[start_equity, np.asarray(equity)[indices]]
        annual[year] = {'opening_equity': float(start_equity), 'closing_equity': float(path[-1]),
                        'return': float(path[-1] / start_equity - 1),
                        'drawdown': float(np.max(1 - path / np.maximum.accumulate(path))),
                        'sessions': len(indices),
                        'closed_cycles': sum(c.exit_session.startswith(year) for c in closed.values())}
        start_equity = path[-1]
    winners = sorted([cycle_cash[key] for key in closed if cycle_cash[key] > 0], reverse=True)
    concentration = sum(winners[:math.ceil(.1 * len(winners))]) / sum(winners) if winners else None
    benchmark = np.r_[evidence.initial_cash, evidence.benchmark_equity]
    benchmark_annual = {}
    if evidence.benchmark_equity:
        start = evidence.initial_cash
        for year in annual:
            indices = [i for i, day in enumerate(sessions) if day.startswith(year)]
            path = np.r_[start, benchmark[1:][indices]]
            benchmark_annual[year] = {'return': float(path[-1] / start - 1),
                                      'drawdown': float(np.max(1 - path / np.maximum.accumulate(path)))}
            start = path[-1]
    benchmark_cagr = float((benchmark[-1] / evidence.initial_cash) ** (252 / len(equity)) - 1) if evidence.benchmark_equity else None
    gates = None if benchmark_cagr is None else {
        'return': cagr >= 1.5 * benchmark_cagr if benchmark_cagr > 0 else cagr > 0,
        'annual_drawdown': all(annual[y]['drawdown'] < benchmark_annual[y]['drawdown'] for y in annual),
        'frequency': 60 * len(closed) / len(equity) >= 4,
        'negative_buyhold_year_profit': all(annual[y]['return'] > 0 for y in annual if benchmark_annual[y]['return'] < 0),
    }
    return {'status': 'PASS', 'candidate': evidence.candidate.to_dict(), 'scenario': evidence.scenario_id,
            'net_cagr': cagr, 'full_drawdown': full_dd, 'closed_trades': len(closed),
            'frequency60': 60 * len(closed) / len(equity), 'annual': annual,
            'benchmark_annual': benchmark_annual,
            'benchmark_cagr': benchmark_cagr,
            'benchmark_full_drawdown': float(np.max(1 - benchmark / np.maximum.accumulate(benchmark))) if evidence.benchmark_equity else None,
            'drawdown': full_dd, 'gates': gates, 'qualified': None if gates is None else all(gates.values()),
            'profit_concentration': concentration,
            'max_cash_error': max_cash_error, 'max_mark_error': max_mark_error,
            'annual_boundary': 'continuous prior year final equity; first year includes initial cash',
            'actual_closed_cycle_ids': sorted(closed)}


def assess_facts(*, center: AssessmentEvidence, points: tuple[AssessmentEvidence, ...],
                 design: ParameterPerturbationDesign, stress: AssessmentEvidence | None = None,
                 family: FamilyReturnEvidence | None = None,
                 family_evidence: tuple[AssessmentEvidence, ...] = ()) -> SelfcheckResult:
    """Pure public SE assessment; native caller authenticates before this layer."""
    if center.candidate != design.center or not center.candidate.candidate_id.startswith('S013-'):
        raise ValueError('center identity must be the S013 declared design center')
    if center.window_id != 'full' or center.scenario_id != STANDARD_SCENARIO:
        raise ValueError('center must use full baseline account')
    if center.scenario_context.one_way_cost != STANDARD_COST:
        raise ValueError('baseline one-way cost must be .001')
    if len(points) != 32:
        raise ValueError('retain all32 prescribed points; no subset or replacement')
    seen = set()
    links = []
    point_economics = []
    for point in points:
        binding = point.parameter_point
        if binding is None or binding.point_index in seen or binding != design.bind_point(binding.point_index):
            raise ValueError('parameter evidence missing/duplicated/mismatched design binding')
        seen.add(binding.point_index)
        if point.parent != center.candidate or point.scenario_id != STANDARD_SCENARIO or point.window_id != 'full':
            raise ValueError('parameter point must keep parent/full/standard cost')
        if point.scenario_context != center.scenario_context or point.context_sha256 != center.context_sha256:
            raise ValueError('parameter point changed economic context')
        links.append(PerturbationLink(center.candidate, point.candidate, 1.0, point.derivation_sha256, binding))
        point_economics.append(economics(point))
    if seen != set(range(32)):
        raise ValueError('all point indices0..31 required')
    incomplete = ()
    stress_economics = None
    if stress is None:
        incomplete = (IncompleteEvaluation(center.candidate, 'full', STRESS_SCENARIO,
                       IncompleteEvaluationStatus.NOT_RUN, 'Separate 2x fee account not provided; helper never schedules evaluation'),)
    else:
        if stress.candidate != center.candidate or stress.window_id != 'full' or stress.scenario_id != STRESS_SCENARIO:
            raise ValueError('fee pressure must use unchanged center/full identity')
        if stress.scenario_context.one_way_cost != STRESS_COST or stress.scenario_context.measurement_tier != 'STRESS':
            raise ValueError('fee pressure must be explicit .002 STRESS contract')
        stress_economics = economics(stress)
    all_evidence = (center, *points, *((stress,) if stress is not None else ()), *family_evidence)
    request = CandidateAssessmentRequest(centers=(center.candidate,), protocol=protocol(design),
        perturbations=tuple(links), evidence=all_evidence, incomplete=incomplete,
        family_returns=family, parameter_designs=(design,))
    panel = assess_candidates(request)
    center_economics = economics(center)
    row = panel.rows[0]
    metric = {item.metric: item for item in row.diagnostics}
    q10 = float(np.quantile([item['net_cagr'] for item in point_economics], .1, method='linear'))
    q90 = float(np.quantile([item['full_drawdown'] for item in point_economics], .9, method='linear'))
    expected = {ResearchMetric.NET_ANNUAL_RETURN: center_economics['net_cagr'],
                ResearchMetric.DRAWDOWN_MAGNITUDE: center_economics['full_drawdown'],
                ResearchMetric.FULL_SAMPLE_FREQUENCY: center_economics['frequency60'],
                ResearchMetric.PARAMETER_RETURN_DEGRADATION: max(0, center_economics['net_cagr'] - q10),
                ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION: max(0, q90 - center_economics['full_drawdown'])}
    if stress_economics is not None:
        expected[ResearchMetric.STRESS_ANNUAL_LOSS] = center_economics['net_cagr'] - stress_economics['net_cagr']
    if center_economics['profit_concentration'] is not None:
        expected[ResearchMetric.PROFIT_CONCENTRATION] = center_economics['profit_concentration']
    for name, value in expected.items():
        if metric[name].value is None or not math.isclose(metric[name].value, value, rel_tol=0, abs_tol=1e-12):
            raise ValueError('independent economics differs from public SE: ' + name.value)
    return SelfcheckResult(request, panel,
        {'center': center_economics, 'points': point_economics, 'stress': stress_economics,
         'absolute_q10_cagr': q10, 'absolute_q90_drawdown': q90,
         'new_accounts_scheduled_by_helper': 0},
        ('Repeated S013 development-pool mechanism/parameter selection is not fully corrected.',
         'No supplied full-family matrix means official PBO/DSR are unavailable, never zero; supplied subset diagnostics cannot correct all historical choices.',
         'Return interval describes this paired bootstrap, not future returns or probability of strategy success.',
         'All original-four-goal-qualified stage3 centers retain eligibility; five-item diagnostics add no economic veto.',
         'Helper has no account scheduler, publication, market-data fetch, parameter/time/cost cross-combination or fallback.'))


def _fact(native: NativeEvaluation, scenario: str) -> AssessmentEvidence:
    if type(native) is not NativeEvaluation:
        raise TypeError('native must be NativeEvaluation with authentic evaluated request/result')
    selected = [item for item in build_assessment_evidence(native.request, native.result)
                if item.window_id == 'full' and item.scenario_id == scenario]
    if len(selected) != 1:
        raise ValueError('exactly one authenticated full scenario required: ' + scenario)
    return selected[0]


def economic_native(request: EvaluationRequest, result: EvaluationResult) -> dict:
    """Authenticate unchanged full baseline native pair, then retain EX058 four gates."""
    fact = _fact(NativeEvaluation(request, result), STANDARD_SCENARIO)
    if fact.initial_cash != 1_000_000 or len(fact.account) != 1636:
        raise ValueError('EX062 native economics requires original1m cash and1636-session grid')
    if fact.account[0].session != '2020-01-02' or fact.account[-1].session != '2026-09-30':
        raise ValueError('EX062 native economics cannot change approved development dates')
    audited = economics(fact)
    if audited['gates'] is None:
        raise ValueError('original four goals require matching executable benchmark')
    audited['account_audit'] = {
        'status': 'PASS', 'max_cash_error': audited['max_cash_error'],
        'max_mark_error': audited['max_mark_error'],
        'closed_cycles_reconciled': audited['closed_trades'],
        'scope': 'independent fill fees/cash/quantity/equity/closed-cycle/continuous-year audit; no signal-path or limit-fill-policy audit claim',
    }
    return audited


def assess_native(*, center: NativeEvaluation, points: tuple[NativeEvaluation, ...],
                  design: ParameterPerturbationDesign, stress: NativeEvaluation | None = None,
                  family: FamilyReturnEvidence | None = None,
                  family_evidence: tuple[AssessmentEvidence, ...] = ()) -> SelfcheckResult:
    """Use original native request/results; do not use a stripped plan-center view."""
    return assess_facts(center=_fact(center, STANDARD_SCENARIO),
        points=tuple(_fact(item, STANDARD_SCENARIO) for item in points), design=design,
        stress=None if stress is None else _fact(stress, STRESS_SCENARIO),
        family=family, family_evidence=family_evidence)
