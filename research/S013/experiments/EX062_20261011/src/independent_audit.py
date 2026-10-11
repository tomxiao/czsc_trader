"""EX062 independent audit, gated on complete native run plus selfchecks.

No market fetch, prepare, evaluation, publication or frozen-source mutation.
CLI requires --audit-complete; writes only its audit result in this .tmp folder.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-robust-center'
RUN = WORK / 'run'
SRC = ROOT / 'research/S013/experiments/EX062_20261011/src'
sys.path.insert(0, str(SRC))
import driver  # noqa: E402
from czsc_trader.research_tools import build_assessment_evidence  # noqa: E402
from czsc_trader.research_tools.evidence import EvidenceRef  # noqa: E402
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence  # noqa: E402
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan  # noqa: E402
from strategy_evaluator import CandidateAssessmentRequest, assess_candidates  # noqa: E402

GATES = ('return', 'annual_drawdown', 'frequency', 'negative_buyhold_year_profit')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def numeric_same(actual, expected, tolerance=1e-12):
    if actual is None or expected is None:
        assert actual is expected
    else:
        assert abs(actual - expected) <= tolerance, (actual, expected)


def independent_economics(fact):
    """Different direct array calculation of continuous equity/year gates."""
    values = np.asarray([row.equity for row in fact.account], dtype=float)
    benchmark = np.asarray(fact.benchmark_equity, dtype=float)
    dates = np.asarray([row.session[:4] for row in fact.account])
    assert len(values) == len(benchmark) == 1636
    assert fact.initial_cash == 1_000_000
    assert fact.account[0].session == '2020-01-02' and fact.account[-1].session == '2026-09-30'
    own_cagr = float((values[-1] / 1_000_000) ** (252 / len(values)) - 1)
    base_cagr = float((benchmark[-1] / 1_000_000) ** (252 / len(values)) - 1)
    annual, base_annual = {}, {}
    for array, output in ((values, annual), (benchmark, base_annual)):
        anchor = 1_000_000.
        for year in sorted(set(dates)):
            segment = array[dates == year]
            path = np.concatenate(([anchor], segment))
            peak = np.maximum.accumulate(path)
            output[str(year)] = {'return': float(segment[-1] / anchor - 1),
                                  'drawdown': float(np.max((peak - path) / peak)),
                                  'opening_equity': anchor, 'closing_equity': float(segment[-1])}
            anchor = float(segment[-1])
    closed = len(fact.closed_cycles)
    assert len({cycle.cycle_id for cycle in fact.closed_cycles}) == closed
    negative = [year for year in base_annual if base_annual[year]['return'] < 0]
    gates = {'return': own_cagr >= 1.5 * base_cagr if base_cagr > 0 else own_cagr > 0,
             'annual_drawdown': all(annual[year]['drawdown'] < base_annual[year]['drawdown'] for year in annual),
             'frequency': closed * 60 / len(values) >= 4,
             'negative_buyhold_year_profit': all(annual[year]['return'] > 0 for year in negative)}
    path = np.concatenate(([1_000_000.], values))
    peak = np.maximum.accumulate(path)
    return {'net_cagr': own_cagr, 'drawdown': float(np.max((peak-path)/peak)),
            'closed_trades': closed, 'frequency60': closed*60/len(values),
            'annual': annual, 'benchmark_annual': base_annual,
            'gates': gates, 'qualified': all(gates.values())}


def compare_economics(actual, stored):
    for key in ('net_cagr', 'drawdown', 'frequency60'):
        numeric_same(actual[key], stored[key])
    assert actual['closed_trades'] == stored['closed_trades']
    assert actual['gates'] == stored['gates'] and actual['qualified'] == stored['qualified']
    for name, keys in (
        ('annual', ('return', 'drawdown', 'opening_equity', 'closing_equity')),
        ('benchmark_annual', ('return', 'drawdown')),
    ):
        assert set(actual[name]) == set(stored[name])
        for year in actual[name]:
            for key in keys:
                value = actual[name][year][key]
                numeric_same(value, stored[name][year][key], 1e-9 if key.endswith('equity') else 1e-12)


def authenticated(pair, reference, scenario='baseline'):
    """Authenticate public full serialization and native identity without prepare."""
    request, result = pair
    ref = EvidenceRef.from_dict(reference) if isinstance(reference, dict) else reference
    assert ref.experiment.strategy_id == 'S013'
    formal = read(ref.resolve(ROOT))
    validate_evaluation_evidence(formal)
    assert serialize_evaluation_evidence(request, result) == formal
    assert request.strategy.strategy_family_id == 'S013'
    facts = build_assessment_evidence(request, result)
    selected = [item for item in facts if item.window_id == 'full' and item.scenario_id == scenario]
    assert len(selected) == 1
    fact = selected[0]
    assert fact.request_sha256 == result.request_hash and fact.result_sha256 == result.result_hash
    assert fact.candidate.content_sha256 == result.runs[0].identity.content_sha256
    assert result.data_identity == request.execution_data.fingerprint
    return fact, ref


def vector_payload(center_parameters, coordinates, vector):
    result = deepcopy(center_parameters)
    for (name, lower, upper, kind), value in zip(coordinates, vector, strict=True):
        assert lower <= value <= upper
        if kind == 'INTEGER':
            assert float(value).is_integer()
        target = result
        parts = name.split('.')
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = int(value) if kind == 'INTEGER' else float(value)
    return result


def independent_selection(rows):
    baseline = next(row for row in rows if row['label'] == 'BASE')
    qualified = [row for row in rows if row['center_qualified']]
    preferred = [row for row in qualified if row['label'] != 'BASE'
                 and row['q10_cagr'] >= baseline['q10_cagr']
                 and row['q90_drawdown'] <= baseline['q90_drawdown']
                 and (row['q10_cagr'] > baseline['q10_cagr'] or row['q90_drawdown'] < baseline['q90_drawdown'])]
    preferred.sort(key=lambda row: (-row['joint_pass_count'], -row['q10_cagr'], row['q90_drawdown'], row['queue_index']))
    def dominates(first, second):
        a = (first['joint_pass_count'], first['q10_cagr'], -first['q90_drawdown'])
        b = (second['joint_pass_count'], second['q10_cagr'], -second['q90_drawdown'])
        return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))
    return {'preferred': preferred[0]['label'] if preferred else None,
            'absolute_tail_improvement_found': bool(preferred),
            'qualified_labels': [row['label'] for row in qualified],
            'pareto_all': [row['label'] for row in rows if not any(dominates(other, row) for other in rows)],
            'relative_degradation_report_only': True,
            'tie_break': 'joint count descending, Q10 descending, Q90 ascending, frozen queue order'}


def run_audit():
    """Only after full fixed run, analysis and selected selfchecks are complete."""
    state = read(RUN / 'checkpoint.json')
    analysis = read(RUN / 'analysis.json')
    checks = read(RUN / 'selfchecks.json')
    assert state['status'] == analysis['status'] == checks['status'] == 'COMPLETE'
    assert state['failure'] is None and len(analysis['centers']) == 9
    method_ref = EvidenceRef.from_dict(read(WORK / 'method_reference.json'))
    method = driver.draft.require_frozen_method(method_ref)
    assert method['status'] == 'FROZEN_FOR_EXECUTION' and len(method['queue']) == 9
    driver.legacy_pickle_support()
    records = driver.cache_read(RUN / 'prepared.pkl.gz')
    assert len(records) == 9
    all_roles, summaries, complete = [], [], {}
    for index, stored in enumerate(analysis['centers']):
        assert stored['queue_index'] == index and stored['label'] == method['queue'][index]['label']
        native = driver.cache_read(RUN / f'complete-center-{index:02}.pkl.gz')
        complete[index] = native
        plan_ref = EvidenceRef.from_dict(stored['plan_reference'])
        plan = read_parameter_plan(plan_ref, ROOT)
        assert plan == records[index]['plan'] and plan.design == native['design']
        assert plan.center.candidate == native['design'].center
        assert stored['prospective_view_request_hash'] == plan.center_request_sha256
        center_fact, center_ref = authenticated(native['center'], stored['center_reference'])
        assert center_fact.candidate == plan.design.center
        assert stored['native_center_request_hash'] == native['center'][1].request_hash
        assert center_fact.scenario_context.one_way_cost == .001
        own = independent_economics(center_fact)
        compare_economics(own, stored['center'])
        # Reuse helper only for an additional fill/cash/quantity/cycle audit, not as independent equity formula.
        helper = driver.selfcheck.economics(center_fact)
        compare_economics(own, helper)
        all_roles.append({'role': stored['label']+':center', 'candidate': center_fact.candidate.to_dict(),
                          'reference': center_ref.to_dict(), 'request_hash': native['center'][1].request_hash})
        points = []
        assert len(native['points']) == len(stored['points']) == len(stored['point_references']) == 32
        for point_index, (pair, stored_point, point_reference) in enumerate(zip(
                native['points'], stored['points'], stored['point_references'], strict=True)):
            fact, ref = authenticated(pair, point_reference)
            assert pair[0].lineage.parameter_binding.plan == plan_ref
            assert pair[0].lineage.parameter_binding.point == plan.design.bind_point(point_index)
            assert fact.parent == center_fact.candidate and fact.parameter_point == plan.design.bind_point(point_index)
            assert fact.candidate == plan.children[point_index].candidate
            assert fact.scenario_context == center_fact.scenario_context
            assert fact.context_sha256 == center_fact.context_sha256
            expected_parameters = vector_payload(driver.draft.plain(native['center'][0].strategy.payload['parameters']),
                                                  method['coordinates'], plan.design.points[point_index].coordinates)
            assert driver.draft.plain(pair[0].strategy.payload['parameters']) == expected_parameters
            own_point = independent_economics(fact)
            compare_economics(own_point, stored_point)
            compare_economics(own_point, driver.selfcheck.economics(fact))
            points.append(own_point)
            all_roles.append({'role': stored['label']+f':P{point_index:02}', 'candidate': fact.candidate.to_dict(),
                              'reference': ref.to_dict(), 'request_hash': pair[1].request_hash})
        cagr = sorted(point['net_cagr'] for point in points)
        dd = sorted(point['drawdown'] for point in points)
        # Independent explicit linear interpolation of prescribed32 values.
        def quantile(ordered, q):
            position = (len(ordered)-1)*q
            lower = int(position)
            return ordered[lower] + (position-lower)*(ordered[min(lower+1, len(ordered)-1)]-ordered[lower])
        summary = {'queue_index': index, 'label': stored['label'], 'center_qualified': own['qualified'],
                   'center_gates': own['gates'], 'complete_points': 32,
                   'joint_pass_count': sum(point['qualified'] for point in points),
                   'gate_pass_counts': {gate: sum(point['gates'][gate] for point in points) for gate in GATES},
                   'q10_cagr': quantile(cagr, .1), 'q90_drawdown': quantile(dd, .9)}
        summary['return_degradation'] = max(0, own['net_cagr']-summary['q10_cagr'])
        summary['drawdown_degradation'] = max(0, summary['q90_drawdown']-own['drawdown'])
        for key, value in summary.items():
            if key in ('q10_cagr', 'q90_drawdown', 'return_degradation', 'drawdown_degradation'):
                numeric_same(value, stored[key])
            else:
                assert value == stored[key], (index, key, value, stored[key])
        summaries.append(summary)
    selection = independent_selection(summaries)
    for key, value in selection.items():
        assert value == analysis['selection'][key], (key, value, analysis['selection'][key])
    content = {role['candidate']['content_sha256'] for role in all_roles}
    new_roles = [role for role in all_roles if role['reference']['experiment']['experiment_id'] == 'EX062_20261011']
    old_roles = [role for role in all_roles if role not in new_roles]
    new_content = {role['candidate']['content_sha256'] for role in new_roles}
    old_refs = {role['reference']['sha256'] for role in old_roles}
    assert len(all_roles) == 297 and len(content) == 294
    assert len(new_roles) == 262 and len(new_content) == 261
    assert len(old_roles) == 35 and len(old_refs) == 33
    first = complete[1]['points'][21]
    second = complete[2]['points'][0]
    assert first[0].strategy.candidate_id == second[0].strategy.candidate_id == 'C0621'
    assert first[0].strategy == second[0].strategy
    assert first[0].lineage.parameter_binding.plan != second[0].lineage.parameter_binding.plan
    assert first[0].lineage.parameter_binding.point != second[0].lineage.parameter_binding.point
    assert first[1].request_hash != second[1].request_hash
    a, b = first[1].runs[0], second[1].runs[0]
    pd.testing.assert_frame_equal(a.signals.decisions, b.signals.decisions, check_exact=True)
    for left, right in ((a.execution, b.execution), (a.buyhold.execution, b.buyhold.execution)):
        for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
            pd.testing.assert_frame_equal(getattr(left, field), getattr(right, field), check_exact=True)
    serial = driver.cache_read(RUN / 'native/center-03.pkl.gz')
    spawn = driver.cache_read(RUN / 'native/preflight-spawn.pkl.gz')
    assert serialize_evaluation_evidence(*serial) == serialize_evaluation_evidence(*spawn)
    assert read(RUN / 'preflight.json')['actual_technical_duplicates'] == 1
    expected_labels = ['BASE'] + ([selection['preferred']] if selection['preferred'] else [])
    assert [item['label'] for item in checks['selected_checks']] == expected_labels
    selfcheck_results = []
    for item in checks['selected_checks']:
        stored = next(row for row in analysis['centers'] if row['label'] == item['label'])
        index = stored['queue_index']
        stress = driver.cache_read(RUN / f'native/fee-stress-{index:02}.pkl.gz')
        fact, ref = authenticated(stress, item['stress_reference'], 'stress_20bp_per_side')
        assert stress[0].strategy == complete[index]['center'][0].strategy
        assert fact.scenario_context.one_way_cost == .002
        request = CandidateAssessmentRequest.from_dict(item['request'])
        original_facts = tuple(build_assessment_evidence(*pair)[0] for pair in
                               (complete[index]['center'], *complete[index]['points'], stress))
        assert request.evidence == original_facts
        assert request.parameter_designs == (complete[index]['design'],)
        assert assess_candidates(request).to_dict() == item['panel']
        public_item = read(EvidenceRef.from_dict(item['reference']).resolve(ROOT))
        assert public_item == {key: value for key, value in item.items() if key != 'reference'}
        selfcheck_results.append({'label': item['label'], 'native_request_and_public_panel': 'PASS',
                                 'stress_ref': ref.to_dict(), 'no_family_correction': request.family_returns is None})
    pressure = len(expected_labels)
    assert state['pressure_successful'] == checks['pressure_successful'] == pressure
    assert state['new_successful_business'] == 262  # This counter is role count, not unique content.
    assert state['technical_duplicates'] == 1
    assert state['evaluation_attempts'] == 262 + 1 + pressure
    output = {'status': 'PASS', 'scope': 'Independent full-native9x33 economics, plans, public references, selection/counts and retained selfchecks',
              'new_account_evaluations_by_audit': 0, 'preparations': 0, 'publications': 0,
              'method_reference': method_ref.to_dict(),
              'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'counts': {'roles': 297, 'unique_configurations': 294, 'old_roles': 35, 'old_unique_native': 33,
                         'new_unique_business': 261, 'new_role_evaluations': 262, 'binding_technical_duplicate': 1,
                         'preflight_technical_duplicate': 1, 'center_fee_pressure': pressure,
                         'actual_new_evaluations': 263+pressure},
              'centers': summaries, 'selection': selection, 'all_role_references': all_roles,
              'duplicate_C0621': 'Two real different plan/request bindings; exact source/parameters/signals/strategy and benchmark economic frames',
              'selfchecks': selfcheck_results,
              'limitations': ['Audit verifies declared finite experiment; does not prove independent out-of-sample validity or future profits.',
                              'Repeated development-pool selection is not fully corrected; intervals are not future assurance.',
                              'Known S013 OHLC/limit exposure retained; economics audit does not certify all historical bar quality.']}
    (WORK / 'independent_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'roles': 297, 'centers': 9, 'new_evaluations_by_audit': 0}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-complete', action='store_true')
    args = parser.parse_args()
    if not args.audit_complete:
        parser.error('--audit-complete is required; wait until native run/analyze/selfchecks are COMPLETE')
    run_audit()
