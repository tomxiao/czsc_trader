"""Public SE complete parameter diagnostics and unchanged four-gate reporting."""
# ruff: noqa: E402
import os

for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

from collections import Counter
import numpy as np
import pandas as pd
from strategy_evaluator import (
    CandidateAssessmentRequest, ParameterRobustnessComparisonRequest, PerturbationLink,
    QuantileMethod, ResearchMetric, SelfCheckProtocol, assess_candidates, compare_parameter_robustness,
)
from strategy_runtime import canonical_sha256
from czsc_trader.research_tools import build_assessment_evidence
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from account_reference import verify_account
from analysis_reference import annual
from direction_oracle import audit_direction
from common import PROTOCOLS, ROOT, RUNS, cache_read, context, file_hash, read, write
from run_parameters import CONTROLS, MANIFEST, TRANSPORT, point_cache, publish_material, source_check


def economic(bound, result):
    run = result.runs[0]
    own, benchmark = run.execution.account_daily, run.buyhold.account_daily
    years, byears = annual(own), annual(benchmark)
    cagr = float((own.equity.iloc[-1] / 1_000_000) ** (252 / len(own)) - 1)
    bcagr = float((benchmark.equity.iloc[-1] / 1_000_000) ** (252 / len(benchmark)) - 1)
    wealth = np.r_[1_000_000, own.equity.to_numpy()]
    drawdown = float(np.max(1 - wealth / np.maximum.accumulate(wealth)))
    closed = int(run.execution.trades.status.eq('CLOSED').sum())
    negative = [year for year in byears if byears[year]['return'] < 0]
    gates = {'return': cagr >= 1.5 * bcagr if bcagr > 0 else cagr > 0,
             'annual_drawdown': all(years[y]['drawdown'] < byears[y]['drawdown'] for y in years),
             'frequency': closed * 60 / len(own) >= 4,
             'negative_buyhold_year_profit': all(years[y]['return'] > 0 for y in negative)}
    audit = verify_account(bound, result)
    return {'net_cagr': cagr, 'drawdown': drawdown, 'closed_trades': closed,
            'frequency60': closed * 60 / len(own), 'annual': years, 'benchmark_annual': byears,
            'gates': gates, 'qualified': all(gates.values()), 'account_audit': audit}


def main():
    source_check()
    manifest = read(MANIFEST)
    if manifest['status'] == 'NOT_APPLICABLE':
        write(RUNS / 'parameter_analysis.json', {'status': 'NOT_APPLICABLE', 'reason': manifest['reason'], 'new_parameter_business_accounts': 0,
                                                    'reused_parameter_accounts': 0, 'actual_parameter_evaluations': 0,
                                                    'technical_duplicate_evaluations': 0,
                                                    'unqualified_control_keys': [],
                                                    'qualified_flags': manifest['qualified_flags']})
        return
    matrix = read(RUNS / 'parameter_matrix.json')
    assert matrix['status'] == 'COMPLETE'
    assert len(matrix['rows']) == len(manifest['centers']) * 32
    prepared = cache_read(TRANSPORT / 'prepared.pkl.gz')
    evidence, links, designs, point_rows, central = [], [], [], {}, {}
    benchmark = prepared[0]['result'].runs[0].buyhold.execution
    def same_benchmark(result):
        for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
            pd.testing.assert_frame_equal(getattr(benchmark, name),
                getattr(result.runs[0].buyhold.execution, name), check_exact=True)
    for record, transport in zip(manifest['centers'], prepared, strict=True):
        assert record['control_key'] == transport['control_key']
        same_benchmark(transport['result'])
        plan = transport['plan']
        center = plan.design.center
        center_facts = build_assessment_evidence(transport['center'], transport['result'])
        assert center_facts[0].candidate == center
        evidence.extend(center_facts)
        designs.append(plan.design)
        central[record['control_key']] = economic(transport['center'], transport['result'])
        if record['control_key'] != 'B0-TIME':
            center_audit = audit_direction(context(1), transport['center'], transport['result'].runs[0].execution.decisions, transport['center'].strategy.payload['parameters'])
            central[record['control_key']]['direction_audit'] = center_audit
        assert central[record['control_key']]['qualified'] == record['center_qualified']
        point_rows[record['control_key']] = []
        rows = [row for row in matrix['rows'] if row['control_key'] == record['control_key']]
        assert sorted(row['point_index'] for row in rows) == list(range(32))
        for row in rows:
            bound, result = cache_read(point_cache(record['control_key'], row['label']))
            ref = EvidenceRef.from_dict(row['reference'])
            assert file_hash(ref.resolve(ROOT)) == ref.sha256
            formal = read(ref.resolve(ROOT))
            validate_evaluation_evidence(formal)
            assert serialize_evaluation_evidence(bound, result) == formal
            same_benchmark(result)
            facts = build_assessment_evidence(bound, result)
            assert len(facts) == 1
            evidence.extend(facts)
            binding = bound.lineage.parameter_binding.point
            assert binding == plan.design.bind_point(row['point_index'])
            links.append(PerturbationLink(center, facts[0].candidate, 1.,
                canonical_sha256(bound.lineage.derivation.to_dict()), binding))
            direction_audit = (None if record['control_key'] == 'B0-TIME' else audit_direction(
                context(1), bound, result.runs[0].execution.decisions, bound.strategy.payload['parameters']))
            point_rows[record['control_key']].append({**row, **economic(bound, result),
                'direction_audit': direction_audit,
                'coordinates': list(binding.coordinates), 'actual_radius': binding.actual_radius})
    protocol = SelfCheckProtocol('S013-EX046-common-domain-parameter-diagnostic-v1',
        'full', 'baseline', 'not_run_stress', 126, 21, QuantileMethod.LINEAR,
        32, 20, 2000, 20, 13, 1e-6, 10, designs[0].protocol)
    request = CandidateAssessmentRequest(tuple(x.center for x in designs), protocol, tuple(links),
                                         tuple(evidence), parameter_designs=tuple(designs))
    panel = assess_candidates(request)
    comparison = compare_parameter_robustness(ParameterRobustnessComparisonRequest(panel.rows))
    assert comparison.comparable, comparison.to_dict()
    summaries = {}
    for record, row in zip(manifest['centers'], panel.rows, strict=True):
        label = record['control_key']
        values = {x.metric: x for x in row.diagnostics}
        return_metric = values[ResearchMetric.PARAMETER_RETURN_DEGRADATION]
        dd_metric = values[ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION]
        assert return_metric.status.value == dd_metric.status.value == 'AVAILABLE'
        points = point_rows[label]
        q10 = float(np.quantile([x['net_cagr'] for x in points], .1, method='linear'))
        q90 = float(np.quantile([x['drawdown'] for x in points], .9, method='linear'))
        assert abs(return_metric.value - max(0., central[label]['net_cagr'] - q10)) < 1e-12
        assert abs(dd_metric.value - max(0., q90 - central[label]['drawdown'])) < 1e-12
        summaries[label] = {'candidate_id': record['candidate_id'], 'mechanism': record['mechanism'],
            'background': record['background'], 'center': central[label], 'complete_points': len(points),
            'role': record['role'], 'center_qualified': record['center_qualified'],
            'implementation_parent': record.get('implementation_parent'),
            'time_semantics': record.get('time_semantics', 'Original held-session TIME'),
            'entry_direction_structure': record.get('entry_direction_structure'),
            'source_sha256': record.get('source_sha256'),
            'q10_cagr': q10, 'q90_drawdown': q90,
            'return_degradation': return_metric.value, 'drawdown_degradation': dd_metric.value,
            'qualified_points': sum(x['qualified'] for x in points),
            'failed_gate_counts': dict(Counter(name for x in points for name, passed in x['gates'].items() if not passed)),
            'known_low_error_potential_orders': sum(x['account_audit']['known_low_error_potential_orders'] for x in points),
            'parameter_context': row.parameter_context.to_dict()}
    original = summaries['B0-TIME']
    differences = {label: {
        'center_cagr_difference': row['center']['net_cagr'] - original['center']['net_cagr'],
        'center_drawdown_difference': row['center']['drawdown'] - original['center']['drawdown'],
        'return_degradation_difference': row['return_degradation'] - original['return_degradation'],
        'drawdown_degradation_difference': row['drawdown_degradation'] - original['drawdown_degradation'],
        'q10_cagr_difference': row['q10_cagr'] - original['q10_cagr'],
        'q90_drawdown_difference': row['q90_drawdown'] - original['q90_drawdown']}
        for label, row in summaries.items() if label != 'B0-TIME'}
    coupled = summaries['B0-COUPLED']
    differences_from_coupled = {key: summaries['N0'][key] - coupled[key] for key in
        ('q10_cagr', 'q90_drawdown', 'return_degradation', 'drawdown_degradation')}
    output = {'status': 'PASS', 'summaries': summaries, 'differences_from_original': differences,
        'differences_from_coupled': differences_from_coupled,
        'points': point_rows, 'se_comparison': comparison.to_dict(),
        'diagnostic_boundary': 'Four original gates remain diagnostic on neighbors; no additional eligibility veto.',
        'scope': 'Three centers at all13 original full domains/numeric centers/5%L2/32 identical coordinates. Original raw ACF versus two coupled actual-L MEAN structures; new rawbear-segment category expiry changes only reentry context. L remains active for baseline and score. No categorical robustness/independent validation claim.',
        'historical_comparison': manifest['historical_comparison'],
        'execution_reconciliation': 'Original EX01532 and coupled EX043N0 32 exact native identities/labels/plans/lineage/bindings/accounts reused; control_key aliases and cache subdirectories do not alter native identity. Qualified new32business/33actual only; registered coupled center is IMPLEMENTATION parent and new authenticated center is PARAMETERS parent. New independent oracle audits segment expiry; compatible legacy branch audits coupled control. Actual-L MEAN requires L+21 prices plus original score/route dependencies, no fallback.',
        'new_parameter_business_accounts': manifest['new_parameter_business_accounts'],
        'reused_parameter_accounts': manifest['reused_parameter_accounts'],
        'comparison_basis_from_original': 'All13 numeric centers/domains/32 coordinates identical. New versus coupled changes only category expiry across rawbull, without changing actual-L baseline, original score or any holding exits/H. Comparisons with original also include centered ACF and BELOW reentry structures; no single-coordinate causal inference.',
        'center_eligibility': 'Original four economic goals only; parameter diagnostics do not add a veto or promote unqualified controls.',
        'unqualified_control_keys': manifest['unqualified_control_keys'],
        'qualified_flags': manifest['qualified_flags'],
        'technical_duplicate_evaluations':1,
        'evaluation_count_basis':manifest['evaluation_count_basis'],
        'actual_parameter_evaluations': matrix['actual_run_evaluations'] + read(RUNS / 'parameter_precheck.json')['actual_evaluations']}
    assert set(summaries) == {*CONTROLS, 'N0'}
    assert set(summaries) == {'B0-TIME', 'B0-COUPLED', 'N0'}
    assert all(summaries[label]['center_qualified'] for label in summaries if label != 'B0-TIME')
    assert output['reused_parameter_accounts'] == 64
    assert output['new_parameter_business_accounts'] == 32
    assert output['actual_parameter_evaluations'] == 33
    write(RUNS / 'parameter_analysis.json', output)
    ctx = context(1)
    refs = {
        'request': publish_material(ctx, 'parameter-se-assessment-request', request.to_dict()).to_dict(),
        'panel': publish_material(ctx, 'parameter-se-assessment-panel', panel.to_dict()).to_dict(),
        'analysis': publish_material(ctx, 'parameter-complete-analysis', output).to_dict()}
    write(PROTOCOLS / 'parameter_analysis_references.json', refs)
    print({'parameter_analysis': 'PASS', 'summaries': {
        label: {key: row[key] for key in ('q10_cagr', 'q90_drawdown', 'return_degradation',
                                        'drawdown_degradation', 'qualified_points')}
        for label, row in summaries.items()}}, flush=True)


if __name__ == '__main__':
    main()
