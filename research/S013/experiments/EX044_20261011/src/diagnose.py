"""Full native66 authentication and complete descriptive one-step contrasts."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'
import importlib.util
import pandas as pd
import numpy as np
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from common import ROOT, SRC, PROTOCOLS, OUTPUT, TRANSPORT, SOURCE_CALLS, context, read, write, cache_read, file_hash
from native_reference import verified_json, load_original_oracle, bound_bars, json_standard
from transition import SignalKind, Feature, trace, validate_parameters, state_dict
from contrasts import compare_same_kind, cross_actual
from probe import fixed_values, diagnose_probe


def frozen_oracle():
    source = ROOT / 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    spec = importlib.util.spec_from_file_location('s013_ex044_frozen_new_oracle', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_check():
    plan = verified_json(read(PROTOCOLS / 'plan_reference.json'))
    assert plan == read(PROTOCOLS / 'plan.json')
    for name, digest in plan['source_files'].items():
        assert file_hash(SRC / name) == digest, name
    for name, digest in plan['external_source_files'].items():
        assert name.startswith('research/S013/') and file_hash(ROOT / name) == digest, name
    return plan


def main():
    plan = source_check()
    assert not OUTPUT.exists(), 'Retain previous output; no silent overwrite'
    identity_audit, original_oracle, old_state_trace, verify_account = load_original_oracle()
    oracle, ctx = frozen_oracle(), context(1)
    prepared = cache_read(TRANSPORT / 'prepared.pkl.gz')
    assert {item['label'] for item in prepared} == {'B0-TIME', 'N0'}
    matrix = read(ROOT / 'research/S013/assets/runs/EX043_20261011/parameter_matrix_v3.json')
    assert matrix['status'] == 'COMPLETE' and len(matrix['rows']) == 64
    centers = read(ROOT / 'research/S013/assets/runs/EX043_20261011/account_references.json')
    native, audits, refs, probes = {}, {}, {}, {}
    benchmark, dates_all, executions_all = None, None, None
    try:
        for transport in prepared:
            label = transport['label']
            kind = SignalKind.ORIGINAL_TIME if label == 'B0-TIME' else SignalKind.MEAN_BEAR_TIME_BELOW_CLOSE
            parameter_plan = transport['plan']
            points = sorted((row for row in matrix['rows'] if row['center'] == label), key=lambda row: row['point_index'])
            assert [row['point_index'] for row in points] == list(range(32))
            center_identity = None
            for item in [None, *points]:
                key = label + '-center' if item is None else item['label']
                bound, result = (transport['center'], transport['result']) if item is None else cache_read(TRANSPORT / (key + '.pkl.gz'))
                reference = centers[label] if item is None else item['reference']
                assert reference == plan['input_accounts'][key]
                formal = verified_json(reference)
                validate_evaluation_evidence(formal)
                assert formal == serialize_evaluation_evidence(bound, result)
                identity = identity_audit(ctx, bound, result, formal)
                funds = verify_account(bound, result)
                assert funds['known_low_error_potential_orders'] == 0
                assert len(result.runs) == 1 and not SOURCE_CALLS
                if benchmark is None:
                    benchmark = result.runs[0].buyhold.execution
                for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
                    pd.testing.assert_frame_equal(getattr(benchmark, name), getattr(result.runs[0].buyhold.execution, name), check_exact=True)
                if item is None:
                    assert bound.strategy.candidate_id == ('C2132' if label == 'B0-TIME' else 'C4900')
                    assert parameter_plan.design.center.content_sha256 == identity['content_sha256']
                    center_identity = identity
                else:
                    assert identity['source_sha256'] == center_identity['source_sha256']
                    assert identity['dependency_sha256'] == center_identity['dependency_sha256']
                    assert bound.strategy.candidate_id == item['candidate_id'] and identity['content_sha256'] == item['content_sha256']
                    assert result.request_hash == item['request_hash'] and result.result_hash == item['result_hash']
                    assert bound.lineage.parameter_binding.point == parameter_plan.design.bind_point(item['point_index'])
                    assert verified_json(bound.lineage.parameter_binding.plan.to_dict()) == parameter_plan.to_dict()
                    derivation = bound.lineage.derivation
                    assert derivation.kind.value == 'PARAMETERS'
                    assert derivation.parent_content_sha256 == center_identity['content_sha256']
                    assert derivation.child.candidate_id == item['candidate_id'] and derivation.child_content_sha256 == item['content_sha256']
                frame, p = result.runs[0].execution.decisions, bound.strategy.payload['parameters']
                rules = validate_parameters(kind, p)
                bars = bound_bars(ctx, bound)
                dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize().as_unit('ns')
                executions = pd.DatetimeIndex(pd.to_datetime(frame.valid_session)).normalize().as_unit('ns')
                assert len(dates) == 1636
                if dates_all is None:
                    dates_all, executions_all = dates, executions
                pd.testing.assert_index_equal(dates, dates_all, check_names=False)
                pd.testing.assert_index_equal(executions, executions_all, check_names=False)
                calendar = oracle._audit_dates(ctx, bound, next(iter(bound.input_bindings.values())), frame, dates, bars)
                if kind == SignalKind.ORIGINAL_TIME:
                    values, _, _ = original_oracle(ctx, bound, frame, p, old_state_trace)
                    raw = tuple(float(value) for value in values.raw_acf)
                    bear, independent = raw, {'original_all_features': 'EXACT_EQUAL', 'original_state': 'EXACT_EQUAL'}
                else:
                    independent = oracle.audit_direction(ctx, bound, frame, p)
                    expected = oracle._reconstruct(bars, dates, p)
                    raw = tuple(float(value) for value in expected.bear_acf_raw)
                    bear = tuple(float(value) for value in expected.bear_acf_centered)
                closes, previous = bars.Close.reindex(dates), bars.Close.shift(1).reindex(dates)
                features = tuple(Feature(str(row.regime), float(closes.iloc[i]), float(previous.iloc[i]),
                    float(row.bull_range_position), float(row.bear_range_position), raw[i], bear[i],
                    float(row.confirmation_score), float(p['confirmation']['threshold']), *rules)
                    for i, row in enumerate(frame.itertuples()))
                own = trace(kind, features, tuple(float(value) for value in frame.target_position),
                            tuple(frame.signal_reason), tuple(dates), tuple(executions))
                if kind != SignalKind.ORIGINAL_TIME:
                    for i, state in enumerate(own.before):
                        assert state.holding == bool(expected.holding_before.iloc[i])
                        assert state.route == expected.route_before.iloc[i] and state.age == expected.age_before.iloc[i]
                        for name in ('last_exit_reason', 'last_exit_route', 'last_exit_category'):
                            assert getattr(state, name) == expected[name].iloc[i]
                    fixed = fixed_values(bars, dates, raw)
                    if p['confirmation']['lookback'] == 120:
                        np.testing.assert_array_equal(fixed, bear)
                    probes[key] = diagnose_probe(own, fixed)
                refs[key] = reference
                audits[key] = {'public_identity': identity, 'native_funds': funds, 'calendar': calendar,
                    'serialized_account': 'EXACT_EQUAL', 'benchmark_ledgers': 'EXACT_EQUAL',
                    'independent_features_states': independent, 'own_pure_transition_rows': len(own.features),
                    'tail_state': state_dict(own.tail_state), 'confirmation_lookback': p['confirmation']['lookback']}
                native[key] = own
                print({'authenticated_native_accounts': len(native), 'key': key}, flush=True)
        assert len(native) == len(audits) == len(refs) == 66 and len(probes) == 33
        assert len({audit['public_identity']['request_hash'] for audit in audits.values()}) == 66
        assert len({EvidenceRef.from_dict(ref).repository_path for ref in refs.values()}) == 66
        same, cross = {}, {}
        for label in ('B0-TIME', 'N0'):
            for i in range(32):
                key = label + f'-P{i:02d}'
                same[key] = compare_same_kind(native[label + '-center'], native[key])
            print({'same_kind_complete': label, 'points': 32}, flush=True)
        for suffix in ('center', *(f'P{i:02d}' for i in range(32))):
            if suffix != 'center':
                index = int(suffix[1:])
                bindings = [transport['plan'].design.bind_point(index) for transport in prepared]
                assert bindings[0].coordinates == bindings[1].coordinates
            cross[suffix] = cross_actual(native['B0-TIME-' + suffix], native['N0-' + suffix])
        assert not SOURCE_CALLS
        output = {'status': 'PASS', 'new_account_evaluations': 0, 'new_account_preparations': 0,
            'method_reference': read(PROTOCOLS / 'method_reference.json'), 'input_accounts': refs, 'audits': audits,
            'same_kind': same, 'cross_actual': cross, 'fixed120_probe': probes,
            'summary': {'unique_native_accounts': 66, 'native_signal_rows': 66 * 1636,
                'same_kind_complete_pairs': 64, 'cross_actual_complete_pairs': 33,
                'fixed120_complete_accounts': 33, 'new_account_evaluations': 0,
                'provider_calls': SOURCE_CALLS, 'cash_replays': 0}, 'limits': plan['limits']}
        write(OUTPUT, json_standard(output))
        print({'diagnosis': 'PASS', **output['summary']}, flush=True)
    except Exception as error:
        assert not OUTPUT.exists()
        write(OUTPUT, {'status': 'FAILED', 'new_account_evaluations': 0, 'input_accounts': refs, 'audits': audits,
            'error': {'type': type(error).__name__, 'message': str(error)},
            'policy': 'Immutable failure; no partial PASS or silent replay'})
        raise


if __name__ == '__main__':
    main()
