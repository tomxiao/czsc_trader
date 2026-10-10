"""Authenticate37 retained native accounts and describe signal exit-anchor contexts."""
from technical_validation import technical_check
import importlib.util
import pandas as pd
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from common import ROOT, SRC, PROTOCOLS, SOURCE_CALLS, context, read, write, cache_read, file_hash
from native_reference import (verified_json, load_original_oracle, enrich_original,
                              reconstruct_extra, bound_bars, direction_fields, validate_days, json_standard)
from anchor_diagnosis_v2 import diagnose_account

OUTPUT = ROOT / '.tmp/ex042-diagnosis/anchors_v2.json'


def declared_method():
    reference = read(PROTOCOLS / 'method_reference.json')
    ref = EvidenceRef.from_dict(reference)
    assert ref.experiment.experiment_id == SRC.parent.name == 'EX042_20261011'
    method = verified_json(reference)
    assert method['unique_native_accounts'] == 37 and method['new_account_evaluations'] == 0
    assert set(method['inputs']) == {'original33', 'mean_center', 'body_center', 'time_close', 'time_body'}
    for name, digest in method['source_files'].items():
        assert file_hash(SRC / name) == digest
    for name, digest in method['external_source_files'].items():
        assert name.startswith('research/S013/') and file_hash(ROOT / name) == digest
    return reference, method


def load_reentry_oracle():
    source = ROOT / 'research/S013/experiments/EX041_20261011/src/direction_oracle_v2.py'
    spec = importlib.util.spec_from_file_location('s013_ex042_frozen_reentry_reference', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enrich_reentry(ctx, bound, frame, oracle):
    p = bound.strategy.payload['parameters']
    audit = oracle.audit_direction(ctx, bound, frame, p)
    assert audit['status'] == 'PASS'
    bars = bound_bars(ctx, bound)
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
    expected = oracle._reconstruct(bars, dates, p)
    names = {'regime': 'raw_route', 'confirmation_score': 'score', 'confirmation_pass': 'score_pass',
             'confirmation_opportunity': 'opportunity', 'target_position': 'target',
             'entry_signal_close': 'signal_close', 'entry_signal_open': 'signal_open',
             'previous_signal_close': 'previous_signal_close'}
    values = expected.rename(columns=names).copy()
    values['entry'] = values.signal_reason.eq('entry')
    values['threshold'] = p['confirmation']['threshold']
    values['valid_session'] = pd.to_datetime(frame.valid_session).to_numpy()
    for name, value in direction_fields(values.signal_close, values.signal_open, values.previous_signal_close).items():
        values[name] = value
    return values, audit


def main():
    technical_check()
    reference, method = declared_method()
    assert not OUTPUT.exists(), 'Retain previous output; no silent overwrite'
    identity_audit, original_oracle, state_trace, verify_account = load_original_oracle()
    reentry_oracle = load_reentry_oracle()
    ctx = context(1)
    refs, audits, accounts = {}, {}, {}
    try:
        prior = verified_json(method['inputs']['original33'])
        expected_refs = prior['input_accounts']
        matrix = read(ROOT / 'research/S013/assets/runs/EX015_20261011/parameter_matrix.json')
        points = sorted((row for row in matrix['rows'] if row['center'] == 'B0-TIME'), key=lambda row: row['point_index'])
        assert len(points) == 32 and [row['point_index'] for row in points] == list(range(32))
        assert set(expected_refs) == {'center', *(row['label'] for row in points)}
        transport = next(row for row in cache_read(ROOT / '.tmp/s013-mechanism-EX015/parameters/prepared.pkl.gz') if row['label'] == 'B0-TIME')
        parameter_plan = transport['plan']
        benchmark = transport['result'].runs[0].buyhold.execution
        center_identity = None

        def authenticate(label, bound, result, account_reference):
            formal = verified_json(account_reference)
            validate_evaluation_evidence(formal)
            assert formal == serialize_evaluation_evidence(bound, result)
            identity = identity_audit(ctx, bound, result, formal)
            audit = verify_account(bound, result)
            assert audit['known_low_error_potential_orders'] == 0
            assert len(result.runs) == 1 and not SOURCE_CALLS
            for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
                pd.testing.assert_frame_equal(getattr(benchmark, name), getattr(result.runs[0].buyhold.execution, name), check_exact=True)
            frame = result.runs[0].execution.decisions
            dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
            binding = next(iter(bound.input_bindings.values()))
            calendar = reentry_oracle._audit_dates(ctx, bound, binding, frame, dates, bound_bars(ctx, bound))
            assert calendar['exact_signal_execute_pairs'] == 1636
            refs[label] = account_reference
            audits[label] = {'public_identity': identity, 'full_native_account': audit,
                             'serialized_account': 'EXACT_EQUAL', 'benchmark_ledgers': 'EXACT_EQUAL',
                             'calendar': calendar}
            return identity

        def save(label, bound, result, values, population, point=None):
            dates = pd.DatetimeIndex(pd.to_datetime(result.runs[0].execution.decisions.signal_date)).normalize()
            validate_days(values, dates)
            assert len(values) == 1636
            diagnostic = diagnose_account(values, result.runs[0].execution)
            assert len(diagnostic['all_native_days']) == 1636
            accounts[label] = {'candidate_id': bound.strategy.candidate_id,
                               'content_sha256': result.runs[0].identity.content_sha256,
                               'population': population, 'point_index': point,
                               'native_signal_days': len(values), **diagnostic}

        for item in [None, *points]:
            if item is None:
                label, bound, result = 'center', transport['center'], transport['result']
            else:
                label = item['label']
                bound, result = cache_read(ROOT / '.tmp/s013-mechanism-EX015/parameters' / (label + '.pkl.gz'))
                assert expected_refs[label] == item['reference']
            identity = authenticate(label, bound, result, expected_refs[label])
            if item is None:
                assert bound.strategy.candidate_id == 'C2132'
                assert parameter_plan.design.center.content_sha256 == identity['content_sha256']
                center_identity = identity
            else:
                assert identity['source_sha256'] == center_identity['source_sha256']
                assert identity['dependency_sha256'] == center_identity['dependency_sha256']
                assert bound.strategy.candidate_id == item['candidate_id'] and identity['content_sha256'] == item['content_sha256']
                assert result.request_hash == item['request_hash'] and result.result_hash == item['result_hash']
                assert bound.lineage.parameter_binding.point == parameter_plan.design.bind_point(item['point_index'])
                plan_ref = bound.lineage.parameter_binding.plan
                assert plan_ref.experiment.experiment_id == 'EX015_20261011'
                assert verified_json(plan_ref.to_dict()) == parameter_plan.to_dict()
                derivation = bound.lineage.derivation
                assert derivation.kind.value == 'PARAMETERS'
                assert derivation.parent.candidate_id == 'C2132' and derivation.parent_content_sha256 == center_identity['content_sha256']
                assert derivation.child.candidate_id == item['candidate_id'] and derivation.child_content_sha256 == item['content_sha256']
            frame = result.runs[0].execution.decisions
            values, before, _ = original_oracle(ctx, bound, frame, bound.strategy.payload['parameters'], state_trace)
            values = enrich_original(ctx, bound, frame, values, before)
            save(label, bound, result, values, 'original33_dependent', None if item is None else item['point_index'])
            print({'authenticated_original_accounts': len(accounts)}, flush=True)

        for label, experiment, identifier, is_body, key in (
                ('MEAN', 'EX028_20261011', 'C8701', False, 'mean_center'),
                ('BODY', 'EX029_20261011', 'C8481', True, 'body_center')):
            account_reference = method['inputs'][key]
            assert account_reference == read(ROOT / f'research/S013/assets/runs/{experiment}/account_references.json')['N1']
            config = next(row for row in read(ROOT / f'research/S013/experiments/{experiment}/protocols/plan.json')['configurations'] if row['label'] == 'N1')
            bound, result = cache_read(ROOT / '.tmp' / ('s013-mechanism-' + experiment[:5]) / 'N1.pkl.gz')
            assert bound.strategy.candidate_id == identifier == config['candidate_id']
            assert json_standard(dict(bound.strategy.payload)) == config['payload']
            identity = authenticate(label, bound, result, account_reference)
            assert identity['content_sha256'] == config['content_sha256']
            values = reconstruct_extra(ctx, bound, result.runs[0].execution.decisions, bound.strategy.payload['parameters'], is_body)
            save(label, bound, result, values, 'additional_existing_center')

        for label, native_label, key in (('TIME_CLOSE', 'N0', 'time_close'), ('TIME_BODY', 'N1', 'time_body')):
            experiment = 'EX041_20261011'
            account_reference = method['inputs'][key]
            assert account_reference == read(ROOT / f'research/S013/assets/runs/{experiment}/account_references.json')[native_label]
            config = next(row for row in read(ROOT / f'research/S013/experiments/{experiment}/protocols/plan.json')['configurations'] if row['label'] == native_label)
            bound, result = cache_read(ROOT / '.tmp/s013-mechanism-EX041' / (native_label + '.pkl.gz'))
            assert bound.strategy.candidate_id == config['candidate_id']
            assert json_standard(dict(bound.strategy.payload)) == config['payload']
            identity = authenticate(label, bound, result, account_reference)
            assert identity['content_sha256'] == config['content_sha256']
            values, audit = enrich_reentry(ctx, bound, result.runs[0].execution.decisions, reentry_oracle)
            audits[label]['reentry_oracle'] = audit
            save(label, bound, result, values, 'additional_existing_center')

        assert len(refs) == len(accounts) == len(audits) == 37
        assert len({value['public_identity']['request_hash'] for value in audits.values()}) == 37
        assert len({EvidenceRef.from_dict(ref).repository_path for ref in refs.values()}) == 37
        assert not SOURCE_CALLS
        output = {'status': 'PASS', 'new_account_evaluations': 0, 'input_accounts': refs,
                  'method_reference': reference, 'technical_correction_reference': read(PROTOCOLS / 'technical_correction_reference.json'),
                  'accounts': accounts, 'audits': audits,
                  'summary': {'unique_native_accounts': 37, 'original_dependent_accounts': 33,
                              'original_parameter_points': 32, 'additional_existing_centers': 4,
                              'native_signal_rows': 37 * 1636, 'provider_calls': list(SOURCE_CALLS),
                              'cash_replays': 0}, 'limits': method['limits']}
        write(OUTPUT, json_standard(output))
        print({'anchor_diagnosis': 'PASS', 'native_accounts': 37, 'new_account_evaluations': 0}, flush=True)
    except Exception as error:
        assert not OUTPUT.exists()
        write(OUTPUT, json_standard({'status': 'FAILED', 'new_account_evaluations': 0,
              'input_accounts': refs, 'audits': audits, 'method_reference': reference,
              'summary': {'authenticated_accounts': len(refs), 'provider_calls': list(SOURCE_CALLS)},
              'error': {'type': type(error).__name__, 'message': str(error)},
              'policy': 'Retain failure; no replacement, provider fallback, partial PASS or automatic retry.'}))
        raise


if __name__ == '__main__':
    main()
