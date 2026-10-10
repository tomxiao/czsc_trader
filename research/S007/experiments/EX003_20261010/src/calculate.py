"""Four diagnostic formulas; no composite score, new economic gate, or ranking."""
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from common import ROOT, PROTOCOLS, RUNS, read, write, material
import independent_audit as audit


def load(ref, refs):
    reference = EvidenceRef.from_dict(ref)
    value = read(reference.resolve(ROOT))
    validate_evaluation_evidence(value)
    refs.append(reference.to_dict())
    return value


def account_metrics(evidence):
    wealth = np.r_[evidence['initial_cash'], [x['equity'] for x in evidence['account']]]
    return {'net_cagr': float((wealth[-1]/wealth[0])**(252/len(evidence['account']))-1),
            'drawdown_magnitude': float(np.max(1-wealth/np.maximum.accumulate(wealth)))}


def select(raw, scenario):
    return next(x for x in raw['assessment_evidence'] if x['scenario_id'] == scenario)


def main():
    assert read(RUNS/'center_reproduction.json')['status'] == 'PASS'
    assert read(RUNS/'c2132_center_reproduction.json')['status'] == 'PASS'
    refs = []
    s007 = load(read(RUNS/'center_reference.json'), refs)
    standard = select(s007, 'baseline')
    stress = select(s007, 'stress_20bp_per_side')
    assert standard['scenario_context']['one_way_cost'] == .001
    assert stress['scenario_context']['one_way_cost'] == .002
    assert standard['candidate'] == stress['candidate']
    standard_metrics, pressure_metrics = account_metrics(standard), account_metrics(stress)
    neighbors = read(RUNS/'neighborhood.json')['rows']
    assert len(neighbors) == 8 and all(x['status']=='SUCCEEDED' for x in neighbors)
    new_metrics = [account_metrics(select(load(x['evidence'], refs), 'baseline')) for x in neighbors]
    q10 = float(np.quantile([x['net_cagr'] for x in new_metrics], .1, method='linear'))
    q90 = float(np.quantile([x['drawdown_magnitude'] for x in new_metrics], .9, method='linear'))
    account = pd.DataFrame(standard['account']).rename(columns={'session': 'date'})
    fills = [dict(x, date=x['session']) for x in standard['fills']]
    concentration = audit.reconcile(account, fills,
        {x['cycle_id']: x['exit_session'] for x in standard['closed_cycles']},
        standard['initial_cash'], standard['opening_cash'], standard['opening_quantity'], 's007-regenerated')
    benchmark = pd.DataFrame({'date': account['date'], 'equity': standard['benchmark_equity']})
    rolling = audit.rolling(account, benchmark, standard['initial_cash'], 's007-executable')
    independent = read(RUNS/'independent-audit/independent_audit.json')
    assert concentration['profit_concentration'] == independent['s007']['concentration']['profit_concentration']
    family = read(ROOT/'research/S013/assets/runs/EX008_20261010/rows.json')['rows']
    relevant = [x for x in family if x['parent']['key']['candidate_id']=='C2132']
    control = read(RUNS/'c2132_center_reproduction.json')
    c2132 = select(load(control['original'], refs), 'baseline')
    load(control['reproduced'], refs)
    c2132_metrics = account_metrics(c2132)
    c2132_neighbors = [account_metrics(select(load(x['reference'], refs), 'baseline'))
                        for x in relevant if x['kind']=='PARAMETERS']
    assert len(c2132_neighbors) == 8
    c2132_stress_raw = load(next(x for x in relevant if x['kind']=='STRESS')['reference'], refs)
    c2132_stress = select(c2132_stress_raw, 'stress_20bp_per_side')
    assert c2132_stress['candidate'] == c2132['candidate']
    assert c2132_stress['scenario_context']['one_way_cost'] == .002
    c2132_pressure = account_metrics(c2132_stress)
    c2132_q10 = float(np.quantile([x['net_cagr'] for x in c2132_neighbors], .1, method='linear'))
    c2132_q90 = float(np.quantile([x['drawdown_magnitude'] for x in c2132_neighbors], .9, method='linear'))
    row = next(x for x in read(ROOT/'research/S013/assets/runs/EX008_20261010/assessment.json')['rows']
               if x['candidate']['candidate_id']=='S013-C2132')
    formal = {x['metric']: x['value'] for x in row['diagnostics']}
    computed_c2132 = {
        'PARAMETER_RETURN_DEGRADATION': max(0., c2132_metrics['net_cagr']-c2132_q10),
        'PARAMETER_DRAWDOWN_DEGRADATION': max(0., c2132_q90-c2132_metrics['drawdown_magnitude']),
        'STRESS_ANNUAL_LOSS': c2132_metrics['net_cagr']-c2132_pressure['net_cagr'],
        'PROFIT_CONCENTRATION': independent['s013_c2132']['concentration']['profit_concentration'],
        'ROLLING_EXCESS_Q10': independent['s013_c2132']['time_stability']['q10_linear']}
    assert all(abs(formal[k]-v)<1e-12 for k,v in computed_c2132.items())
    s007_metrics = {
        'standard_net_cagr': standard_metrics['net_cagr'], 'pressure_net_cagr': pressure_metrics['net_cagr'],
        'cost_loss': standard_metrics['net_cagr']-pressure_metrics['net_cagr'],
        'parameter_q10_cagr': q10,
        'parameter_return_degradation': max(0., standard_metrics['net_cagr']-q10),
        'parameter_q90_drawdown': q90,
        'parameter_drawdown_worsening': max(0., q90-standard_metrics['drawdown_magnitude']),
        'profit_concentration': concentration['profit_concentration'],
        'rolling_q10_executable_benchmark': rolling['q10_linear'],
        'rolling_q10_legacy_fractional_benchmark': independent['s007']['time_stability']['q10_linear']}
    c2132_values = {'standard_net_cagr': c2132_metrics['net_cagr'], 'pressure_net_cagr': c2132_pressure['net_cagr'],
        'cost_loss': computed_c2132['STRESS_ANNUAL_LOSS'], 'parameter_q10_cagr': c2132_q10,
        'parameter_return_degradation': computed_c2132['PARAMETER_RETURN_DEGRADATION'],
        'parameter_q90_drawdown': c2132_q90,
        'parameter_drawdown_worsening': computed_c2132['PARAMETER_DRAWDOWN_DEGRADATION'],
        'profit_concentration': computed_c2132['PROFIT_CONCENTRATION'],
        'rolling_q10_executable_benchmark': computed_c2132['ROLLING_EXCESS_Q10']}
    baseline_quantities = [x['quantity'] for x in standard['fills'] if x['side']=='BUY']
    stressed_quantities = [x['quantity'] for x in stress['fills'] if x['side']=='BUY']
    assert len(baseline_quantities)==len(stressed_quantities)==139
    quantity_changes = sum(a!=b for a,b in zip(baseline_quantities, stressed_quantities, strict=True))
    assert quantity_changes > 0
    result = {'status': 'NUMERICAL_CHECKS_PASS', 'units': 'ratios; multiply by100 for percent or percentage points',
        'scope': 'Four diagnostics only; no new economic gates, combined score or overall winner',
        'S007': s007_metrics, 'C2132': c2132_values,
        'parameter_points': new_metrics, 'S007_concentration_details': concentration,
        'S007_time_details': rolling, 'S007_pressure_buy_quantity_changes': quantity_changes,
        'benchmark_decision': 'PENDING_HUMAN_CONFIRMATION',
        'formal_account_validation': {'count': len(refs), 'method': 'Public validate_evaluation_evidence; all full ledgers/identities/metrics authenticated', 'references': refs},
        'C2132_formal_metric_differences': {k: v-formal[k] for k,v in computed_c2132.items()},
        'comparability': {'cost': 'same side10->20bp FULL account method, different instruments/pools/capital',
                         'parameters': 'same8 points/seed13/quantiles, different dimension/structure/scale; not equal stress strength',
                         'concentration': 'same top ceil10% positive closed-cycle CASH NET profit formula',
                         'time': 'same126/21/LINEAR formula; different native markets/pools; S007 legacy fractional-BH correction awaits confirmation'}}
    write(RUNS/'four_diagnostics.json', result)
    write(PROTOCOLS/'four_diagnostics_reference.json', material('four-diagnostics-numerical-results',
        RUNS/'four_diagnostics.json').to_dict())
    print({'S007': s007_metrics, 'C2132': c2132_values, 'validated_full_account_evidence': len(refs),
           'S007_quantity_changes_under_cost_stress': quantity_changes}, flush=True)


if __name__ == '__main__':
    main()
