"""The DEV account comparator must not hide semantic or foreign-key changes."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope='module')
def benchmark():
    path = Path(__file__).resolve().parents[2] / 'scripts/benchmarks/equity_replay_benchmark.py'
    spec = importlib.util.spec_from_file_location('equity_replay_benchmark_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accounts():
    stamp = '2020-01-02T14:30:00.000000Z'
    result = {key: [] for key in ('decisions', 'orders', 'fills', 'actions',
                                'account_points', 'account_daily', 'trades')}
    for index in range(2):
        point = f'2020-01-02T{14 + index}:30:00.000000Z'
        decision, order, fill, cycle = (f'{kind}{index}' for kind in ('d', 'o', 'f', 'c'))
        result['decisions'].append(dict(decision_id=decision, observed_through=stamp,
            decision_at=point, execution_start=point, execution_end=point,
            portfolio_revision=index, reference_price=100., explanation={'basis': [{'key': 'atr', 'text': '0.123'}]}))
        result['orders'].append(dict(order_id=order, decision_id=decision, valid_start=point,
                                     valid_end=point, side='BUY'))
        result['fills'].append(dict(fill_id=fill, order_id=order, cycle_id=cycle, side='BUY',
                                    interval_start=point, interval_end=point, price=100.))
        for table in ('account_points', 'account_daily'):
            result[table].append(dict(decision_id=decision, cycle_id=cycle, equity=1000., time=point))
        result['trades'].append(dict(cycle_id=cycle, entry_at=point, income=1000.))
    return result


def translated(reference):
    result = deepcopy(reference)
    for rows in result.values():
        for row in rows:
            for key, value in row.items():
                if key.endswith('_id'):
                    row[key] = 'new-' + value
                elif isinstance(value, str) and value.endswith('.000000Z'):
                    row[key] = value.replace('.000000Z', '+00:00')
    return result


def test_identity_bijection_and_timezone_only_are_equal(benchmark):
    reference = accounts()
    actual = translated(reference)
    maps = benchmark.identity_maps(reference, actual)
    assert all(len(value) == 2 for value in maps.values())
    assert benchmark.differences(reference, actual)['count'] > 0
    assert benchmark.differences(benchmark.normalized(reference), benchmark.normalized(actual, maps))['count'] == 0


@pytest.mark.parametrize('table,field', [('account_points', 'cycle_id'), ('account_daily', 'decision_id'),
                                       ('trades', 'cycle_id')])
def test_existing_foreign_key_cross_link_is_not_hidden(benchmark, table, field):
    reference = accounts()
    actual = translated(reference)
    actual[table][0][field] = actual[table][1][field]
    maps = benchmark.identity_maps(reference, actual)
    assert benchmark.differences(benchmark.normalized(reference), benchmark.normalized(actual, maps))['count'] == 1


def test_orphan_and_nonbijective_roots_rejected(benchmark):
    reference = accounts()
    actual = translated(reference)
    actual['account_points'][0]['cycle_id'] = 'orphan'
    with pytest.raises(ValueError, match='Orphan'):
        benchmark.identity_maps(reference, actual)
    actual = translated(reference)
    actual['decisions'][1]['decision_id'] = actual['decisions'][0]['decision_id']
    with pytest.raises(ValueError, match='one-to-one'):
        benchmark.identity_maps(reference, actual)


def test_price_and_explanation_changes_are_not_rounded(benchmark):
    reference = accounts()
    actual = translated(reference)
    actual['fills'][0]['price'] += 1e-10
    actual['decisions'][0]['explanation']['basis'][0]['text'] = '0.12300000000000001'
    maps = benchmark.identity_maps(reference, actual)
    assert benchmark.differences(benchmark.normalized(reference), benchmark.normalized(actual, maps))['count'] == 2


def test_account_loading_statistics_require_one_startup_load(benchmark):
    statistics = {'source_checks': 0, 'source_bytes_read': 6400, 'module_loads': 1}
    benchmark.validate_runtime_statistics(statistics, 6400)
    for key, value in (('source_checks', 1), ('source_checks', False),
                       ('module_loads', 0), ('module_loads', 2), ('source_bytes_read', 12800)):
        with pytest.raises(ValueError, match=key):
            benchmark.validate_runtime_statistics({**statistics, key: value}, 6400)
