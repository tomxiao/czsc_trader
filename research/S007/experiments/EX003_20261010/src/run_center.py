"""Authenticate the historical center and preserve full cost-rerun evidence."""
from hashlib import sha256
import sys
import numpy as np
import pandas as pd
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite
from common import ROOT, PROTOCOLS, RUNS, EXPERIMENT, context, request, write, read, cache_write, cache_read, fingerprint, material
from offline_inputs import supplier


def csv(path):
    return pd.read_csv(path, float_precision='round_trip')


def compare(old, new, label, columns):
    proof = {'table': label, 'old_rows': len(old), 'new_rows': len(new), 'fields': {}}
    if len(old) != len(new):
        raise AssertionError(f'{label}: row count differs')
    for key in columns:
        left = old[key]
        right = new[key]
        if key == 'date' or key.endswith(('_date', '_time')) or key == 'valid_session':
            equal = np.array_equal(pd.to_datetime(left).to_numpy(), pd.to_datetime(right).to_numpy())
        elif pd.api.types.is_numeric_dtype(left):
            left_values = pd.to_numeric(left).to_numpy(float)
            right_values = pd.to_numeric(right).to_numpy(float)
            equal = np.array_equal(left_values, right_values, equal_nan=True)
            proof['fields'][key] = {'exact': bool(equal), 'max_absolute_difference':
                float(np.nanmax(np.abs(left_values-right_values))) if np.isfinite(left_values).any() else 0.}
        else:
            equal = np.array_equal(left.fillna('').astype(str).to_numpy(), right.fillna('').astype(str).to_numpy())
        proof['fields'].setdefault(key, {'exact': bool(equal)})
        # Historical derived ratios were CSV-serialized at less than full binary64
        # precision. Preserve their discrepancy; cash, prices, quantities and dates
        # receive no tolerance. This cannot hide an economic account difference.
        if not equal and key in {'factor_score', 'confirmation_score', 'net_return'}:
            mismatch = proof['fields'][key]['max_absolute_difference']
            if mismatch <= 3e-16 and np.array_equal(left.isna().to_numpy(), right.isna().to_numpy()):
                proof['fields'][key]['qualification'] = 'historical derived-ratio CSV precision; discrepancy preserved'
                continue
        if not equal:
            raise AssertionError(f'{label}: {key}: {proof["fields"][key]}')
    return proof


def main():
    assert (PROTOCOLS/'adapted_plan_reference.json').exists()
    assert read(RUNS/'c2132_center_reproduction.json')['status'] == 'PASS'
    if '--verify-only' in sys.argv:
        from czsc_trader.research_tools import EvidenceRef
        bound, result = cache_read(ROOT/'.tmp/s007-four-metrics/center.pkl.gz')
        ref = EvidenceRef.from_dict(read(RUNS/'center_reference.json'))
        assert read(ref.resolve(ROOT))['result_hash'] == result.result_hash
    else:
        research = context(4, supplier)
        bound = research.evaluation.prepare(request())
        outcome = research.evaluation.evaluate_many((bound,))[0]
        if outcome.status.value != 'SUCCEEDED':
            write(RUNS/'center_technical_failure.json', {'status': outcome.status.value,
                'error': {'code': outcome.error.code, 'message': outcome.error.message}})
            raise AssertionError('S007 center calculation failed: '+outcome.error.message)
        result = outcome.result
        cache_write(ROOT/'.tmp/s007-four-metrics/center.pkl.gz', (bound, result))
        ref = publish_evidence(research, EvaluationEvidenceWrite(
            EXPERIMENT, 'four-diagnostics-s007-center-cost-pair', bound, result))
        write(RUNS/'center_reference.json', ref.to_dict())
    baseline = next(x for x in result.runs if x.scenario_id == 'baseline')
    # Save the raw regenerated tables before any equality check; mismatches remain auditable.
    for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
        getattr(baseline.execution, name).to_csv(RUNS/(name+'.csv'), index=False)
    baseline.buyhold.account_daily.to_csv(RUNS/'buyhold_account_daily.csv', index=False)
    previous = ROOT/'experiments/S007/20260915_S007_EX31/artifacts'
    ledgers = {}
    for name in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
        old, new = csv(previous/(name+'.csv')), getattr(baseline.execution, name)
        if name == 'decisions':
            old = old.loc[pd.to_datetime(old['valid_session']).between('2021-01-05', '2026-09-02')].reset_index(drop=True)
            new = baseline.signals.decisions
        excluded = {'decision_id', 'order_id', 'fill_id', 'cycle_id', 'candidate_id'}
        common = [x for x in old.columns if x in new.columns and x not in excluded]
        ledgers[name] = {'common_columns': common, 'old_only': sorted(set(old)-set(new)),
                         'new_only': sorted(set(new)-set(old))}
        ledgers[name]['comparison'] = compare(old, new, name, common)
    behavior = baseline.execution.account_daily['target_position'].astype('int8').to_numpy()
    # EX31 hashed the calculation calendar including the initial cash-only
    # 2021-01-04 session; the account window itself starts on 2021-01-05.
    behavior_hash = sha256(np.r_[np.int8(0), behavior].astype('int8').tobytes()).hexdigest()
    assert behavior_hash == 'd6dafcf9f65c2ea0be11f7c127a2a6e4acf0aa4a4e767dcf6fc3e21042ff26a3'
    old_bh_path = ROOT/'experiments/S007/20260915_S007_EX32/artifacts/buyhold_account_daily.csv'
    old_bh, new_bh = csv(old_bh_path), baseline.buyhold.account_daily
    assert np.array_equal(pd.to_datetime(old_bh['date']), pd.to_datetime(new_bh['date']))
    assert np.array_equal(old_bh['close'].to_numpy(), new_bh['close'].to_numpy())
    first_open = float(result.execution_data.execution_daily.iloc[1]['open'])
    fractional_quantity = bound.initial_cash/(first_open*1.001)
    assert np.array_equal(old_bh['equity'].to_numpy(), old_bh['close'].to_numpy()*fractional_quantity)
    bh = {'status': 'LEGACY_BENCHMARK_NOT_EXECUTABLE_IN_100_SHARE_LOTS',
          'old_fractional_quantity': fractional_quantity,
          'new_executable_quantity': float(new_bh['quantity'].iloc[0]),
          'new_remaining_cash': float(new_bh['cash'].iloc[0]),
          'dates_and_prices_exact': True, 'old_equity_exactly_equals_fractional_quantity_times_close': True,
          'maximum_equity_difference': float(np.max(np.abs(old_bh['equity'].to_numpy()-new_bh['equity'].to_numpy()))),
          'main_table_decision': 'Pending human confirmation; both values preserved. Prospective TDR protocol used NextOpenBuyHold(100).'}
    summary = read(previous/'tdr_replay_summary.json')
    assert baseline.observation.closed_trades == summary['metrics']['closed_trades'] == 139
    assert baseline.observation.total_return == summary['metrics']['return']
    proof = {'status': 'PASS', 'evidence': ref.to_dict(), 'source': read(PROTOCOLS/'adapted_plan.json')['center'],
             'behavior_sha256': behavior_hash, 'comparison': ledgers, 'benchmark': bh,
             'source_files': [fingerprint(previous/(x+'.csv')) for x in ledgers]+[fingerprint(old_bh_path)],
             'account_metrics': [x.observation.to_dict() for x in result.runs],
             'execution_data_identity': result.data_identity,
             'qualification': 'Original executed signals and economic fields checked; cash/fill prices/quantities/account exact. Derived score/net-return CSV precision differences explicitly listed. Original terminal unexecuted signal excluded only from signal comparison.'}
    write(RUNS/'center_reproduction.json', proof)
    write(PROTOCOLS/'center_proof_reference.json', material('four-diagnostics-s007-center-reproduction-proof',
        RUNS/'center_reproduction.json').to_dict())
    print({'S007': 'PASS', 'metrics': proof['account_metrics']}, flush=True)


if __name__ == '__main__':
    main()
