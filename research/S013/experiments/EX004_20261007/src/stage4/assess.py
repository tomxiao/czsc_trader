"""Assess authenticated published accounts; annual gates stay researcher-owned."""
from collections import defaultdict
import math
import numpy as np
import pandas as pd
from strategy_evaluator import (
    AssessmentEvidence, CandidateAssessmentRequest, PerturbationLink, FamilyReturnEvidence,
    SelfCheckProtocol, ComparisonPolicy, ResearchTargets, CandidateComparisonRequest,
    assess_candidates, compare_candidates, ResearchMetric, DiagnosticStatus,
)
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from phase4_common import RESULTS, ROOT, read, save, source, centers, PLANS
from economics import annual_stats


def facts(ref, quality=None):
    value = read(ref.resolve(ROOT))
    validate_evaluation_evidence(value)
    if quality is not None:
        assert value['data_identity'] == quality['execution_data_identity']
        low = quality['low_error']
        affected = set(quality['high_error_dates']) | {low['date']}
        for run in value['runs']:
            evaluation_id = next(e['evaluation_id'] for e in value['assessment_evidence']
                                 if (e['window_id'], e['scenario_id']) == (run['window_id'], run['scenario_id']))
            quality['evaluation_coordinates'] += 1
            for order in run['ledgers']['orders']['data']:
                day = order['execution_date'][:10]
                if day not in affected:
                    continue
                potential = (day == low['date'] and order['side'] == 'BUY'
                    and order['order_type'] == 'LIMIT' and order['status'] == 'UNFILLED'
                    and low['normalized_lower'] < float(order['limit_price']) <= low['normalized_upper'])
                quality['orders_on_error_dates'].append({
                    'candidate_id': run['candidate_id'], 'scenario_id': run['scenario_id'],
                    'evaluation_id': evaluation_id, 'date': day,
                    'side': order['side'], 'order_type': order['order_type'],
                    'status': order['status'], 'limit_price': order['limit_price'],
                    'potential_economic_change_from_low_error': potential})
    return tuple(AssessmentEvidence.from_dict(x) for x in value['assessment_evidence'])


def annual(evidence):
    own = pd.DataFrame({'date': [x.session for x in evidence.account],
                        'equity': [x.equity for x in evidence.account]})
    benchmark = own.assign(equity=evidence.benchmark_equity)
    years, by = annual_stats(own, evidence.initial_cash), annual_stats(benchmark, evidence.initial_cash)
    returns = float((own.equity.iloc[-1]/evidence.initial_cash)**(252/len(own))-1)
    bhreturn = float((benchmark.equity.iloc[-1]/evidence.initial_cash)**(252/len(own))-1)
    frequency = 60 * len(evidence.closed_cycles)/len(own)
    negative = [y for y in by if by[y]['return'] < 0]
    margins = {y: by[y]['max_drawdown_magnitude']-years[y]['max_drawdown_magnitude'] for y in by}
    gates = {'return': returns >= 1.5*bhreturn,
             'annual_drawdown': all(m > 0 for m in margins.values()),
             'frequency': frequency >= 4,
             'negative_buyhold_year_profit': all(years[y]['return'] > 0 for y in negative)}
    return {'net_cagr': returns, 'buyhold_cagr': bhreturn, 'frequency60': frequency,
            'closed_trades': len(evidence.closed_cycles), 'annual': years, 'buyhold_annual': by,
            'negative_buyhold_years': negative, 'annual_dd_margins': margins,
            'gates': gates, 'qualified': all(gates.values()), 'evaluation_id': evidence.evaluation_id}


def metrics(evidence):
    equity = np.r_[evidence.initial_cash, [x.equity for x in evidence.account]]
    return (float((equity[-1]/equity[0])**(252/(len(equity)-1))-1),
            float(np.max(1-equity/np.maximum.accumulate(equity))))


def independent_checks(request, panel):
    index = {(e.candidate, e.scenario_id): e for e in request.evidence}
    checks = []
    for row in panel.rows:
        base = index[row.candidate, 'baseline']
        neighbors = [index[link.child, 'baseline'] for link in request.perturbations if link.parent == row.candidate]
        center_cagr, center_dd = metrics(base)
        neighbor_perf = [metrics(e) for e in neighbors]
        values = {
            ResearchMetric.NET_ANNUAL_RETURN: center_cagr,
            ResearchMetric.DRAWDOWN_MAGNITUDE: center_dd,
            ResearchMetric.PARAMETER_RETURN_DEGRADATION: max(0., center_cagr-float(np.quantile([x[0] for x in neighbor_perf], .1))),
            ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION: max(0., float(np.quantile([x[1] for x in neighbor_perf], .9))-center_dd),
            ResearchMetric.STRESS_ANNUAL_LOSS: center_cagr-metrics(index[row.candidate, request.protocol.stress_scenario])[0],
        }
        bh = np.r_[base.initial_cash, base.benchmark_equity]
        own = np.r_[base.initial_cash, [x.equity for x in base.account]]
        size, step = request.protocol.rolling_window_days, request.protocol.rolling_step_days
        excess = own[size::step]/own[:len(own)-size:step] - bh[size::step]/bh[:len(bh)-size:step]
        values[ResearchMetric.ROLLING_EXCESS_Q10] = float(np.quantile(excess, .1))
        flow = defaultdict(float)
        for fill in base.fills:
            direction = -1 if fill.side.value == 'BUY' else 1
            flow[fill.cycle_id] += direction * fill.quantity * fill.price-fill.fees
        positive = sorted([flow[c.cycle_id] for c in base.closed_cycles if flow[c.cycle_id] > 0], reverse=True)
        values[ResearchMetric.PROFIT_CONCENTRATION] = sum(positive[:math.ceil(.1*len(positive))])/sum(positive)
        cash, quantity = base.opening_cash, base.opening_quantity
        fills = defaultdict(list)
        for fill in base.fills:
            fills[fill.session].append(fill)
        maximum_error = 0.
        for point in base.account:
            for fill in fills[point.session]:
                sign = 1 if fill.side.value == 'BUY' else -1
                cash -= sign*fill.quantity*fill.price + fill.fees
                quantity += sign*fill.quantity
            assert quantity == point.quantity
            maximum_error = max(maximum_error, abs(cash-point.cash),
                                abs(point.equity-point.cash-point.quantity*point.close))
        assert maximum_error < request.protocol.reconciliation_tolerance
        for diagnostic in row.diagnostics:
            if diagnostic.metric in values:
                assert diagnostic.status is DiagnosticStatus.AVAILABLE, diagnostic.to_dict()
                assert abs(diagnostic.value-values[diagnostic.metric]) < 1e-12, (row.candidate, diagnostic)
        assert not row.coverage_gaps, row.coverage_gaps
        checks.append({'candidate_id': row.candidate.candidate_id, 'seven_metrics': 'PASS',
                       'annual_four_gates': annual(base)['gates'], 'rolling_windows': len(excess),
                       'max_daily_reconciliation_error': maximum_error})
    return checks


def main():
    plan = read(PLANS/'plan.json')
    predecessor = source('CANDIDATES', 3)
    entries = predecessor.payload.candidates
    quality_source = next(r for r in predecessor.evidence if r.name == 'four-gate-quality-impact')
    quality = read(quality_source.resolve(ROOT))
    quality['source'] = quality_source.to_dict()
    quality['scope'] = '阶段四17个原正式账户、80个联合扰动和20个压力场景的实际订单；所有事实共用同一原执行数据'
    quality.pop('successful_configurations')
    quality['evaluation_coordinates'] = 0
    quality['orders_on_error_dates'] = []
    evidence = []
    for entry in entries:
        evidence.extend(facts(entry.evaluations[0].evidence, quality))
    original = tuple(evidence)
    for batch in range(math.ceil(len(plan['cases'])/4)):
        value = read(RESULTS/f'batch_{batch:02}.json')
        for row in value['rows']:
            assert row['status'] == 'SUCCEEDED', row
            evidence.extend(facts(EvidenceRef.from_dict(row['reference']), quality))
    quality['potential_economic_change_count'] = sum(r['potential_economic_change_from_low_error']
                                                   for r in quality['orders_on_error_dates'])
    save('quality_impact.json', quality)
    center_ids = {f'S013-{e.identity.key.candidate_id}' for e in centers()}
    central = tuple(e.candidate for e in original if e.candidate.candidate_id in center_ids)
    links = tuple(PerturbationLink(e.parent, e.candidate, 1., e.derivation_sha256)
                  for e in evidence if e.parent is not None)
    family_members = tuple(e.candidate for e in original)
    matrix = np.array([[p.equity for p in e.account] for e in original]).T
    previous = np.vstack([np.array([e.initial_cash for e in original]), matrix[:-1]])
    returns = matrix / previous - 1
    family = FamilyReturnEvidence(family_members, tuple(p.session for p in original[0].account),
        tuple(tuple(float(x) for x in row) for row in returns),
        next(c for c in family_members if c.candidate_id == 'S013-C0494'),
        plan['family_raw_trial_count'], (
            plan['family_matrix'], plan['trial_count_basis'], plan['selection'],
            '矩阵亦不含本次80个扰动收益；PBO和有效DSR仅条件于17个保留成员，不能校正完整搜索。原始DSR虽采用590次计数，trial Sharpe离散度也来自有偏子集，不能声称总体统计必然保守。',
            plan['holdout'],))
    request = CandidateAssessmentRequest(central, SelfCheckProtocol.from_dict(plan['protocol']), links,
                                          tuple(evidence), family_returns=family)
    panel = assess_candidates(request)
    mandate = source('MANDATE', 5).payload
    targets = tuple(t for i in mandate.items if isinstance(i.requirement, __import__('czsc_trader.research_tools.delivery', fromlist=['PerformanceRequirement']).PerformanceRequirement)
                    for t in i.requirement.targets)
    compare_request = CandidateComparisonRequest(central, ResearchTargets(targets, 60), panel,
                                                 ComparisonPolicy.from_dict(plan['comparison_policy']))
    comparison = compare_candidates(compare_request)
    audit = independent_checks(request, panel)
    all_four = {}
    neighborhood = {}
    for center in central:
        records = [annual(e) for e in evidence if e.parent == center]
        neighborhood[center.candidate_id] = {'count': len(records),
            'qualified': sum(r['qualified'] for r in records),
            'gate_pass_counts': {k: sum(r['gates'][k] for r in records) for k in records[0]['gates']},
            'records': records}
        slots = {e.scenario_id: annual(e) for e in evidence if e.candidate == center}
        assert slots['baseline']['qualified'], slots['baseline']
        all_four[center.candidate_id] = slots
    save('assessment_request.json', request.to_dict())
    save('assessment.json', panel.to_dict())
    save('comparison_request.json', compare_request.to_dict())
    save('comparison.json', comparison.to_dict())
    save('annual_four_gates.json', {'standard_and_stress': all_four,
        'standard_four_gate_qualified': len(all_four), 'interpretation': '中心标准场景四门决定研究资格；压力与扰动场景四门通过率只作诊断。'})
    save('neighborhood_four_gates.json', neighborhood)
    save('independent_verification.json', {'status': 'PASS', 'checks': audit,
        'all_center_standard_gates': 'PASS', 'authenticated_published_evidence': len(evidence),
        'bootstrap': '公共SE配对平稳区块重采样，保留随机长度的相邻连续块；返回CAGR差95%区间。',
        'source_accounts': 17, 'parameter_accounts': len(links), 'stress_accounts': 20})
    sensitivity = []
    for variant in comparison.sensitivities:
        sensitivity.append({'name': variant.name, 'ranking': [r.to_dict() for r in variant.rows]})
    save('sensitivity.json', {'variants': sensitivity, 'behavior_groups': [g.to_dict() for g in comparison.behavior_groups]})
    print({'centers': len(panel.rows), 'metrics': 'COMPLETE', 'annual_gates': 'PASS',
        'ranking': [{'candidate': r.candidate.candidate_id, 'layer': r.pareto_layer, 'rank': r.rank_in_layer} for r in comparison.rows],
        'family_diagnostics': [x.to_dict() for x in panel.family_diagnostics]}, flush=True)


if __name__ == '__main__':
    main()
