"""Pure synthetic fixture for EX062 selfcheck contracts; no accounts or market I/O."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import numpy as np
import pandas as pd
from strategy_evaluator import (
    AccountPoint, AssessmentCandidate, AssessmentDerivationKind, AssessmentEvidence,
    AssessmentFill, ClosedCycle, EvaluationScenarioContext, FillSide,
    ParameterCoordinate, ParameterCoordinateKind, ParameterDesignRequest,
    ParameterPerturbationProtocol, ParameterSpace, ResearchMetric,
    build_parameter_perturbation_design,
)
from selfcheck import assess_facts, economics


def digest(text):
    return sha256(text.encode()).hexdigest()


def fixture(candidate, number, *, parent=None, binding=None, cost=.001):
    dates = [day.date().isoformat() for day in pd.bdate_range('2020-01-01', periods=600)]
    prices = 100 + 2 * np.sin(np.arange(600) / 10) + .02 * np.arange(600)
    fills, closed = [], []
    for k in range(8):
        entry, exit_ = k * 10, k * 10 + 3
        key = f'pure-cycle-{k}'
        for i, side in ((entry, FillSide.BUY), (exit_, FillSide.SELL)):
            fills.append(AssessmentFill(key, dates[i], side, 10, float(prices[i]), float(10 * prices[i] * cost)))
        closed.append(ClosedCycle(key, dates[exit_]))
    cash, quantity, account = 1_000_000., 0, []
    for date, price in zip(dates, prices):
        for fill in fills:
            if fill.session == date:
                sign = 1 if fill.side is FillSide.BUY else -1
                cash += -sign * fill.price * fill.quantity - fill.fees
                quantity += sign * fill.quantity
        account.append(AccountPoint(date, cash, quantity, float(price), float(cash + quantity * price)))
    return AssessmentEvidence(
        candidate=candidate, experiment_id='PURE_NOT_REGISTERED', attempt_id=f'{number:032x}',
        evaluation_id=digest(f'pure-selfcheck-{number}'), request_sha256=digest(f'request{number}'),
        result_sha256=digest(f'result{number}'), context_sha256=digest('same-pure-context'),
        window_id='full', scenario_id='baseline' if cost == .001 else 'stress_20bp_per_side',
        metric_version='pure-fixture', scenario_context=EvaluationScenarioContext(
            cost, 'FORMAL' if cost == .001 else 'STRESS', 'pure-benchmark', 'LimitBuyHold', digest('same-benchmark')),
        initial_cash=1_000_000., opening_cash=1_000_000., opening_quantity=0, frequency_window_days=60,
        account=tuple(account), fills=tuple(fills), closed_cycles=tuple(closed),
        benchmark_equity=tuple(float(x) for x in 1_000_000 * .9999 ** np.arange(1, 601)), parent=parent,
        derivation_sha256=digest(f'derivation{number}') if parent else None,
        derivation_kind=AssessmentDerivationKind.PARAMETERS if parent else None, parameter_point=binding)


def main():
    center = AssessmentCandidate('S013-C9500', digest('PURE_ONLY_center'))
    space = ParameterSpace(tuple(ParameterCoordinate(f'pure_x{i}', .5, 0., 1., ParameterCoordinateKind.CONTINUOUS)
                                 for i in range(3)), digest('pure_mapping'), digest('pure_constraint'))
    design = build_parameter_perturbation_design(ParameterDesignRequest(center, ParameterPerturbationProtocol(), space),
                                                feasibility=lambda values: True).design
    base = fixture(center, 1)
    points = tuple(fixture(AssessmentCandidate(f'S013-C{9501+i}', digest(f'PURE_ONLY{i}')), 2+i,
                           parent=center, binding=design.bind_point(i)) for i in range(32))
    stress = fixture(center, 50, cost=.002)
    out = assess_facts(center=base, points=points, design=design, stress=stress)
    checks = ['public_SE_five_item_pure_fixture', 'all32_binding_context', 'independent_account_fee_cash_quantity_equity',
              'actual_closed_count_not_buy_count', 'continuous_year_boundary_including_initial',
              'absoluteQ10Q90_match_public_parameter_degradation', 'original_four_gates_no_diagnostic_veto']
    assert out.economics['center']['closed_trades'] == 8
    years = out.economics['center']['annual']
    for first, second in zip(list(years), list(years)[1:]):
        assert years[first]['closing_equity'] == years[second]['opening_equity']
    missing = assess_facts(center=base, points=points, design=design)
    stress_metric = next(item for item in missing.panel.rows[0].diagnostics if item.metric is ResearchMetric.STRESS_ANNUAL_LOSS)
    assert stress_metric.value is None and missing.request.incomplete[0].status.value == 'NOT_RUN'
    assert all(item.value is None for item in missing.panel.family_diagnostics)
    checks += ['missing_pressure_NOT_RUN_no_scheduler', 'family_missing_not_zero_no_selection_correction_claim']
    bad = []
    for label, action in (
        ('missing_point', lambda: assess_facts(center=base, points=points[:-1], design=design)),
        ('duplicate_point', lambda: assess_facts(center=base, points=(*points[:-1], points[0]), design=design)),
        ('parameter_fee_cross', lambda: assess_facts(center=base, points=(replace(points[0], scenario_context=stress.scenario_context), *points[1:]), design=design)),
        ('changed_stress_identity', lambda: assess_facts(center=base, points=points, design=design, stress=replace(stress, candidate=points[0].candidate))),
        ('account_cash_corruption', lambda: economics(replace(base, account=(replace(base.account[0], cash=base.account[0].cash+1), *base.account[1:])))),
        ('closed_trade_corruption', lambda: economics(replace(base, closed_cycles=base.closed_cycles[:-1]))),
    ):
        try:
            action()
        except ValueError:
            bad.append(label)
        else:
            raise AssertionError('Expected rejection: ' + label)
    payload = {'status': 'PASS', 'synthetic_only': True, 'market_reads': 0, 'native_account_runs': 0,
               'publications': 0, 'checks': checks, 'rejection_checks': bad, 'count': len(checks)+len(bad)}
    Path(__file__).with_suffix('.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == '__main__':
    main()
