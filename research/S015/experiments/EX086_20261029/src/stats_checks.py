"""Synthetic checks of census summaries; no historical prices or research imports."""
from math import isclose

import numpy as np

from stats import block_weights, bootstrap, concentration, match, nonoverlap, stats, summarize


def _raises(call, message):
    try:
        call()
    except ValueError as error:
        assert message in str(error)
    else:
        raise AssertionError('Expected explicit ValueError')


def _row(i, value, stratum='2025-01|09:30', day=None):
    return {
        'i': i, 'date': day or f'2025-01-{i + 1:02d}', 'stratum': stratum,
        'price_net_return': value, 'information_return': None if value is None else value + .002,
        'close_path_min': None if value is None else min(0, value),
        'close_path_max': None if value is None else max(0, value),
        'status': 'NO_ENTRY' if value is None else 'COMPLETE',
        'entry_status': 'LIMIT_NOT_CROSSED' if value is None else 'FILLED',
        'exit_status': 'NOT_OBSERVED' if value is None else 'FILLED',
    }


def run_checks():
    checks = []
    value = stats([None, .1, -.2, 0., .3])
    expected = {
        'count': 4, 'mean': .05, 'median': .05, 'win_rate': .5, 'flat_rate': .25,
        'average_win': .2, 'average_loss_magnitude': .2, 'payoff_ratio': 1.,
        'q10': -.14, 'q90': .24,
    }
    assert set(value) == set(expected)
    assert all(isclose(value[k], v, abs_tol=1e-14) for k, v in expected.items())
    assert stats([None]) == {'count': 0}
    assert stats([.1])['average_loss_magnitude'] is None
    assert stats([-.1])['average_win'] is None
    assert stats([0.])['payoff_ratio'] is None
    checks.append('stats_null_flat_and_one_sided_payoff_boundaries')

    rows = [_row(0, .1), _row(1, -.2), _row(2, .4, '2025-02|09:30'), _row(3, None)]
    result = summarize(rows)
    assert result['events'] == result['signal_days'] == 4
    assert result['price']['count'] == result['information']['count'] == 3
    assert result['status'] == {'COMPLETE': 3, 'NO_ENTRY': 1}
    assert result['exit_status'] == {'FILLED': 3, 'NOT_OBSERVED': 1}
    assert summarize([])['price'] == {'count': 0}
    selected = [rows[0], rows[2], rows[3]]
    value = match(rows, selected)
    assert value['count'] == 2
    assert isclose(value['control_mean'], .175, abs_tol=1e-14)
    assert isclose(value['difference']['mean'], .075, abs_tol=1e-14)
    assert value['control_support'] == {
        'unique_cells': 2, 'singleton_target_events': 1, 'all_target_cell_events': 1,
        'median_control_events_per_target': 1.5, 'minimum_control_events': 1,
    }
    entire = match(rows, rows)
    assert entire['control_support']['all_target_cell_events'] == 3
    assert isclose(entire['difference']['mean'], 0, abs_tol=1e-14)
    assert match(rows, [])['control_mean'] is None
    assert match([], [])['control_support']['minimum_control_events'] is None
    _raises(lambda: match(rows[:2], [rows[2]]), 'lacks matched control support')
    checks.append('planned_entry_denominators_stratum_matching_and_self_support')

    assert nonoverlap([], 2) == set()
    assert nonoverlap([0, 1, 3, 4, 7, 8, 9], 2) == {0, 4, 8}
    assert nonoverlap([0, 2, 3, 4, 6], 1) == {0, 3, 6}
    checks.append('greedy_strict_boundary_excludes_held_and_exit_indices')

    values = [_row(0, .1, day='2025-01-01'), _row(1, -.9, day='2025-02-01'),
              _row(2, .3, day='2026-01-01'), _row(3, None, day='2027-01-01')]
    concentrated = concentration(values)
    assert concentrated['positive_sum_by_year'] == {'2025': .1, '2026': .3, '2027': 0}
    assert isclose(concentrated['largest_event_share'], .75)
    assert isclose(concentrated['largest_year_share'], .75)
    assert concentration([])['positive_sum_by_year'] == {}
    assert concentration([values[1]])['largest_event_share'] is None
    checks.append('concentration_uses_observed_years_and_positive_returns_only')

    weights, fingerprint = block_weights(45, replicates=12)
    again, same = block_weights(45, replicates=12)
    assert fingerprint == same and len(fingerprint) == 64
    assert np.array_equal(weights, again)
    assert weights.shape == (12, 45) and np.all(weights.sum(axis=1) == 45)
    assert np.issubdtype(weights.dtype, np.integer) and np.all(weights >= 0)
    full, _ = block_weights(20, replicates=3)
    assert np.array_equal(full, np.ones((3, 20), dtype=np.int32))
    _raises(lambda: block_weights(19), 'Insufficient trading days')
    checks.append('moving_blocks_reproducible_count_conserving_and_short_sample_rejected')

    rows = [_row(i, value, day=f'2025-01-{1 + i // 2:02d}')
            for i, value in enumerate([.1, -.2, .3, .4, -.1, .2])]
    selected = [rows[0], rows[2], rows[4]]
    days = sorted({row['date'] for row in rows})
    weights = np.array([[2, 0, 1], [0, 1, 2], [0, 0, 0]])
    result, draws = bootstrap(rows, selected, rows, days, weights)
    # Independently expand integer repetition weights into explicit observations.
    expected_means, expected_differences = [], []
    for weight in weights[:2]:
        targets = [row['price_net_return'] for row in selected
                   for _ in range(weight[days.index(row['date'])])]
        controls = [row['price_net_return'] for row in rows
                    for _ in range(weight[days.index(row['date'])])]
        mean = sum(targets) / len(targets)
        expected_means.append(mean)
        expected_differences.append(mean - sum(controls) / len(controls))
    assert np.allclose(draws['price_mean'][:2], expected_means, rtol=0, atol=1e-14)
    assert np.allclose(draws['matched_difference'][:2], expected_differences, rtol=0, atol=1e-14)
    fixed_control = sum(row['price_net_return'] for row in rows) / len(rows)
    assert not isclose(draws['matched_difference'][0], expected_means[0] - fixed_control)
    assert draws['price_mean'][2] is draws['matched_difference'][2] is None
    assert result['matched_difference']['valid_replicates'] == 2
    assert result['matched_difference']['empty_replicates'] == 1
    assert np.allclose(result['matched_difference']['interval_95'],
                       np.quantile(expected_differences, [.025, .975]), rtol=0, atol=1e-14)
    empty, empty_draws = bootstrap(rows, [], rows, days, weights)
    assert empty['price_mean'] == {'valid_replicates': 0, 'empty_replicates': 3, 'interval_95': None}
    assert empty_draws['matched_difference'] == [None, None, None]
    _raises(lambda: bootstrap(rows, selected, [], days, weights), 'lacks positive-weight matched controls')
    checks.append('bootstrap_reestimates_control_from_repeated_days_and_retains_empty_draws')

    # Different strata must be reestimated separately; never a pooled benchmark.
    rows[2]['stratum'] = rows[3]['stratum'] = 'second'
    _, draws = bootstrap(rows, [rows[0], rows[2]], rows, days, np.array([[1, 1, 1]]))
    assert isclose(draws['matched_difference'][0], ((.1 - 0.) + (.3 - .35)) / 2, abs_tol=1e-14)
    checks.append('bootstrap_preserves_distinct_matched_strata')
    return checks


if __name__ == '__main__':
    completed = run_checks()
    print('STATS_CHECKS PASS', len(completed))
