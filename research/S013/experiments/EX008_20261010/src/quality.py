"""Audit actual published orders against the five preserved S013 anomalies."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from math import isclose
from multiprocessing import get_context
from os import environ

import pandas as pd

from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from common import ROOT, RUNS, PROTOCOLS, read, write, source, centers, center_cache, cache_read


def authenticated(ref):
    assert ref.experiment.strategy_id == 'S013', ref.to_dict()
    path = ref.resolve(ROOT)
    assert sha256(path.read_bytes()).hexdigest() == ref.sha256, ref.to_dict()
    return read(path)


def anomaly_values(data, original):
    """Check the same dated raw and normalized values, without repairing inputs."""
    daily = data.execution_daily.copy()
    raw = data.raw_execution_daily.copy()
    minutes = data.execution_intraday.copy()
    for frame in (daily, raw, minutes):
        frame['session'] = pd.to_datetime(frame['dt']).dt.strftime('%Y-%m-%d')
    dates = original['high_error_dates'] + [original['low_error']['date']]
    actual = []
    for day in dates:
        own = daily.loc[daily.session.eq(day)]
        unadjusted = raw.loc[raw.session.eq(day)]
        intraday = minutes.loc[minutes.session.eq(day)]
        assert len(own) == len(unadjusted) == 1 and not intraday.empty, day
        own, unadjusted = own.iloc[0], unadjusted.iloc[0]
        scale = float(own.close / unadjusted.close)
        row = {
            'date': day, 'price_scale': scale,
            'raw_daily_low': float(unadjusted.low),
            'normalized_daily_low': float(own.low),
            'normalized_intraday_minimum': float(intraday.low.min()),
            'raw_intraday_minimum': float(intraday.low.min() / scale),
            'raw_daily_high': float(unadjusted.high),
            'normalized_daily_high': float(own.high),
            'normalized_intraday_maximum': float(intraday.high.max()),
            'raw_intraday_maximum': float(intraday.high.max() / scale),
        }
        if day in original['high_error_dates']:
            assert not isclose(row['normalized_daily_high'],
                               row['normalized_intraday_maximum'], rel_tol=0., abs_tol=1e-9), day
        else:
            expected = original['low_error']
            for name in ('raw_daily_low', 'raw_intraday_minimum', 'price_scale'):
                assert isclose(row[name], expected[name], rel_tol=0., abs_tol=1e-9), (day, name)
            assert isclose(row['normalized_daily_low'], expected['normalized_lower'],
                           rel_tol=0., abs_tol=1e-9)
            assert isclose(row['normalized_intraday_minimum'], expected['normalized_upper'],
                           rel_tol=0., abs_tol=1e-9)
        actual.append(row)
    return actual


def inspect_published(task):
    """A spawned worker authenticates one S013 account and returns small facts."""
    ref = EvidenceRef.from_dict(task['reference'])
    category, candidate_id = task['category'], task['candidate_id']
    value = authenticated(ref)
    validate_evaluation_evidence(value)
    contract = value['request_identity']
    assert value['data_identity'] == contract['data_identity'] == task['data_identity']
    assert contract['symbol'] == '510500.SH' and contract['asset_type'] == 'etf'
    assert contract['data_cutoff'] == '2026-09-30'
    assert contract['pricing'] == task['pricing']
    assert value['execution_mode'] == 'FULL'
    evidence = {(item['window_id'], item['scenario_id']): item
                for item in value['assessment_evidence']}
    assert len(evidence) == len(value['runs'])
    source_record = {'candidate_id': candidate_id, 'category': category,
                     'reference': ref.to_dict(), 'request_hash': value['request_hash'],
                     'result_hash': value['result_hash'], 'data_identity': value['data_identity']}
    coordinates, orders = [], []
    low = task['low_error']
    affected = set(task['high_error_dates']) | {low['date']}
    for run in value['runs']:
        assert run['candidate_id'] == candidate_id
        key = (run['window_id'], run['scenario_id'])
        evaluation_id = evidence[key]['evaluation_id']
        coordinates.append({'candidate_id': candidate_id, 'category': category,
                            'window_id': run['window_id'], 'scenario_id': run['scenario_id'],
                            'evaluation_id': evaluation_id})
        for order in run['ledgers']['orders']['data']:
            assert (order['side'], order['order_type']) in {('BUY', 'LIMIT'), ('SELL', 'MARKET')}
            day = order['execution_date'][:10]
            if day not in affected:
                continue
            potential = (day == low['date'] and order['side'] == 'BUY'
                         and order['order_type'] == 'LIMIT' and order['status'] == 'UNFILLED'
                         and low['normalized_lower'] < float(order['limit_price']) <= low['normalized_upper'])
            orders.append({'candidate_id': candidate_id, 'category': category,
                           'window_id': run['window_id'], 'scenario_id': run['scenario_id'],
                           'evaluation_id': evaluation_id, 'date': day,
                           'side': order['side'], 'order_type': order['order_type'],
                           'status': order['status'], 'limit_price': order['limit_price'],
                           'potential_economic_change_from_low_error': potential})
    return {'source': source_record, 'coordinates': coordinates, 'orders': orders}


def main():
    predecessor = source('CANDIDATES', 3)
    origin = next(ref for ref in predecessor.evidence if ref.name == 'four-gate-quality-impact')
    original = authenticated(origin)
    central = centers()
    assert len(central) == 79
    plan = read(PROTOCOLS / 'plan.json')
    cases = plan['cases']
    rows = read(RUNS / 'rows.json')['rows']
    assert len(cases) == len(rows) == 711
    expected = {(case['candidate_id'], case['kind']) for case in cases}
    completed = {(row['candidate_id'], row['kind']) for row in rows}
    assert len(expected) == len(completed) == 711 and expected == completed
    assert Counter(case['kind'] for case in cases) == {'PARAMETERS': 632, 'STRESS': 79}
    assert all(row['status'] == 'SUCCEEDED' for row in rows)

    first, _ = cache_read(center_cache(central[0].identity.key.candidate_id))
    data = first.execution_data
    assert data is not None
    actual_anomalies = anomaly_values(data, original)
    coordinates, orders, sources = [], [], []
    low = original['low_error']
    shared_contract = {'data_identity': data.fingerprint, 'pricing': original['pricing'],
                       'high_error_dates': original['high_error_dates'], 'low_error': low}
    tasks = []
    for entry in central:
        assert len(entry.evaluations) == 1
        tasks.append({**shared_contract, 'reference': entry.evaluations[0].evidence.to_dict(),
                      'category': 'CENTER', 'candidate_id': entry.identity.key.candidate_id})
    for row in rows:
        tasks.append({**shared_contract, 'reference': row['reference'],
                      'category': row['kind'], 'candidate_id': row['candidate_id']})
    assert len(tasks) == 790
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        environ[variable] = '1'
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context('spawn')) as pool:
        for result in pool.map(inspect_published, tasks, chunksize=1):
            sources.append(result['source'])
            coordinates.extend(result['coordinates'])
            orders.extend(result['orders'])
    counts = Counter(item['category'] for item in coordinates)
    assert counts == {'CENTER': 79, 'PARAMETERS': 632, 'STRESS': 158}, counts
    assert len({item['evaluation_id'] for item in coordinates}) == len(coordinates)
    potential_count = sum(item['potential_economic_change_from_low_error'] for item in orders)
    write(RUNS / 'quality_impact.json', {
        'status': 'PASS' if potential_count == 0 else 'POTENTIALLY_AFFECTED',
        'source': origin.to_dict(), 'original_execution_data_identity': original['execution_data_identity'],
        'execution_data_identity': data.fingerprint, 'pricing': original['pricing'],
        'scope': '79 original center accounts, 632 parameter accounts and 158 pressure coordinates; actual published orders only',
        'published_account_requests': len(sources), 'new_published_account_requests': len(rows),
        'audit_resources': {'max_workers': 4, 'native_threads_per_worker': 1, 'start_method': 'spawn',
                            'evaluation_overlap': False, 'worker_return': 'small authenticated audit facts'},
        'evaluation_coordinates': len(coordinates), 'coordinate_counts': dict(counts),
        'coordinates': coordinates, 'account_sources': sources,
        'high_error_dates': original['high_error_dates'], 'high_error_use': original['high_error_use'],
        'low_error': low, 'current_anomaly_values': actual_anomalies,
        'orders_on_error_dates': orders, 'potential_economic_change_count': potential_count,
        'boundaries': [
            'Original data and quality evidence remain immutable; no repaired intraday trajectory is invented.',
            'Every account is authenticated and has the same current full-range execution-data fingerprint and original pricing contract.',
            'Current raw and normalized low-error values equal the preserved values; the four dated high differences still exist.',
            'BUY LIMIT consumes Open/Low and SELL MARKET consumes Open; the checked high differences are not consumed by these order types.',
            'This checks only the five declared residual anomalies. Unknown errors, intraday corrections and supplier publication history are outside this audit.',
        ],
    })
    print({'quality_impact': 'PASS' if potential_count == 0 else 'POTENTIALLY_AFFECTED',
           'coordinates': len(coordinates), 'potential_economic_change_count': potential_count}, flush=True)


if __name__ == '__main__':
    main()
