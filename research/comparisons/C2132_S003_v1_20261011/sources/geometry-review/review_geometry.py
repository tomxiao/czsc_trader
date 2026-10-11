"""Pure S003 parameter geometry; only seed/calendar dates are inspected."""
from __future__ import annotations

import ast
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from math import isfinite, sqrt
from pathlib import Path
import sys

import pandas as pd
from strategy_evaluator import (
    AssessmentCandidate, ParameterCoordinate, ParameterCoordinateKind,
    ParameterDesignRequest, ParameterDesignStatus, ParameterPerturbationProtocol,
    ParameterSpace, build_parameter_perturbation_design,
)
from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'strategies/S003/releases/v1/runtime/strategy_runtime'
SEED = RUNTIME / 'resources/s003_v1_seed.csv.gz'
CALENDAR_CACHE = ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz'
CALENDAR_HELPER = ROOT / 'research/S013/experiments/EX058_20261011/src/common.py'
COORDINATES = (
    ParameterCoordinate('threshold_lookback_sessions', 60., 1., 252.,
                        ParameterCoordinateKind.INTEGER),
    ParameterCoordinate('threshold_quantile', .8, 0., 1.,
                        ParameterCoordinateKind.CONTINUOUS),
)
MAPPING = {
    'ordered_paths': ['parameters.rule.feature.threshold_lookback_sessions',
                      'parameters.rule.feature.threshold_quantile'],
    'types': ['int', 'float'],
    'other_fields': 'EXACT_UNCHANGED',
    'domains': 'PROSPECTIVE_FINITE_DIAGNOSTIC_DOMAIN_NOT_HISTORICAL_SEARCH_DOMAIN',
}
FEASIBILITY = {'integer_window': [1, 252], 'quantile': [0., 1.],
               'finite_only': True, 'return_filters': False}


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def feasible(point):
    if type(point) is not tuple or len(point) != 2:
        return False
    if any(type(x) is not float or not isfinite(x) for x in point):
        return False
    length, quantile = point
    return bool(length.is_integer() and 1 <= length <= 252 and 0 <= quantile <= 1)


def mapped(payload, point):
    if not feasible(point):
        raise ValueError('invalid prospective S003 coordinate tuple')
    result = deepcopy(payload)
    feature = result['parameters']['rule']['feature']
    feature['threshold_lookback_sessions'] = int(point[0])
    feature['threshold_quantile'] = float(point[1])
    return result


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                     allow_nan=False) + '\n', encoding='utf-8')


def calendar_dates_only():
    # Explicit parent authorization is limited to this cache's calendar dates.
    # Do not inspect result/run/account fields or market prices.
    sys.path.insert(0, str(CALENDAR_HELPER.parent))
    common = importlib.import_module('common')
    if Path(common.__file__).resolve() != CALENDAR_HELPER.resolve():
        raise ValueError('calendar decoder source differs')
    bound, unused_result = common.cache_read(CALENDAR_CACHE)
    dates = pd.DatetimeIndex(bound.input_bindings['full'].plan.calendar_dates).normalize()
    del bound, unused_result
    if dates.empty or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError('invalid authenticated-cache calendar ordering')
    return dates


def focused(payload, design):
    checks = []
    refusals = []
    assert design.protocol == ParameterPerturbationProtocol()
    points = [x.coordinates for x in design.points]
    assert len(points) == len(set(points)) == 32
    checks.append('32_unique_public_SE_points')
    for point in points:
        assert feasible(point)
        assert abs(sqrt(((point[0]-60.)/251.)**2 + (point[1]-.8)**2)-.05) <= 1e-10
        child = mapped(payload, point)
        assert type(child['parameters']['rule']['feature']['threshold_lookback_sessions']) is int
        assert type(child['parameters']['rule']['feature']['threshold_quantile']) is float
        expected = deepcopy(child)
        expected['parameters']['rule']['feature'].update(
            threshold_lookback_sessions=60, threshold_quantile=.8)
        assert expected == payload
    checks.extend(['all_radius_exact', 'typed_mapping_only_two_fields', 'all_fixed_structure_exact'])
    for bad in ((True, .8), (60., float('nan')), (60.5, .8), (0., .8),
                (253., .8), (60., -.01), (60., 1.01), [60., .8]):
        try:
            mapped(payload, bad)
        except ValueError:
            refusals.append(repr(bad))
        else:
            raise AssertionError('invalid coordinates accepted')
    assert feasible((1., 0.)) and feasible((252., 1.))
    checks.append('full_domain_endpoints_legal_no_shrink')
    # Compile only the frozen pure function; no native input preparation occurs.
    source = (RUNTIME / 'strategies/s003_v1.py').read_text(encoding='utf-8')
    node = next(x for x in ast.parse(source).body
                if isinstance(x, ast.FunctionDef) and x.name == '_decision_history')
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {'pd': pd, 'Mapping': dict, 'Any': object}
    exec(compile(ast.fix_missing_locations(module), 'frozen-pure-decision', 'exec'), namespace)
    decision = namespace['_decision_history']
    history = pd.DataFrame({'moneyflow_breadth': [.1, .2, .3, .4, .1, .9]},
                           index=pd.date_range('2021-01-04', periods=6))
    spec = {'threshold_excludes_current_session': True,
            'threshold_lookback_sessions': 3, 'threshold_quantile': .8}
    base = decision(history, spec)
    assert base['threshold'].iloc[:3].isna().all()
    assert base['threshold'].iloc[3] == pd.Series([.1, .2, .3]).quantile(.8)
    assert base['threshold'].iloc[3] != decision(history, {**spec,
                            'threshold_quantile': .2})['threshold'].iloc[3]
    assert base['threshold'].iloc[3] != decision(history, {**spec,
                            'threshold_lookback_sessions': 2})['threshold'].iloc[3]
    mutated = history.copy()
    mutated.iloc[4:, 0] = [999., -999.]
    pd.testing.assert_frame_equal(base.iloc[:4], decision(mutated, spec).iloc[:4], check_exact=True)
    equality = history.copy()
    equality.iloc[3, 0] = base['threshold'].iloc[3]
    assert bool(decision(equality, spec)['signal_active'].iloc[3])
    checks.extend(['native_L_and_q_both_active', 'prior_L_only_no_current_or_future',
                   'native_threshold_equality_enters', 'insufficient_history_not_filled'])
    return {'status': 'PURE_PASS', 'checks': checks, 'checks_count': len(checks),
            'refusals': refusals, 'refusal_count': len(refusals), 'financial_calls': [],
            'new_account_evaluations': 0, 'new_account_preparations': 0}


def main():
    version_path = ROOT / 'strategies/S003/versions/v1.json'
    version = json.loads(version_path.read_text(encoding='utf-8-sig'))
    payload = version['strategy_payload']
    release_dir = RUNTIME.parents[1]
    binding = json.loads((release_dir / 'runtime_binding.json').read_text(encoding='utf-8-sig'))
    manifest = json.loads((release_dir / 'release_manifest.json').read_text(encoding='utf-8-sig'))
    assert manifest['strategy_version_hash'] == binding['release_hash'] == version['release_hash']
    assert manifest['strategy_version_id'] == binding['release_id'] == version['release_id']
    for path, expected in manifest['files'].items():
        assert sha256((release_dir / path).read_bytes()).hexdigest() == expected
    actual_source = implementation_sha256(tuple(payload['runtime']['source_files']), source_root=RUNTIME)
    assert actual_source == payload['runtime']['source_sha256'] == binding['implementation_sha256']
    candidate = StrategyCandidate('S003', 'C0001', payload, RUNTIME)
    identity = StrategyRuntime().identify(candidate, dependencies=())
    # Identity here is a pure proof center, not a registration/evaluation receipt.
    request = ParameterDesignRequest(
        AssessmentCandidate(candidate.reference_id, identity.content_sha256),
        ParameterPerturbationProtocol(), ParameterSpace(COORDINATES, digest(MAPPING), digest(FEASIBILITY)))
    generated = build_parameter_perturbation_design(request, feasibility=feasible)
    assert generated.status is ParameterDesignStatus.COMPLETE
    design = generated.design
    proof = focused(payload, design)
    proof['checks'].append('frozen_release_binding_manifest_all_file_hashes_exact')
    proof['checks_count'] = len(proof['checks'])
    lengths = [int(p.coordinates[0]) for p in design.points]
    maximum = max(lengths)
    seed_dates = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(SEED, usecols=['Date'])['Date'])).normalize()
    assert not seed_dates.has_duplicates and seed_dates.is_monotonic_increasing
    dates = calendar_dates_only()
    assert seed_dates.isin(dates).all()
    lower = pd.Timestamp('2021-04-15')
    eligible = []
    for execution_day in dates[dates >= lower]:
        prior = dates[dates < execution_day]
        if len(prior) < maximum+1:
            continue
        history = prior[-(maximum+1):]
        if history.isin(seed_dates).all():
            eligible.append((execution_day, history))
            break
    if not eligible:
        raise ValueError('no common execution start satisfies full 32-point history')
    first, needed = eligible[0]
    earlier = dates[dates < lower]
    earlier_needed = earlier[-(maximum+1):]
    coverage = {
        'only_date_columns_inspected': True, 'seed_date_count': len(seed_dates),
        'seed_first': str(seed_dates[0].date()), 'seed_last': str(seed_dates[-1].date()),
        'calendar_first': str(dates[0].date()), 'calendar_last': str(dates[-1].date()),
        'requested_lower_bound': str(lower.date()), 'maximum_actual_L': maximum,
        'required_signal_history_including_T': maximum+1,
        'lower_bound_coverage': bool(earlier_needed.isin(seed_dates).all()),
        'lower_bound_missing_dates': [str(x.date()) for x in earlier_needed.difference(seed_dates)],
        'recommended_common_first_execution': str(first.date()),
        'first_signal': str(needed[-1].date()), 'earliest_required_seed_date': str(needed[0].date()),
        'all_32_history_covered': True,
        'choice_rule': 'FIRST_SSE_EXECUTION_DATE_GE_2021_04_15_WITH_MAX_L_PLUS_1_COMPLETE_SEED_DATES',
        'no_return_values_inspected': True,
    }
    sources = [version_path, ROOT / 'strategies/S003/releases/v1/runtime_binding.json',
               ROOT / 'strategies/S003/releases/v1/release_manifest.json',
               ROOT / 'experiments/S003/20260911_S003_EX44/artifacts/protocol.json',
               ROOT / 'experiments/S003/20260911_S003_EX46/artifacts/protocol.json',
               ROOT / 'experiments/S003/20260911_S003_EX52/artifacts/protocol.json',
               ROOT / 'experiments/S003/20260911_S003_EX53/candidate_payload.json',
               ROOT / 'experiments/S003/20260911_S003_EX56/candidate_payload.json',
               ROOT / 'research/registrations/S003/registration_origin.json',
               ROOT / 'src/czsc_trader/research_tools/evaluation.py',
               ROOT / 'src/czsc_trader/research_tools/parameter_evaluation.py',
               ROOT / 'src/czsc_trader/backtesting/srt_bridge.py',
               ROOT / 'src/czsc_trader/backtesting/audit_adapter.py',
               ROOT / 'packages/strategy_runtime/src/strategy_runtime/pricing.py',
               ROOT / 'packages/strategy_evaluator/src/strategy_evaluator/research_models.py',
               ROOT / 'packages/strategy_evaluator/src/strategy_evaluator/parameter_perturbation.py',
               CALENDAR_HELPER, *[RUNTIME / p for p in payload['runtime']['source_files']],
               Path(__file__).resolve()]
    inventory = {
        'active_signal_coordinates': [x.to_dict() for x in COORDINATES],
        'fixed_numeric_structure': {'core_fraction': .5, 'event_fraction': .5,
                                   'lot_size': 100, 'maximum_events_per_day': 1},
        'fixed_data_quality': {'minimum_observed_weight_ratio': .95,
                              'applies_only_incremental_after_seed_cutoff': True,
                              'historical_weight_snapshot_staleness_days': 370},
        'execution_effectiveness_note': 'core_fraction is read; event quantity is capped by core sellable inventory and available cash; event_fraction/maximum_events_per_day remain fixed declared structure, not independent signal coordinates',
        'historical_fee': {'one_way_cost': .00012, 'unified_via_EvaluationCost': True},
        'fixed_rules': ['positive_member_net_moneyflow_gt_0', 'point_in_time_index_weights',
                        'prior_L_threshold_excludes_current', 'linear_quantile',
                        'breadth_ge_threshold', 'OPEN_entry_11:30_CLOSE_exit',
                        'T_PLUS_ONE_inventory_rotation', 'long_only_510500.SH'],
        'technical_domains': {'L': 'positive integer; no finite upper bound explicitly declared in original source',
                              'q': 'closed mathematical interval [0,1]'},
        'old_neighbor_evidence': {'L': 60, 'q': [.75, .8, .85],
                                  'is_5percent_full_domain_32point_design': False},
    }
    api = {
        'supports_intraday_overlay': True, 'supports_HFQ_RESEARCH': True,
        'explicit_initial_cash': True, 'explicit_evaluation_cost_override': True,
        'frozen_payload_as_modern_StrategyCandidate': True,
        'native_public_entrypoints': ['context.evaluation.prepare(EvaluationRequest)',
                                     'context.evaluation.evaluate(bound_request)',
                                     'context.evaluation.evaluate_many(tuple_of_requests)'],
        'binding_fields': ['runtime.source_files', 'runtime.source_sha256', 'StrategyCandidate.source_root',
                           'EvaluationRequest.dependencies', 'EvaluationRequest.input_bindings'],
        'price_basis': 'ExecutionPriceBasis.HFQ_RESEARCH',
        'fees': 'EvaluationCost(scenario_id, one_way_cost, FORMAL) overrides effective execution cost without editing source',
        'benchmark': 'explicit EvaluationBenchmark, same funds/fees/HFQ/window; preserve S003 overlay structure',
        'requires_5minute_intraday_execution_data': True,
        'formal_parameter_flow': ['declare mapping/feasibility/geometry before accounts',
                                  'prepare center/child inputs', 'ParameterEvaluationPlan.create',
                                  'publish exact ParameterEvaluationPlan', 'bind_point + PARAMETERS lineage',
                                  'then evaluate planned accounts'],
        'registry_origin': 'LEGACY_BACKFILL / PROMOTED_CLOSED / NO_RETROACTIVE_OPEN_CREDENTIAL',
        'current_ResearchContext_availability': 'parent reports modern S003 context success; no new lifecycle action here',
    }
    review = {
        'status': 'READONLY_GEOMETRY_READY', 'research_symbol': '510500.SH',
        'mapping': MAPPING, 'feasibility': FEASIBILITY, 'inventory': inventory, 'public_api': api,
        'geometry': {'dimension': 2, 'radius': .05, 'point_count': 32, 'seed': 13,
                     'normalization': 'sqrt(((L-60)/251)^2 + (q-.8)^2)=.05',
                     'integer_rounding': 'HALF_EVEN', 'actual_min_L': min(lengths),
                     'actual_max_L': maximum, 'attempts': design.attempts,
                     'design_sha256': design.sha256, 'method_sha256': design.protocol.method_sha256},
        'date_coverage': coverage, 'release_hash': version['release_hash'],
        'implementation_sha256': actual_source,
        'frozen_closure_audit': {'binding_matches_version': True,
                                'manifest_matches_version': True,
                                'all_manifest_file_hashes_exact': True},
        'proof_center_identity': {'candidate_id': candidate.reference_id,
                                  'content_sha256': identity.content_sha256,
                                  'dependencies': [], 'formal_registration_or_evaluation': False},
        'source_files': {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in sources},
        'calendar_cache_sha256': sha256(CALENDAR_CACHE.read_bytes()).hexdigest(),
        'new_account_preparations': 0, 'new_account_evaluations': 0, 'provider_calls': [],
        'limits': ['L[1,252] is a prospective finite diagnostic domain, not a recovered original search domain',
                   'two and thirteen dimensions share a normalized method, not coordinates or equivalent economic risk',
                   'same seed does not imply matched parameter points across different dimensions',
                   'no changes to center parameters, execution structure, frozen source or platform',
                   'no performance or parameter optimization performed',
                   'all complete-account metrics must be recomputed under unified context; historical returns are not comparable',
                   'coverage proof is only dates; execution-data availability and positive finite feature values remain preconditions',
                   'frozen source can turn a NaN warmup threshold into inactive signal; external precheck must assert every requested threshold finite and full L-prior history',
                   'proof identity with empty dependencies must be rebuilt for formal request dependencies/candidate identity'],
    }
    write('se_design.json', generated.to_dict())
    write('mapping.json', MAPPING)
    write('feasibility.json', FEASIBILITY)
    write('focused.json', proof)
    write('review.json', review)
    print(json.dumps({'status': review['status'], 'min_L': min(lengths), 'max_L': maximum,
                      'first_execution': coverage['recommended_common_first_execution'],
                      'checks': proof['checks_count'], 'refusals': proof['refusal_count'],
                      'financial_calls': [], 'review_sha256': sha256((OUT/'review.json').read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
