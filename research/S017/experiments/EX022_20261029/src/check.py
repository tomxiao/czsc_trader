"""Focused shape, support and source-bound pre-run checks."""
from datetime import date, timedelta
import check_entries
from study import (WORK, NAMES, HORIZONS, background_segments, compare, block_weights,
                   duration_task, horizon_task, save, digest)


def main():
    checks = check_entries.run()
    facts = [{'i': i, 'signals': names} for i, names in enumerate([
        ['B', 'F'], [], ['B'], ['B', 'C', 'T'], ['B', 'H'], [], ['B']])]
    parts = background_segments(facts)
    assert len(parts) == 3 and parts[0]['left_censored'] and parts[-1]['right_censored']
    assert parts[1]['members'] == [2, 3, 4] and parts[1]['signals']['T'] == [3]
    try:
        background_segments([facts[0], facts[2]])
    except ValueError:
        pass
    else:
        raise AssertionError('Missing index bridged')
    days = [str(date(2020, 1, 1)+timedelta(days=i)) for i in range(25)]
    rows = [{'i': i, 'n': 13, 'date': d, 'month': d[:7], 'stratum': d[:7]+'|10:00',
             'price_net_return': (i-10)/100, 'status': 'COMPLETE'} for i, d in enumerate(days)]
    weights, _ = block_weights(len(days), replicates=10)
    item, _ = compare(rows, rows[:2], days, weights, True)
    assert item['matched']['support']['self_in_control_events'] == 2
    assert item['matched']['support']['all_target_cell_events'] == 0
    all_item, _ = compare(rows[:2], rows[:2], days, weights, True)
    assert all_item['matched']['support']['all_target_cell_events'] == 2
    signals = {name: set(range(j, 25, 5)) for j, name in enumerate(NAMES)}
    signals['B'] = set(range(25))
    n, result, _ = horizon_task((13, rows, signals, days, weights))
    assert n == '13' and result['signals']['T']['raw']['matched']['unmatched_indices'] == []
    by_n = {n: [dict(r, n=n, price_net_return=r['price_net_return']+n/10000) for r in rows] for n in HORIZONS}
    by_n[130][0]['price_net_return'] = None
    by_n[130][0]['status'] = 'RIGHT_CENSORED_EXIT'
    _, duration, _ = duration_task(('B', by_n, signals['B'], days, weights))
    assert duration['nonoverlap130']['preselected_indices'] == [0]
    assert duration['nonoverlap130']['common_complete_indices'] == []
    assert len(duration['raw']['common_complete_indices']) == 24
    checks += ['background_segment_censoring_and_gap', 'self_control_support',
               'horizon_statistics_integration', 'common_cohort_no_replacement']
    sources = {p.name: digest(p) for p in (WORK/'src').glob('*.py') if p.stem != 'render'}
    assert 'verify.py' in sources
    save(WORK/'others/checks.json', {'status': 'PASS', 'checks': checks, 'sources': sources,
                                  'workers': 2, 'native_threads': 1})
    print('FOCUSED_CHECKS_PASS', len(checks), flush=True)


if __name__ == '__main__':
    main()
